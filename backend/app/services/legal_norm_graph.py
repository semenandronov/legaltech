"""Граф норм справочника: узлы (article-level) и рёбра отсылок."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from langchain_core.documents import Document
from sqlalchemy import text

from app.config import config
from app.services.legal_instruments import instrument_validity, resolve_instrument
from app.services.legal_norm_cross_ref import (
    ParsedCrossRef,
    make_norm_node_key,
    parse_cross_reference,
    parse_cross_references_from_text,
)

logger = logging.getLogger(__name__)

_SCHEMA_READY = False

EDGE_TYPES_FORWARD = ("FORWARD_TO", "REFERENCES", "DEVELOPS")


def _engine():
    from app.services.pgvector_store import get_case_vector_store

    return get_case_vector_store().engine


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    from pathlib import Path

    migration_path = Path(__file__).resolve().parents[2] / "migrations" / "031_legal_norm_graph.sql"
    try:
        sql = migration_path.read_text(encoding="utf-8")
    except OSError:
        sql = _FALLBACK_DDL

    engine = _engine()
    with engine.begin() as conn:
        for stmt in _split_sql_statements(sql):
            if stmt.strip():
                conn.execute(text(stmt))
    _SCHEMA_READY = True
    logger.info("legal_norm_graph schema ensured")


_FALLBACK_DDL = """
CREATE TABLE IF NOT EXISTS legal_norm_nodes (
    norm_node_key TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    corpus_file_id TEXT,
    instrument_id TEXT NOT NULL,
    article_number TEXT NOT NULL,
    clause_ref TEXT NOT NULL DEFAULT '',
    full_path TEXT NOT NULL DEFAULT '',
    valid_from DATE,
    valid_to DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS legal_norm_graph_edges (
    id TEXT PRIMARY KEY,
    source_norm_key TEXT NOT NULL,
    target_norm_key TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    source_ref_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_norm_key, target_norm_key, edge_type)
);
"""


def _split_sql_statements(sql: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts


def sync_nodes_from_documents(
    documents: Sequence[Document],
    *,
    corpus_file_id: str,
    instrument_id: str,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
) -> int:
    """Upsert article-level norm nodes из проиндексированных чанков."""
    ensure_schema()
    if not documents:
        return 0

    vf, vt = valid_from, valid_to
    if vf is None and vt is None:
        vf, vt = instrument_validity(instrument_id)

    rows: List[Dict[str, Any]] = []
    for doc in documents:
        md = dict(doc.metadata or {})
        if md.get("chunk_level") != "norm":
            continue
        norm_key = str(md.get("norm_node_key") or "").strip()
        chunk_id = str(md.get("chunk_id") or "").strip()
        art = str(md.get("article_number") or "").strip()
        if not norm_key or not chunk_id or not art:
            continue
        rows.append(
            {
                "norm_node_key": norm_key,
                "chunk_id": chunk_id,
                "corpus_file_id": corpus_file_id,
                "instrument_id": instrument_id,
                "article_number": art,
                "clause_ref": str(md.get("clause_ref") or "").strip(),
                "full_path": str(md.get("full_path") or "").strip(),
                "valid_from": vf,
                "valid_to": vt,
            }
        )

    if not rows:
        return 0

    engine = _engine()
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO legal_norm_nodes (
                        norm_node_key, chunk_id, corpus_file_id, instrument_id,
                        article_number, clause_ref, full_path, valid_from, valid_to, updated_at
                    ) VALUES (
                        :norm_node_key, :chunk_id, :corpus_file_id, :instrument_id,
                        :article_number, :clause_ref, :full_path, :valid_from, :valid_to, NOW()
                    )
                    ON CONFLICT (norm_node_key) DO UPDATE SET
                        chunk_id = EXCLUDED.chunk_id,
                        corpus_file_id = EXCLUDED.corpus_file_id,
                        instrument_id = EXCLUDED.instrument_id,
                        article_number = EXCLUDED.article_number,
                        clause_ref = EXCLUDED.clause_ref,
                        full_path = EXCLUDED.full_path,
                        valid_from = EXCLUDED.valid_from,
                        valid_to = EXCLUDED.valid_to,
                        updated_at = NOW()
                    """
                ),
                row,
            )
    return len(rows)


