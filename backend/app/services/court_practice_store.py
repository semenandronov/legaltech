"""Postgres storage + hybrid search for cad_precedent_chunks (Giga 2560-dim)."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

from app.config import config
from app.utils.database import engine as _shared_engine

logger = logging.getLogger(__name__)

_schema_lock = threading.Lock()
_schema_ready = False


@dataclass(frozen=True)
class CourtPracticeHit:
    chunk_id: str
    document_id: str
    case_number: str
    court_name: Optional[str]
    court_tier: str
    judgment_date: Optional[date]
    chunk_index: int
    chunk_text: str
    score: float
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None


def _embedding_dim() -> int:
    return int(getattr(config, "GIGACHAT_EMBEDDING_DIM", 2560) or 2560)


def _rrf_k() -> int:
    return int(getattr(config, "COURT_PRACTICE_RRF_K", 60) or 60)


def _vector_recall_k() -> int:
    return int(getattr(config, "COURT_PRACTICE_VECTOR_RECALL_K", 50) or 50)


def _fts_recall_k() -> int:
    return int(getattr(config, "COURT_PRACTICE_FTS_RECALL_K", 50) or 50)


def _max_chunks_per_case() -> int:
    return int(getattr(config, "COURT_PRACTICE_MAX_CHUNKS_PER_CASE", 3) or 3)


def _hnsw_max_dimensions() -> int:
    return int(getattr(config, "COURT_PRACTICE_HNSW_MAX_DIM", 2000) or 2000)


def _should_create_hnsw_index() -> bool:
    return _embedding_dim() <= _hnsw_max_dimensions()


def _is_vector_ann_index_stmt(stmt: str) -> bool:
    lowered = stmt.lower()
    return "using hnsw" in lowered or "using ivfflat" in lowered


def _maybe_create_hnsw_index() -> None:
    if not _should_create_hnsw_index():
        logger.info(
            "cad_precedent_chunks: HNSW skipped (embedding dim=%s > Neon limit %s); exact vector scan + FTS",
            _embedding_dim(),
            _hnsw_max_dimensions(),
        )
        return
    with _shared_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cad_precedent_chunks_embedding_hnsw
                    ON cad_precedent_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    """
                )
            )
            logger.info("cad_precedent_chunks: HNSW index ready")
        except Exception as hnsw_exc:
            logger.warning("cad_precedent_chunks: HNSW index not created: %s", hnsw_exc)


def _tables_ready(conn) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'cad_precedent_chunks'
            LIMIT 1
            """
        )
    ).fetchone()
    return row is not None


def ensure_schema() -> None:
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        migration_path = None
        try:
            from pathlib import Path

            migration_path = (
                Path(__file__).resolve().parents[2] / "migrations" / "028_cad_precedents.sql"
            )
        except Exception:
            migration_path = None
        try:
            with _shared_engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                if migration_path and migration_path.is_file():
                    sql = migration_path.read_text(encoding="utf-8")
                    for stmt in _split_sql_statements(sql):
                        stripped = stmt.strip()
                        if not stripped or _is_vector_ann_index_stmt(stripped):
                            continue
                        conn.execute(text(stripped))
                else:
                    logger.warning("court_practice migration file not found; using inline DDL")
                    _inline_ddl(conn)
                if not _tables_ready(conn):
                    raise RuntimeError("cad_precedent tables were not created")
            _maybe_create_hnsw_index()
            _schema_ready = True
            logger.info("cad_precedents schema ready")
        except Exception as exc:
            logger.error("cad_precedents schema ensure failed: %s", exc, exc_info=True)
            raise


def _split_sql_statements(sql: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if ";" in line:
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts


def _inline_ddl(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS cad_precedent_documents (
                id TEXT PRIMARY KEY,
                source_row_id TEXT,
                case_number TEXT NOT NULL DEFAULT '',
                cad_case_number TEXT,
                court_name TEXT,
                court_tier TEXT,
                judgment_date DATE,
                act_kind TEXT,
                outcome_summary TEXT,
                raw_text TEXT,
                batch_id TEXT,
                created_by_user_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS cad_precedent_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES cad_precedent_documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                chunk_text TEXT NOT NULL,
                embedding vector(2560),
                fts_vector tsvector,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_cad_precedent_documents_case_number
            ON cad_precedent_documents(case_number)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_cad_precedent_documents_batch_id
            ON cad_precedent_documents(batch_id)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_cad_precedent_chunks_document_id
            ON cad_precedent_chunks(document_id)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_cad_precedent_chunks_fts
            ON cad_precedent_chunks USING gin(fts_vector)
            """
        )
    )


