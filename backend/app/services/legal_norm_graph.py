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
from app.services.legal_norm_structure import (
    clause_sort_key,
    extract_chapters_from_parent_path,
    make_article_structure_key,
    make_chapter_node_key,
    make_law_node_key,
)

logger = logging.getLogger(__name__)

_SCHEMA_READY = False

EDGE_TYPES_FORWARD = ("FORWARD_TO", "REFERENCES", "DEVELOPS")
EDGE_TYPES_NAVIGATION = ("NEXT",)
EDGE_TYPES_RETRIEVAL = EDGE_TYPES_FORWARD + EDGE_TYPES_NAVIGATION


def _engine():
    from app.services.pgvector_store import get_case_vector_store

    return get_case_vector_store().engine


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    from pathlib import Path

    migration_paths = [
        Path(__file__).resolve().parents[2] / "migrations" / "031_legal_norm_graph.sql",
        Path(__file__).resolve().parents[2] / "migrations" / "036_legal_norm_structure.sql",
    ]
    try:
        sql_parts = [p.read_text(encoding="utf-8") for p in migration_paths if p.is_file()]
        sql = "\n".join(sql_parts)
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


def _upsert_norm_node(conn: Any, row: Dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO legal_norm_nodes (
                norm_node_key, chunk_id, corpus_file_id, instrument_id,
                article_number, clause_ref, full_path, valid_from, valid_to,
                node_type, parent_norm_key, title, chapter_ref, updated_at
            ) VALUES (
                :norm_node_key, :chunk_id, :corpus_file_id, :instrument_id,
                :article_number, :clause_ref, :full_path, :valid_from, :valid_to,
                :node_type, :parent_norm_key, :title, :chapter_ref, NOW()
            )
            ON CONFLICT (norm_node_key) DO UPDATE SET
                chunk_id = COALESCE(EXCLUDED.chunk_id, legal_norm_nodes.chunk_id),
                corpus_file_id = COALESCE(EXCLUDED.corpus_file_id, legal_norm_nodes.corpus_file_id),
                instrument_id = EXCLUDED.instrument_id,
                article_number = EXCLUDED.article_number,
                clause_ref = EXCLUDED.clause_ref,
                full_path = COALESCE(NULLIF(EXCLUDED.full_path, ''), legal_norm_nodes.full_path),
                valid_from = EXCLUDED.valid_from,
                valid_to = EXCLUDED.valid_to,
                node_type = EXCLUDED.node_type,
                parent_norm_key = COALESCE(EXCLUDED.parent_norm_key, legal_norm_nodes.parent_norm_key),
                title = COALESCE(NULLIF(EXCLUDED.title, ''), legal_norm_nodes.title),
                chapter_ref = COALESCE(NULLIF(EXCLUDED.chapter_ref, ''), legal_norm_nodes.chapter_ref),
                updated_at = NOW()
            """
        ),
        row,
    )


def _insert_edge(
    conn: Any,
    *,
    source_key: str,
    target_key: str,
    edge_type: str,
    ref_text: str = "",
    confidence: float = 1.0,
) -> bool:
    if not source_key or not target_key or source_key == target_key:
        return False
    result = conn.execute(
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
            "etype": edge_type,
            "ref_text": ref_text,
            "conf": confidence,
        },
    )
    return bool(getattr(result, "rowcount", 0))


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
        clause_ref = str(md.get("clause_ref") or "").strip()
        node_type = "clause" if clause_ref else "article"
        rows.append(
            {
                "norm_node_key": norm_key,
                "chunk_id": chunk_id,
                "corpus_file_id": corpus_file_id,
                "instrument_id": instrument_id,
                "article_number": art,
                "clause_ref": clause_ref,
                "full_path": str(md.get("full_path") or "").strip(),
                "valid_from": vf,
                "valid_to": vt,
                "node_type": node_type,
                "parent_norm_key": None,
                "title": str(md.get("section_title") or "").strip(),
                "chapter_ref": "",
            }
        )

    if not rows:
        return 0

    engine = _engine()
    with engine.begin() as conn:
        for row in rows:
            _upsert_norm_node(conn, row)
    return len(rows)


def sync_structure_nodes_and_edges(
    documents: Sequence[Document],
    *,
    corpus_file_id: str,
    instrument_id: str,
    instrument_short_name: str = "",
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
) -> int:
    """Скелет закона: FederalLaw → Chapter → Article → Clause + CHILD_OF / NEXT."""
    ensure_schema()
    norm_docs = [d for d in documents if (d.metadata or {}).get("chunk_level") == "norm"]
    if not norm_docs:
        return 0

    vf, vt = valid_from, valid_to
    if vf is None and vt is None:
        vf, vt = instrument_validity(instrument_id)

    law_key = make_law_node_key(instrument_id)
    law_title = (instrument_short_name or instrument_id).strip()
    edges_added = 0

    by_article: Dict[str, List[Document]] = {}
    for doc in norm_docs:
        art = str((doc.metadata or {}).get("article_number") or "").strip()
        if not art:
            continue
        by_article.setdefault(art, []).append(doc)

    article_order: List[Tuple[int, str]] = []
    for art, docs in by_article.items():
        min_idx = min(int((d.metadata or {}).get("chunk_index") or 0) for d in docs)
        article_order.append((min_idx, art))
    article_order.sort(key=lambda x: x[0])

    engine = _engine()
    with engine.begin() as conn:
        _upsert_norm_node(
            conn,
            {
                "norm_node_key": law_key,
                "chunk_id": None,
                "corpus_file_id": None,
                "instrument_id": instrument_id,
                "article_number": "",
                "clause_ref": "",
                "full_path": law_title,
                "valid_from": vf,
                "valid_to": vt,
                "node_type": "federal_law",
                "parent_norm_key": None,
                "title": law_title,
                "chapter_ref": "",
            },
        )

        prev_article_key: Optional[str] = None
        for _, art in article_order:
            docs = sorted(
                by_article[art],
                key=lambda d: (
                    clause_sort_key(str((d.metadata or {}).get("clause_ref") or "")),
                    int((d.metadata or {}).get("chunk_index") or 0),
                ),
            )
            first_md = dict(docs[0].metadata or {})
            parent_path = list(first_md.get("parent_path") or [])
            chapters = extract_chapters_from_parent_path(parent_path)

            parent_key = law_key
            for ch in chapters:
                ch_key = make_chapter_node_key(instrument_id, ch.chapter_ref)
                _upsert_norm_node(
                    conn,
                    {
                        "norm_node_key": ch_key,
                        "chunk_id": None,
                        "corpus_file_id": None,
                        "instrument_id": instrument_id,
                        "article_number": "",
                        "clause_ref": "",
                        "full_path": ch.title,
                        "valid_from": vf,
                        "valid_to": vt,
                        "node_type": "chapter",
                        "parent_norm_key": parent_key,
                        "title": ch.title,
                        "chapter_ref": ch.chapter_ref,
                    },
                )
                if _insert_edge(conn, source_key=ch_key, target_key=parent_key, edge_type="CHILD_OF"):
                    edges_added += 1
                parent_key = ch_key

            has_numbered_clauses = any(str((d.metadata or {}).get("clause_ref") or "").strip() for d in docs)
            art_key = make_article_structure_key(instrument_id, art)
            section_title = str(first_md.get("section_title") or f"Статья {art}").strip()
            full_path = str(first_md.get("full_path") or "").strip()

            if has_numbered_clauses:
                _upsert_norm_node(
                    conn,
                    {
                        "norm_node_key": art_key,
                        "chunk_id": None,
                        "corpus_file_id": corpus_file_id,
                        "instrument_id": instrument_id,
                        "article_number": art,
                        "clause_ref": "",
                        "full_path": full_path,
                        "valid_from": vf,
                        "valid_to": vt,
                        "node_type": "article",
                        "parent_norm_key": parent_key,
                        "title": section_title,
                        "chapter_ref": chapters[-1].chapter_ref if chapters else "",
                    },
                )
                if _insert_edge(conn, source_key=art_key, target_key=parent_key, edge_type="CHILD_OF"):
                    edges_added += 1

                prev_clause_key: Optional[str] = None
                for doc in docs:
                    md = dict(doc.metadata or {})
                    node_key = str(md.get("norm_node_key") or "").strip()
                    if not node_key:
                        continue
                    cref = str(md.get("clause_ref") or "").strip()
                    node_type = "clause" if cref else "preamble"
                    _upsert_norm_node(
                        conn,
                        {
                            "norm_node_key": node_key,
                            "chunk_id": str(md.get("chunk_id") or "").strip() or None,
                            "corpus_file_id": corpus_file_id,
                            "instrument_id": instrument_id,
                            "article_number": art,
                            "clause_ref": cref,
                            "full_path": str(md.get("full_path") or "").strip(),
                            "valid_from": vf,
                            "valid_to": vt,
                            "node_type": node_type,
                            "parent_norm_key": art_key,
                            "title": section_title,
                            "chapter_ref": chapters[-1].chapter_ref if chapters else "",
                        },
                    )
                    if _insert_edge(conn, source_key=node_key, target_key=art_key, edge_type="CHILD_OF"):
                        edges_added += 1
                    if prev_clause_key and cref:
                        if _insert_edge(conn, source_key=prev_clause_key, target_key=node_key, edge_type="NEXT"):
                            edges_added += 1
                    if cref:
                        prev_clause_key = node_key
            else:
                doc = docs[0]
                md = dict(doc.metadata or {})
                node_key = str(md.get("norm_node_key") or art_key).strip()
                _upsert_norm_node(
                    conn,
                    {
                        "norm_node_key": node_key,
                        "chunk_id": str(md.get("chunk_id") or "").strip() or None,
                        "corpus_file_id": corpus_file_id,
                        "instrument_id": instrument_id,
                        "article_number": art,
                        "clause_ref": "",
                        "full_path": str(md.get("full_path") or "").strip(),
                        "valid_from": vf,
                        "valid_to": vt,
                        "node_type": "article",
                        "parent_norm_key": parent_key,
                        "title": section_title,
                        "chapter_ref": chapters[-1].chapter_ref if chapters else "",
                    },
                )
                if _insert_edge(conn, source_key=node_key, target_key=parent_key, edge_type="CHILD_OF"):
                    edges_added += 1
                art_key = node_key

            if prev_article_key and prev_article_key != art_key:
                if _insert_edge(conn, source_key=prev_article_key, target_key=art_key, edge_type="NEXT"):
                    edges_added += 1
            prev_article_key = art_key

    return edges_added


def sync_legal_norm_graph(
    documents: Sequence[Document],
    *,
    corpus_file_id: str,
    instrument_id: str,
    instrument_short_name: str = "",
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    reference_date: Optional[date] = None,
) -> Dict[str, int]:
    """Полная синхронизация: чанки, скелет, перекрёстные ссылки."""
    chunk_nodes = sync_nodes_from_documents(
        documents,
        corpus_file_id=corpus_file_id,
        instrument_id=instrument_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    structure_edges = sync_structure_nodes_and_edges(
        documents,
        corpus_file_id=corpus_file_id,
        instrument_id=instrument_id,
        instrument_short_name=instrument_short_name,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    cross_ref_edges = build_edges_for_documents(
        documents,
        source_instrument_id=instrument_id,
        reference_date=reference_date,
    )
    return {
        "chunk_nodes": chunk_nodes,
        "structure_edges": structure_edges,
        "cross_ref_edges": cross_ref_edges,
    }


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
            source_art = str(md.get("article_number") or "").strip()
            source_clause = str(md.get("clause_ref") or "").strip()
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
                    source_article_number=source_art or None,
                    source_clause_ref=source_clause or None,
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
                if _insert_edge(
                    conn,
                    source_key=source_key,
                    target_key=target_key,
                    edge_type=pref.edge_type,
                    ref_text=pref.raw_text,
                    confidence=1.0,
                ):
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
                        if _insert_edge(
                            conn,
                            source_key=source_key,
                            target_key=target_key,
                            edge_type=pref.edge_type,
                            ref_text=pref.raw_text,
                            confidence=0.85,
                        ):
                            inserted += 1
                except Exception as exc:
                    logger.warning("LLM cross-ref resolver failed: %s", exc)

    return inserted


def delete_graph_for_instrument(instrument_id: str) -> int:
    """Удалить все узлы и рёбра графа для instrument_id (при полной переиндексации)."""
    ensure_schema()
    iid = (instrument_id or "").strip().lower()
    if not iid:
        return 0
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM legal_norm_graph_edges
                WHERE source_norm_key IN (
                    SELECT norm_node_key FROM legal_norm_nodes WHERE instrument_id = :iid
                )
                   OR target_norm_key IN (
                    SELECT norm_node_key FROM legal_norm_nodes WHERE instrument_id = :iid
                )
                """
            ),
            {"iid": iid},
        )
        result = conn.execute(
            text("DELETE FROM legal_norm_nodes WHERE instrument_id = :iid"),
            {"iid": iid},
        )
        return int(result.rowcount or 0)


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


