"""Reconcile norm graph after incremental chapter uploads (127-ФЗ по главам)."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.documents import Document
from sqlalchemy import text

from app.services.legal_corpus_service import LEGAL_CORPUS_CASE_ID
from app.services.legal_norm_cross_ref import make_norm_node_key
from app.services.legal_norm_graph import (
    _insert_edge,
    build_edges_for_documents,
    ensure_schema,
)
from app.services.legal_norm_structure import clause_sort_key

logger = logging.getLogger(__name__)


def _engine():
    from app.services.pgvector_store import get_case_vector_store

    return get_case_vector_store().engine


def load_norm_documents_for_instrument(instrument_id: str) -> List[Document]:
    """Все norm-чанки акта из pgvector (для reconcile отсылок)."""
    iid = (instrument_id or "").strip().lower()
    if not iid:
        return []

    from app.services.pgvector_store import get_case_vector_store

    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT e.uuid, e.document
                FROM {table} e
                WHERE e.collection_id = :collection_id
                  AND e.case_id = :case_id
                  AND e.document->'metadata'->>'instrument_id' = :iid
                  AND e.document->'metadata'->>'chunk_level' = 'norm'
                """
            ),
            {
                "collection_id": store.collection_name,
                "case_id": LEGAL_CORPUS_CASE_ID,
                "iid": iid,
            },
        ).fetchall()

    docs: List[Document] = []
    for row in rows:
        payload = row[1]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        content = str(payload.get("page_content") or "")
        meta = dict(payload.get("metadata") or {})
        if not content.strip():
            continue
        docs.append(Document(page_content=content, metadata=meta))
    return docs


def reconcile_article_next_chain(instrument_id: str) -> int:
    """
    Склеить NEXT между соседними статьями по всему акту (между главами/файлами).
    Одна статья = article-level norm_node_key без clause.
    """
    ensure_schema()
    iid = (instrument_id or "").strip().lower()
    if not iid:
        return 0

    engine = _engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT article_number
                FROM legal_norm_nodes
                WHERE instrument_id = :iid
                  AND article_number IS NOT NULL
                  AND article_number <> ''
                  AND (clause_ref IS NULL OR clause_ref = '')
                """
            ),
            {"iid": iid},
        ).fetchall()

    articles = sorted({str(r[0]).strip() for r in rows if r and r[0]}, key=clause_sort_key)
    if len(articles) < 2:
        return 0

    inserted = 0
    engine = _engine()
    with engine.begin() as conn:
        prev_key: Optional[str] = None
        for art in articles:
            art_key = make_norm_node_key(iid, art)
            row = conn.execute(
                text(
                    """
                    SELECT norm_node_key FROM legal_norm_nodes
                    WHERE instrument_id = :iid AND article_number = :art
                    ORDER BY CASE WHEN clause_ref = '' THEN 0 ELSE 1 END
                    LIMIT 1
                    """
                ),
                {"iid": iid, "art": art},
            ).fetchone()
            if not row:
                continue
            current_key = str(row[0])
            if prev_key and prev_key != current_key:
                if _insert_edge(conn, source_key=prev_key, target_key=current_key, edge_type="NEXT"):
                    inserted += 1
            prev_key = current_key

    return inserted


def reconcile_instrument_graph(instrument_id: str) -> Dict[str, int]:
    """
    После загрузки очередной главы:
    - пересобрать cross-ref рёбра по всем norm-чанкам акта;
    - склеить NEXT между статьями по всему акту.
    """
    iid = (instrument_id or "").strip().lower()
    docs = load_norm_documents_for_instrument(iid)
    cross_ref = 0
    if docs:
        cross_ref = build_edges_for_documents(docs, source_instrument_id=iid)
    next_edges = reconcile_article_next_chain(iid)
    stats = {
        "norm_chunks": len(docs),
        "cross_ref_edges": cross_ref,
        "next_edges": next_edges,
    }
    logger.info("Legal norm graph reconciled instrument=%s stats=%s", iid, stats)
    return stats


def reconcile_instruments(instrument_ids: Sequence[str]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for raw in instrument_ids:
        iid = str(raw or "").strip().lower()
        if not iid or iid == "other":
            continue
        out[iid] = reconcile_instrument_graph(iid)
    return out