def count_chunks() -> int:
    ensure_schema()
    with _shared_engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM cad_precedent_chunks")).fetchone()
        return int(row[0] if row else 0)


def count_documents() -> int:
    ensure_schema()
    with _shared_engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM cad_precedent_documents")).fetchone()
        return int(row[0] if row else 0)


def list_batches(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_schema()
    with _shared_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT batch_id,
                       COUNT(DISTINCT d.id) AS documents,
                       COUNT(c.id) AS chunks,
                       MIN(d.created_at) AS created_at
                FROM cad_precedent_documents d
                LEFT JOIN cad_precedent_chunks c ON c.document_id = d.id
                WHERE batch_id IS NOT NULL
                GROUP BY batch_id
                ORDER BY MIN(d.created_at) DESC
                LIMIT :lim
                """
            ),
            {"lim": max(1, limit)},
        ).fetchall()
    return [
        {
            "batch_id": r[0],
            "documents": int(r[1] or 0),
            "chunks": int(r[2] or 0),
            "created_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]


def delete_batch(batch_id: str) -> Tuple[int, int]:
    ensure_schema()
    bid = (batch_id or "").strip()
    if not bid:
        return 0, 0
    with _shared_engine.begin() as conn:
        doc_rows = conn.execute(
            text("SELECT id FROM cad_precedent_documents WHERE batch_id = :bid"),
            {"bid": bid},
        ).fetchall()
        doc_ids = [str(r[0]) for r in doc_rows]
        if not doc_ids:
            return 0, 0
        chunk_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM cad_precedent_chunks WHERE document_id = ANY(:ids)"
            ),
            {"ids": doc_ids},
        ).scalar()
        conn.execute(
            text("DELETE FROM cad_precedent_documents WHERE batch_id = :bid"),
            {"bid": bid},
        )
        return len(doc_ids), int(chunk_count or 0)


def delete_all() -> Tuple[int, int]:
    ensure_schema()
    with _shared_engine.begin() as conn:
        docs = conn.execute(text("SELECT COUNT(*) FROM cad_precedent_documents")).scalar()
        chunks = conn.execute(text("SELECT COUNT(*) FROM cad_precedent_chunks")).scalar()
        conn.execute(text("DELETE FROM cad_precedent_chunks"))
        conn.execute(text("DELETE FROM cad_precedent_documents"))
        return int(docs or 0), int(chunks or 0)


def insert_document_with_chunks(
    *,
    source_row_id: str,
    case_number: str,
    cad_case_number: Optional[str],
    court_name: Optional[str],
    court_tier: str,
    judgment_date: Optional[date],
    act_kind: Optional[str],
    raw_text: str,
    batch_id: str,
    created_by_user_id: Optional[str],
    chunks: Sequence[Tuple[int, str, List[float]]],
) -> Tuple[str, int]:
    """Insert document + chunks. chunks: (index, text, embedding)."""
    ensure_schema()
    doc_id = str(uuid.uuid4())
    with _shared_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO cad_precedent_documents (
                    id, source_row_id, case_number, cad_case_number, court_name,
                    court_tier, judgment_date, act_kind, raw_text, batch_id, created_by_user_id
                ) VALUES (
                    :id, :source_row_id, :case_number, :cad_case_number, :court_name,
                    :court_tier, :judgment_date, :act_kind, :raw_text, :batch_id, :user_id
                )
                """
            ),
            {
                "id": doc_id,
                "source_row_id": source_row_id,
                "case_number": case_number,
                "cad_case_number": cad_case_number,
                "court_name": court_name,
                "court_tier": court_tier,
                "judgment_date": judgment_date,
                "act_kind": act_kind,
                "raw_text": raw_text,
                "batch_id": batch_id,
                "user_id": created_by_user_id,
            },
        )
        inserted = 0
        for chunk_index, chunk_text, embedding in chunks:
            chunk_id = str(uuid.uuid4())
            emb_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
            conn.execute(
                text(
                    """
                    INSERT INTO cad_precedent_chunks (
                        id, document_id, chunk_index, chunk_text, embedding, fts_vector
                    ) VALUES (
                        :id, :document_id, :chunk_index, :chunk_text,
                        CAST(:embedding AS vector), to_tsvector('russian', :chunk_text)
                    )
                    """
                ),
                {
                    "id": chunk_id,
                    "document_id": doc_id,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                    "embedding": emb_str,
                },
            )
            inserted += 1
    return doc_id, inserted


