"""Health checks for legal corpus indexing (post-upload validation)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text

from app.services.legal_corpus_service import LEGAL_CORPUS_CASE_ID

logger = logging.getLogger(__name__)


@dataclass
class CorpusFileIndexHealth:
    corpus_file_id: str
    instrument_id: str
    chunk_count: int
    norm_chunk_count: int
    norm_node_count: int
    graph_edge_count: int
    articles_with_numbers: int
    ok: bool
    issues: List[str] = field(default_factory=list)


def _engine():
    from app.services.pgvector_store import get_case_vector_store

    return get_case_vector_store().engine


def assess_corpus_file_index(
    *,
    corpus_file_id: str,
    instrument_id: str,
    chunk_count: int,
) -> CorpusFileIndexHealth:
    """Проверка после индексации одного файла (главы)."""
    fid = (corpus_file_id or "").strip()
    iid = (instrument_id or "").strip().lower()
    issues: List[str] = []

    norm_chunk_count = 0
    norm_node_count = 0
    graph_edge_count = 0
    articles_with_numbers = 0

    if chunk_count <= 0:
        issues.append("empty_chunk_index")
    elif iid and iid != "other":
        store = get_case_vector_store()
        with store.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM langchain_pg_embedding e
                    WHERE e.collection_id = :collection_id
                      AND e.case_id = :case_id
                      AND e.document->'metadata'->>'corpus_file_id' = :fid
                      AND e.document->'metadata'->>'chunk_level' = 'norm'
                    """
                ),
                {
                    "collection_id": store.collection_name,
                    "case_id": LEGAL_CORPUS_CASE_ID,
                    "fid": fid,
                },
            ).fetchone()
            norm_chunk_count = int(row[0] or 0) if row else 0

            row = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM legal_norm_nodes
                    WHERE corpus_file_id = :fid
                    """
                ),
                {"fid": fid},
            ).fetchone()
            norm_node_count = int(row[0] or 0) if row else 0

            row = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT article_number) FROM legal_norm_nodes
                    WHERE corpus_file_id = :fid
                      AND article_number IS NOT NULL
                      AND article_number <> ''
                    """
                ),
                {"fid": fid},
            ).fetchone()
            articles_with_numbers = int(row[0] or 0) if row else 0

            row = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM legal_norm_graph_edges e
                    WHERE e.source_norm_key IN (
                        SELECT norm_node_key FROM legal_norm_nodes WHERE corpus_file_id = :fid
                    )
                       OR e.target_norm_key IN (
                        SELECT norm_node_key FROM legal_norm_nodes WHERE corpus_file_id = :fid
                    )
                    """
                ),
                {"fid": fid},
            ).fetchone()
            graph_edge_count = int(row[0] or 0) if row else 0

        if norm_node_count == 0:
            issues.append("no_norm_nodes_for_file")
        if norm_chunk_count == 0:
            issues.append("no_norm_chunks_for_file")
        if articles_with_numbers == 0:
            issues.append("no_article_numbers_in_metadata")
        if graph_edge_count == 0 and norm_node_count > 0:
            issues.append("no_graph_edges_for_file")

    ok = not issues
    return CorpusFileIndexHealth(
        corpus_file_id=fid,
        instrument_id=iid,
        chunk_count=chunk_count,
        norm_chunk_count=norm_chunk_count,
        norm_node_count=norm_node_count,
        graph_edge_count=graph_edge_count,
        articles_with_numbers=articles_with_numbers,
        ok=ok,
        issues=issues,
    )


def log_corpus_file_index_health(health: CorpusFileIndexHealth) -> None:
    if health.ok:
        logger.info(
            "Legal corpus index health OK file=%s instrument=%s chunks=%s nodes=%s articles=%s edges=%s",
            health.corpus_file_id,
            health.instrument_id,
            health.chunk_count,
            health.norm_node_count,
            health.articles_with_numbers,
            health.graph_edge_count,
        )
        return
    logger.warning(
        "Legal corpus index health ISSUES file=%s instrument=%s issues=%s chunks=%s nodes=%s",
        health.corpus_file_id,
        health.instrument_id,
        health.issues,
        health.chunk_count,
        health.norm_node_count,
    )


def assert_corpus_file_index_health(health: CorpusFileIndexHealth) -> None:
    """Строгий режим: сбой индексации при проблемах графа/норм."""
    from app.config import config

    strict = bool(getattr(config, "LEGAL_CORPUS_INDEX_GRAPH_VALIDATION_STRICT", False))
    if not strict or health.ok:
        return
    raise ValueError(
        f"Индексация справочника не прошла проверку качества: {', '.join(health.issues)}"
    )