_EDGE_TYPE_PRIORITY: Dict[str, int] = {
    "FORWARD_TO": 0,
    "REFERENCES": 1,
    "DEVELOPS": 2,
    "NEXT": 3,
    "CHILD_OF": 4,
}


def _norm_keys_for_full_article(
    article_norm_key: str,
    *,
    reference_date: Optional[date] = None,
) -> List[str]:
    """Все norm_node_key с чанками для статьи (как norm tree lookup)."""
    from app.services.legal_norm_cross_ref import parse_article_from_norm_key
    from app.services.legal_norm_structure import clause_sort_key

    parsed = parse_article_from_norm_key(article_norm_key)
    if not parsed:
        return [article_norm_key]

    iid, art = parsed
    params: Dict[str, Any] = {"iid": iid, "art": art}
    date_clause = ""
    if reference_date:
        params["ref_date"] = reference_date
        date_clause = """
          AND (valid_from IS NULL OR valid_from <= :ref_date)
          AND (valid_to IS NULL OR valid_to >= :ref_date)
        """

    engine = _engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT norm_node_key, clause_ref
                FROM legal_norm_nodes
                WHERE instrument_id = :iid
                  AND article_number = :art
                  AND chunk_id IS NOT NULL
                  {date_clause}
                """
            ),
            params,
        ).fetchall()

    if not rows:
        return [article_norm_key]

    rows_sorted = sorted(rows, key=lambda r: clause_sort_key(str(r[1] or "")))
    return [str(r[0]) for r in rows_sorted if r[0]]


def _resolve_fetch_norm_keys(
    keys: Sequence[str],
    *,
    reference_date: Optional[date] = None,
    full_article_for_keys: Optional[Set[str]] = None,
) -> List[str]:
    """Развернуть article-level ключи в полный набор пунктов статьи."""
    full_set = full_article_for_keys or set()
    resolved: List[str] = []
    seen: Set[str] = set()
    for key in keys:
        if key in full_set and "::clause::" not in key:
            for expanded in _norm_keys_for_full_article(key, reference_date=reference_date):
                if expanded not in seen:
                    seen.add(expanded)
                    resolved.append(expanded)
        elif key not in seen:
            seen.add(key)
            resolved.append(key)
    return resolved


def expand_norm_neighbor_edges(
    source_norm_keys: Sequence[str],
    *,
    edge_types: Sequence[str] = EDGE_TYPES_RETRIEVAL,
    limit: int = 12,
    reference_date: Optional[date] = None,
    include_parents: bool = True,
) -> List[Tuple[str, str]]:
    """1-hop expand: (target_norm_key, edge_type)."""
    ensure_schema()
    keys = [str(k).strip() for k in source_norm_keys if str(k).strip()]
    if not keys:
        return []

    etypes = [str(e).strip().upper() for e in edge_types if str(e).strip()]
    if not etypes:
        etypes = list(EDGE_TYPES_RETRIEVAL)

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

    forward_sql = f"""
        SELECT e.target_norm_key AS nk, e.edge_type AS et
        FROM legal_norm_graph_edges e
        JOIN legal_norm_nodes n ON n.norm_node_key = e.target_norm_key
        WHERE e.source_norm_key IN ({placeholders})
          AND e.edge_type IN ({et_placeholders})
          {date_clause}
    """
    parent_sql = ""
    if include_parents:
        parent_sql = f"""
        UNION ALL
        SELECT e.target_norm_key AS nk, 'CHILD_OF' AS et
        FROM legal_norm_graph_edges e
        JOIN legal_norm_nodes n ON n.norm_node_key = e.target_norm_key
        WHERE e.source_norm_key IN ({placeholders})
          AND e.edge_type = 'CHILD_OF'
          {date_clause}
        """

    sql = f"""
        SELECT nk, et FROM (
            {forward_sql}
            {parent_sql}
        ) sub
        LIMIT :lim
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    out: List[Tuple[str, str]] = []
    seen_keys: Set[str] = set(keys)
    best_edge: Dict[str, str] = {}
    for r in rows:
        nk = str(r[0])
        et = str(r[1] or "").strip().upper()
        if nk in seen_keys:
            continue
        prev = best_edge.get(nk)
        if prev is None or _EDGE_TYPE_PRIORITY.get(et, 99) < _EDGE_TYPE_PRIORITY.get(prev, 99):
            best_edge[nk] = et

    for nk, et in best_edge.items():
        seen_keys.add(nk)
        out.append((nk, et))
    return out