def _vector_to_param(vec: List[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def _dense_search(query_embedding: List[float], k: int) -> List[CourtPracticeHit]:
    ensure_schema()
    q = _vector_to_param(query_embedding)
    sql = """
        SELECT c.id, c.document_id, d.case_number, d.court_name, d.court_tier, d.judgment_date,
               c.chunk_index, c.chunk_text,
               1 - (c.embedding <=> CAST(:q AS vector)) AS score
        FROM cad_precedent_chunks c
        JOIN cad_precedent_documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:q AS vector)
        LIMIT :k
    """
    with _shared_engine.connect() as conn:
        rows = conn.execute(text(sql), {"q": q, "k": k}).fetchall()
    hits: List[CourtPracticeHit] = []
    for rank, row in enumerate(rows, start=1):
        hits.append(
            CourtPracticeHit(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                case_number=str(row[2] or ""),
                court_name=row[3],
                court_tier=str(row[4] or "unknown"),
                judgment_date=row[5],
                chunk_index=int(row[6] or 0),
                chunk_text=str(row[7] or ""),
                score=float(row[8] or 0.0),
                dense_rank=rank,
            )
        )
    return hits


def _fts_search(query: str, k: int) -> List[CourtPracticeHit]:
    ensure_schema()
    q = (query or "").strip()
    if not q:
        return []
    sql = """
        SELECT c.id, c.document_id, d.case_number, d.court_name, d.court_tier, d.judgment_date,
               c.chunk_index, c.chunk_text,
               ts_rank_cd(c.fts_vector, websearch_to_tsquery('russian', :q)) AS score
        FROM cad_precedent_chunks c
        JOIN cad_precedent_documents d ON d.id = c.document_id
        WHERE c.fts_vector @@ websearch_to_tsquery('russian', :q)
        ORDER BY score DESC
        LIMIT :k
    """
    with _shared_engine.connect() as conn:
        rows = conn.execute(text(sql), {"q": q, "k": k}).fetchall()
    hits: List[CourtPracticeHit] = []
    for rank, row in enumerate(rows, start=1):
        hits.append(
            CourtPracticeHit(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                case_number=str(row[2] or ""),
                court_name=row[3],
                court_tier=str(row[4] or "unknown"),
                judgment_date=row[5],
                chunk_index=int(row[6] or 0),
                chunk_text=str(row[7] or ""),
                score=float(row[8] or 0.0),
                sparse_rank=rank,
            )
        )
    return hits


def fts_search(query: str, k: int) -> List[CourtPracticeHit]:
    """Public wrapper: FTS recall without vector embedding."""
    return _fts_search(query, k)


def _rrf_merge(
    dense: List[CourtPracticeHit],
    sparse: List[CourtPracticeHit],
) -> List[CourtPracticeHit]:
    k = _rrf_k()
    scores: Dict[str, float] = {}
    by_id: Dict[str, CourtPracticeHit] = {}
    for hits in (dense, sparse):
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            if hit.chunk_id not in by_id:
                by_id[hit.chunk_id] = hit
    merged: List[CourtPracticeHit] = []
    for cid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        base = by_id[cid]
        merged.append(
            CourtPracticeHit(
                chunk_id=base.chunk_id,
                document_id=base.document_id,
                case_number=base.case_number,
                court_name=base.court_name,
                court_tier=base.court_tier,
                judgment_date=base.judgment_date,
                chunk_index=base.chunk_index,
                chunk_text=base.chunk_text,
                score=score,
                dense_rank=base.dense_rank,
                sparse_rank=base.sparse_rank,
            )
        )
    return merged


def _court_tier_boost(tier: str) -> float:
    return {
        "vs_rf": 1.30,
        "cassation": 1.15,
        "appeal": 1.0,
        "first": 0.92,
    }.get((tier or "").lower(), 1.0)


def _recency_boost(judgment_date: Optional[date]) -> float:
    if not judgment_date:
        return 1.0
    try:
        from datetime import datetime as _dt

        years = (_dt.utcnow().date() - judgment_date).days / 365.25
        if years <= 2:
            return 1.08
        if years <= 5:
            return 1.04
        return 1.0
    except Exception:
        return 1.0


def diversify_by_case(hits: List[CourtPracticeHit], max_per_case: int) -> List[CourtPracticeHit]:
    per_case: Dict[str, int] = {}
    out: List[CourtPracticeHit] = []
    for hit in hits:
        key = hit.case_number or hit.document_id
        if per_case.get(key, 0) >= max_per_case:
            continue
        per_case[key] = per_case.get(key, 0) + 1
        out.append(hit)
    return out


def hybrid_search(
    query: str,
    query_embedding: List[float],
    *,
    vector_k: Optional[int] = None,
    fts_k: Optional[int] = None,
    max_per_case: Optional[int] = None,
) -> List[CourtPracticeHit]:
    vk = vector_k or _vector_recall_k()
    fk = fts_k or _fts_recall_k()
    dense = _dense_search(query_embedding, vk)
    sparse = _fts_search(query, fk)
    merged = _rrf_merge(dense, sparse)
    diversified = diversify_by_case(merged, max_per_case or _max_chunks_per_case())
    boosted: List[CourtPracticeHit] = []
    for hit in diversified:
        score = hit.score * _court_tier_boost(hit.court_tier) * _recency_boost(hit.judgment_date)
        boosted.append(
            CourtPracticeHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                case_number=hit.case_number,
                court_name=hit.court_name,
                court_tier=hit.court_tier,
                judgment_date=hit.judgment_date,
                chunk_index=hit.chunk_index,
                chunk_text=hit.chunk_text,
                score=score,
                dense_rank=hit.dense_rank,
                sparse_rank=hit.sparse_rank,
            )
        )
    boosted.sort(key=lambda h: h.score, reverse=True)
    return boosted


def get_chunk_preview(chunk_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _shared_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.id, c.chunk_text, c.chunk_index,
                       d.case_number, d.court_name, d.court_tier, d.judgment_date, d.act_kind
                FROM cad_precedent_chunks c
                JOIN cad_precedent_documents d ON d.id = c.document_id
                WHERE c.id = :cid
                """
            ),
            {"cid": chunk_id},
        ).fetchone()
    if not row:
        return None
    return {
        "chunk_id": str(row[0]),
        "chunk_text": str(row[1] or ""),
        "chunk_index": int(row[2] or 0),
        "case_number": str(row[3] or ""),
        "court_name": row[4],
        "court_tier": str(row[5] or ""),
        "judgment_date": row[6].isoformat() if row[6] else None,
        "act_kind": row[7],
    }


def format_hits_as_context(hits: Sequence[CourtPracticeHit]) -> str:
    blocks: List[str] = []
    for i, hit in enumerate(hits, start=1):
        date_s = hit.judgment_date.isoformat() if hit.judgment_date else ""
        court = hit.court_name or ""
        blocks.append(
            f'<document id="{i}" case="{hit.case_number}" court="{court}" '
            f'date="{date_s}" tier="{hit.court_tier}">\n{hit.chunk_text}\n</document>'
        )
    return "\n\n".join(blocks)


def hits_to_citation_documents(hits: Sequence[CourtPracticeHit]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for hit in hits:
        label = hit.case_number
        if hit.court_name:
            label = f"{label} ({hit.court_name})"
        docs.append(
            {
                "page_content": hit.chunk_text,
                "metadata": {
                    "source_type": "court_practice",
                    "source_id": hit.chunk_id,
                    "case_number": hit.case_number,
                    "court_name": hit.court_name,
                    "court_tier": hit.court_tier,
                    "judgment_date": hit.judgment_date.isoformat() if hit.judgment_date else None,
                    "file_name": label,
                    "chunk_index": hit.chunk_index,
                    "score": hit.score,
                },
            }
        )
    return docs
