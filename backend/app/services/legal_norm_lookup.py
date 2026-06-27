"""Structured lookup норм по AST-дереву (метаданные + граф), без FTS/вектора."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

from langchain_core.documents import Document
from sqlalchemy import text

from app.services.legal_norm_cross_ref import normalize_article_number
from app.services.legal_norm_structure import clause_sort_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormLookupRequest:
    instrument_id: str
    article_number: str
    clause_ref: Optional[str] = None


def _engine():
    from app.services.pgvector_store import get_case_vector_store

    return get_case_vector_store().engine


def _norm_tree_lookup_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "LEGAL_NORM_TREE_LOOKUP_ENABLED", True))


def fetch_norm_documents(
    requests: Sequence[NormLookupRequest],
    *,
    reference_date: Optional[date] = None,
) -> List[Document]:
    """Загрузить чанки по instrument_id + article_number [+ clause_ref] из legal_norm_nodes."""
    if not requests:
        return []

    from app.services.legal_norm_graph import ensure_schema, fetch_documents_by_norm_keys, is_norm_valid_on_date

    ensure_schema()
    engine = _engine()
    ordered_keys: List[str] = []
    seen_keys: set[str] = set()

    with engine.connect() as conn:
        for req in requests:
            iid = (req.instrument_id or "").strip().lower()
            art = normalize_article_number(req.article_number)
            if not iid or not art:
                continue

            params: dict = {"iid": iid, "art": art}
            date_clause = ""
            if reference_date:
                params["ref_date"] = reference_date
                date_clause = """
                  AND (valid_from IS NULL OR valid_from <= :ref_date)
                  AND (valid_to IS NULL OR valid_to >= :ref_date)
                """

            cref = normalize_article_number(req.clause_ref) if req.clause_ref else ""
            if cref:
                params["cref"] = cref
                clause_sql = " AND clause_ref = :cref"
            else:
                clause_sql = ""

            rows = conn.execute(
                text(
                    f"""
                    SELECT norm_node_key, clause_ref, valid_from, valid_to
                    FROM legal_norm_nodes
                    WHERE instrument_id = :iid
                      AND article_number = :art
                      AND chunk_id IS NOT NULL
                      {clause_sql}
                      {date_clause}
                    """
                ),
                params,
            ).fetchall()

            rows_sorted = sorted(
                rows,
                key=lambda r: clause_sort_key(str(r[1] or "")),
            )
            for row in rows_sorted:
                vf, vt = row[2], row[3]
                if reference_date and not is_norm_valid_on_date(
                    valid_from=vf,
                    valid_to=vt,
                    reference_date=reference_date,
                ):
                    continue
                key = str(row[0] or "").strip()
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    ordered_keys.append(key)

    if not ordered_keys:
        return []

    docs = fetch_documents_by_norm_keys(ordered_keys, reference_date=reference_date)
    if not docs:
        return []

    key_rank = {k: i for i, k in enumerate(ordered_keys)}

    def _sort_key(doc: Document) -> tuple:
        md = doc.metadata or {}
        nk = str(md.get("norm_node_key") or "")
        return (key_rank.get(nk, 10_000), clause_sort_key(str(md.get("clause_ref") or "")))

    return sorted(docs, key=_sort_key)


def fetch_norm_documents_for_plan(
    plan: object,
    *,
    reference_date: Optional[date] = None,
) -> List[Document]:
    """Все пункты целевых статей плана (или один пункт, если задан user_clause_ref)."""
    if not _norm_tree_lookup_enabled():
        return []

    topic = getattr(plan, "topic", None)
    if topic != "article_lookup":
        return []

    instrument_ids: List[str] = list(getattr(plan, "instrument_ids", None) or [])
    if not instrument_ids:
        return []

    user_articles: List[str] = list(getattr(plan, "user_articles", None) or [])
    required_articles: List[str] = list(getattr(plan, "required_articles", None) or [])
    targets = user_articles or required_articles
    if not targets:
        return []

    user_clause_ref = normalize_article_number(getattr(plan, "user_clause_ref", None) or "")
    iid = instrument_ids[0]
    requests: List[NormLookupRequest] = []
    for art in targets[:6]:
        a = normalize_article_number(art)
        if not a:
            continue
        cref: Optional[str] = user_clause_ref if user_clause_ref else None
        requests.append(NormLookupRequest(instrument_id=iid, article_number=a, clause_ref=cref))

    docs = fetch_norm_documents(requests, reference_date=reference_date)
    if docs:
        logger.info(
            "[NormLookup] tree fetch instruments=%s articles=%s clause=%s chunks=%d",
            instrument_ids,
            targets[:6],
            user_clause_ref or "*",
            len(docs),
        )
    return docs


def should_prefer_norm_tree(plan: object) -> bool:
    """Structured lookup уместен для явного article_lookup."""
    if not _norm_tree_lookup_enabled():
        return False
    if getattr(plan, "topic", None) != "article_lookup":
        return False
    arts = list(getattr(plan, "user_articles", None) or []) or list(
        getattr(plan, "required_articles", None) or []
    )
    return bool(arts and getattr(plan, "instrument_ids", None))