def expand_norm_neighbors(
    source_norm_keys: Sequence[str],
    *,
    edge_types: Sequence[str] = EDGE_TYPES_RETRIEVAL,
    limit: int = 12,
    reference_date: Optional[date] = None,
    include_parents: bool = True,
) -> List[str]:
    """1-hop expand: norm_node_key → соседи по отсылкам, NEXT и родителю (CHILD_OF)."""
    return [
        nk
        for nk, _ in expand_norm_neighbor_edges(
            source_norm_keys,
            edge_types=edge_types,
            limit=limit,
            reference_date=reference_date,
            include_parents=include_parents,
        )
    ]


def fetch_documents_by_norm_keys(
    norm_keys: Sequence[str],
    *,
    reference_date: Optional[date] = None,
    full_article_for_keys: Optional[Set[str]] = None,
) -> List[Document]:
    """Загрузить чанки PGVector по norm_node_key."""
    keys = [str(k).strip() for k in norm_keys if str(k).strip()]
    if not keys:
        return []

    ensure_schema()
    from app.services.legal_corpus_service import LEGAL_CORPUS_CASE_ID

    keys = _resolve_fetch_norm_keys(
        keys,
        reference_date=reference_date,
        full_article_for_keys=full_article_for_keys,
    )
    if not keys:
        return []

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

    chunk_ids: List[str] = []
    child_date_clause = ""
    child_params_base: Dict[str, Any] = {}
    if reference_date:
        child_params_base["ref_date"] = reference_date
        child_date_clause = """
          AND (n.valid_from IS NULL OR n.valid_from <= :ref_date)
          AND (n.valid_to IS NULL OR n.valid_to >= :ref_date)
        """

    with engine.connect() as conn:
        for row in node_rows:
            cid = row[0]
            nk = str(row[1])
            if cid:
                chunk_ids.append(str(cid))
                continue
            child_params = {**child_params_base, "nk": nk}
            child_rows = conn.execute(
                text(
                    f"""
                    SELECT n.chunk_id
                    FROM legal_norm_graph_edges e
                    JOIN legal_norm_nodes n ON n.norm_node_key = e.source_norm_key
                    WHERE e.target_norm_key = :nk
                      AND e.edge_type = 'CHILD_OF'
                      AND n.chunk_id IS NOT NULL
                    {child_date_clause}
                    ORDER BY n.clause_ref NULLS FIRST, n.updated_at DESC
                    LIMIT 3
                    """
                ),
                child_params,
            ).fetchall()
            for cr in child_rows:
                if cr[0]:
                    chunk_ids.append(str(cr[0]))

    if not chunk_ids:
        return []
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