def _lookup_target_norm_key(
    conn: Any,
    *,
    instrument_id: str,
    article_number: str,
    clause_ref: str = "",
    reference_date: Optional[date] = None,
) -> Optional[str]:
    params: Dict[str, Any] = {
        "iid": instrument_id,
        "art": article_number,
        "cref": clause_ref or "",
    }
    date_clause = ""
    if reference_date:
        params["ref_date"] = reference_date
        date_clause = """
          AND (valid_from IS NULL OR valid_from <= :ref_date)
          AND (valid_to IS NULL OR valid_to >= :ref_date)
        """
    if clause_ref:
        row = conn.execute(
            text(
                f"""
                SELECT norm_node_key FROM legal_norm_nodes
                WHERE instrument_id = :iid AND article_number = :art AND clause_ref = :cref
                {date_clause}
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            params,
        ).fetchone()
        if row:
            return str(row[0])
    row = conn.execute(
        text(
            f"""
            SELECT norm_node_key FROM legal_norm_nodes
            WHERE instrument_id = :iid AND article_number = :art
            {date_clause}
            ORDER BY CASE WHEN clause_ref = '' THEN 0 ELSE 1 END, updated_at DESC
            LIMIT 1
            """
        ),
        params,
    ).fetchone()
    return str(row[0]) if row else None


def build_edges_for_documents(
    documents: Sequence[Document],
    *,
    source_instrument_id: str,
    reference_date: Optional[date] = None,
) -> int:
    """Резолвит cross_references → рёбра графа."""
    ensure_schema()
    if not documents:
        return 0

    engine = _engine()
    inserted = 0
    with engine.begin() as conn:
        for doc in documents:
            md = dict(doc.metadata or {})
            if md.get("chunk_level") != "norm":
                continue
            source_key = str(md.get("norm_node_key") or "").strip()
            if not source_key:
                continue
            body = doc.page_content or ""
            raw_refs = list(md.get("cross_references") or [])
            parsed_refs: List[ParsedCrossRef] = []
            for raw in raw_refs:
                p = parse_cross_reference(
                    str(raw),
                    source_text=body,
                    default_instrument_id=source_instrument_id,
                )
                if p:
                    parsed_refs.append(p)
            if not parsed_refs:
                parsed_refs = parse_cross_references_from_text(
                    body,
                    default_instrument_id=source_instrument_id,
                )

            unresolved: List[str] = []
            for pref in parsed_refs:
                target_iid = pref.target_instrument_id or source_instrument_id
                target_key = _lookup_target_norm_key(
                    conn,
                    instrument_id=target_iid,
                    article_number=pref.article_number,
                    clause_ref=pref.clause_ref,
                    reference_date=reference_date,
                )
                if not target_key:
                    unresolved.append(pref.raw_text)
                    continue
                if target_key == source_key:
                    continue
                edge_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        """
                        INSERT INTO legal_norm_graph_edges (
                            id, source_norm_key, target_norm_key, edge_type,
                            source_ref_text, confidence
                        ) VALUES (
                            :id, :source, :target, :etype, :ref_text, :conf
                        )
                        ON CONFLICT (source_norm_key, target_norm_key, edge_type) DO NOTHING
                        """
                    ),
                    {
                        "id": edge_id,
                        "source": source_key,
                        "target": target_key,
                        "etype": pref.edge_type,
                        "ref_text": pref.raw_text,
                        "conf": 1.0,
                    },
                )
                inserted += 1

            if unresolved and bool(getattr(config, "LEGAL_NORM_LLM_EXTRACTOR_ENABLED", False)):
                try:
                    from app.services.legal_norm_llm_extractor import resolve_unresolved_refs_llm

                    llm_refs = resolve_unresolved_refs_llm(
                        body,
                        source_instrument_id=source_instrument_id,
                        unresolved_raw=unresolved,
                    )
                    for pref in llm_refs:
                        target_iid = pref.target_instrument_id or source_instrument_id
                        target_key = _lookup_target_norm_key(
                            conn,
                            instrument_id=target_iid,
                            article_number=pref.article_number,
                            clause_ref=pref.clause_ref,
                            reference_date=reference_date,
                        )
                        if not target_key or target_key == source_key:
                            continue
                        conn.execute(
                            text(
                                """
                                INSERT INTO legal_norm_graph_edges (
                                    id, source_norm_key, target_norm_key, edge_type,
                                    source_ref_text, confidence
                                ) VALUES (
                                    :id, :source, :target, :etype, :ref_text, :conf
                                )
                                ON CONFLICT (source_norm_key, target_norm_key, edge_type) DO NOTHING
                                """
                            ),
                            {
                                "id": str(uuid.uuid4()),
                                "source": source_key,
                                "target": target_key,
                                "etype": pref.edge_type,
                                "ref_text": pref.raw_text,
                                "conf": 0.85,
                            },
                        )
                        inserted += 1
                except Exception as exc:
                    logger.warning("LLM cross-ref resolver failed: %s", exc)

    return inserted


def delete_graph_for_corpus_file(corpus_file_id: str) -> int:
    ensure_schema()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM legal_norm_graph_edges
                WHERE source_norm_key IN (
                    SELECT norm_node_key FROM legal_norm_nodes WHERE corpus_file_id = :fid
                )
                   OR target_norm_key IN (
                    SELECT norm_node_key FROM legal_norm_nodes WHERE corpus_file_id = :fid
                )
                """
            ),
            {"fid": corpus_file_id},
        )
        result = conn.execute(
            text("DELETE FROM legal_norm_nodes WHERE corpus_file_id = :fid"),
            {"fid": corpus_file_id},
        )
        return int(result.rowcount or 0)


def expand_norm_neighbors(
    source_norm_keys: Sequence[str],
    *,
    edge_types: Sequence[str] = EDGE_TYPES_FORWARD,
    limit: int = 12,
    reference_date: Optional[date] = None,
) -> List[str]:
    """1-hop expand: norm_node_key → соседние norm_node_key."""
    ensure_schema()
    keys = [str(k).strip() for k in source_norm_keys if str(k).strip()]
    if not keys:
        return []

    etypes = [str(e).strip().upper() for e in edge_types if str(e).strip()]
    if not etypes:
        etypes = list(EDGE_TYPES_FORWARD)

    engine = _engine()
    placeholders = ", ".join(f":sk{i}" for i in range(len(keys)))
    et_placeholders = ", ".join(f":et{i}" for i in range(len(etypes)))
    params: Dict[str, Any] = {f"sk{i}": k for i, k in enumerate(keys)}
    params.update({f"et{i}": e for i, e in enumerate(etypes)})
    params["lim"] = max(1, int(limit))

    date_clause = ""
    if reference_date:
        params["ref_date"] = reference_date
        date_clause = """
          AND (n.valid_from IS NULL OR n.valid_from <= :ref_date)
          AND (n.valid_to IS NULL OR n.valid_to >= :ref_date)
        """

    sql = f"""
        SELECT DISTINCT e.target_norm_key
        FROM legal_norm_graph_edges e
        JOIN legal_norm_nodes n ON n.norm_node_key = e.target_norm_key
        WHERE e.source_norm_key IN ({placeholders})
          AND e.edge_type IN ({et_placeholders})
          {date_clause}
        LIMIT :lim
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    out: List[str] = []
    seen: Set[str] = set(keys)
    for r in rows:
        k = str(r[0])
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def fetch_documents_by_norm_keys(
    norm_keys: Sequence[str],
    *,
    reference_date: Optional[date] = None,
) -> List[Document]:
    """Загрузить чанки PGVector по norm_node_key."""
    keys = [str(k).strip() for k in norm_keys if str(k).strip()]
    if not keys:
        return []

    ensure_schema()
    from app.services.legal_corpus_service import LEGAL_CORPUS_CASE_ID

    engine = _engine()
    placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
    params: Dict[str, Any] = {f"k{i}": k for i, k in enumerate(keys)}
    date_clause = ""
    if reference_date:
        params["ref_date"] = reference_date
        date_clause = """
          AND (valid_from IS NULL OR valid_from <= :ref_date)
          AND (valid_to IS NULL OR valid_to >= :ref_date)
        """

    with engine.connect() as conn:
        node_rows = conn.execute(
            text(
                f"""
                SELECT chunk_id, norm_node_key, full_path, instrument_id, article_number
                FROM legal_norm_nodes
                WHERE norm_node_key IN ({placeholders})
                {date_clause}
                """
            ),
            params,
        ).fetchall()

    if not node_rows:
        return []

    chunk_ids = [str(r[0]) for r in node_rows]
    cid_placeholders = ", ".join(f":c{i}" for i in range(len(chunk_ids)))
    cparams = {f"c{i}": cid for i, cid in enumerate(chunk_ids)}
    cparams["case_id"] = LEGAL_CORPUS_CASE_ID

    table = "langchain_pg_embedding"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT document
                FROM {table}
                WHERE case_id = :case_id
                  AND document->'metadata'->>'chunk_id' IN ({cid_placeholders})
                """
            ),
            cparams,
        ).fetchall()

    docs: List[Document] = []
    for r in rows:
        doc_json = r[0] or {}
        if not isinstance(doc_json, dict):
            continue
        pc = doc_json.get("page_content")
        meta = doc_json.get("metadata") or {}
        if pc:
            md = dict(meta)
            md["graph_expanded"] = True
            docs.append(Document(page_content=pc, metadata=md))
    return docs


def is_norm_valid_on_date(
    *,
    valid_from: Optional[date],
    valid_to: Optional[date],
    reference_date: Optional[date],
) -> bool:
    if reference_date is None:
        return True
    if valid_from and reference_date < valid_from:
        return False
    if valid_to and reference_date > valid_to:
        return False
    return True
