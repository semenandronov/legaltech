"""
File-level summary index for hierarchical case RAG (retrieval funnel step 1).

Each case file gets one embedding + FTS row built from passport (filename, doc_type,
summary, key_points). Query path: hybrid RRF → dynamic K by score gap → scoped chunk search.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import config
from app.models.analysis import DocumentClassification
from app.models.case import File as CaseFile
from app.utils.database import engine as _shared_engine

logger = logging.getLogger(__name__)

_schema_lock = threading.Lock()
_schema_ready = False
_case_index_locks: Dict[str, threading.Lock] = {}
_case_index_guard = threading.Lock()


@dataclass(frozen=True)
class FileSummaryCandidate:
    file_id: str
    filename: str
    score: float
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None


@dataclass(frozen=True)
class FileScopeResult:
    """Outcome of file-level scope resolution (step 1 before chunk retrieval)."""

    file_ids: List[str]
    reason: str
    top_score: float
    scope_hint: str  # resolved | relaxed | miss
    candidates: Tuple[FileSummaryCandidate, ...] = ()


def file_summary_index_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_INDEX_ENABLED", True))


def _min_score_threshold() -> float:
    return float(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_MIN_SCORE", 0.6) or 0.6)


def _score_gap() -> float:
    return float(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_SCORE_GAP", 0.15) or 0.15)


def _recall_k() -> int:
    return max(5, int(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_RECALL_K", 30) or 30))


def _max_selected_files() -> int:
    return max(1, int(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_MAX_FILES", 20) or 20))


def _relaxed_min_score_threshold() -> float:
    return float(
        getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_RELAXED_MIN_SCORE", 0.35) or 0.35
    )


def _near_miss_top_k() -> int:
    return max(1, int(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_NEAR_MISS_TOP_K", 3) or 3))


def build_search_text(
    *,
    filename: str,
    doc_type: str,
    summary: str,
    key_points: Optional[Sequence[str]] = None,
) -> str:
    parts = [
        str(filename or "").strip(),
        str(doc_type or "").strip(),
        str(summary or "").strip(),
    ]
    if key_points:
        parts.extend(str(x).strip() for x in key_points[:8] if str(x).strip())
    return "\n".join(p for p in parts if p)


def select_file_ids_by_score_gap(
    candidates: List[FileSummaryCandidate],
    *,
    min_threshold: Optional[float] = None,
    max_gap: Optional[float] = None,
    max_files: Optional[int] = None,
) -> Tuple[List[str], str, float]:
    """
    Dynamic K: keep files within max_gap of top score and above min_threshold.

    Returns (file_ids, reason, top_score).
    """
    if not candidates:
        return [], "empty_candidates", 0.0

    threshold = min_threshold if min_threshold is not None else _min_score_threshold()
    gap = max_gap if max_gap is not None else _score_gap()
    cap = max_files if max_files is not None else _max_selected_files()

    sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
    top_score = sorted_cands[0].score
    if top_score < threshold:
        return [], "below_threshold", top_score

    selected: List[str] = []
    for cand in sorted_cands:
        if cand.score < threshold:
            break
        if (top_score - cand.score) > gap:
            break
        selected.append(cand.file_id)
        if len(selected) >= cap:
            break

    if len(selected) == 1:
        return selected, "single_winner", top_score
    if len(selected) > 1:
        return selected, "dynamic_k_cluster", top_score
    return [], "below_threshold", top_score


def _normalize_rrf_scores(raw: Dict[str, float]) -> Dict[str, float]:
    if not raw:
        return {}
    max_v = max(raw.values())
    if max_v <= 0:
        return {k: 0.0 for k in raw}
    return {k: v / max_v for k, v in raw.items()}


def rrf_merge_file_scores(
    dense: List[Tuple[str, float]],
    sparse: List[Tuple[str, float]],
    *,
    rrf_k: int = 60,
) -> Dict[str, float]:
    """Reciprocal Rank Fusion over file_id lists; returns normalized 0..1 scores."""
    raw: Dict[str, float] = {}
    for rank, (fid, _) in enumerate(dense, start=1):
        raw[fid] = raw.get(fid, 0.0) + 1.0 / (rrf_k + rank)
    for rank, (fid, _) in enumerate(sparse, start=1):
        raw[fid] = raw.get(fid, 0.0) + 1.0 / (rrf_k + rank)
    return _normalize_rrf_scores(raw)


def _ensure_schema() -> None:
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        try:
            with _shared_engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS case_file_summaries (
                            file_id TEXT PRIMARY KEY,
                            case_id TEXT NOT NULL,
                            filename TEXT NOT NULL DEFAULT '',
                            doc_type TEXT,
                            summary_text TEXT NOT NULL DEFAULT '',
                            search_text TEXT NOT NULL DEFAULT '',
                            fts_vector tsvector,
                            embedding vector(256),
                            content_hash VARCHAR(64),
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_case_file_summaries_case_id "
                        "ON case_file_summaries(case_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_case_file_summaries_fts "
                        "ON case_file_summaries USING gin(fts_vector)"
                    )
                )
            with _shared_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                try:
                    conn.execute(
                        text(
                            """
                            CREATE INDEX IF NOT EXISTS idx_case_file_summaries_embedding_hnsw
                            ON case_file_summaries USING hnsw (embedding vector_cosine_ops)
                            WITH (m = 16, ef_construction = 64)
                            """
                        )
                    )
                except Exception as hnsw_exc:
                    logger.debug("HNSW index on case_file_summaries skipped: %s", hnsw_exc)
            _schema_ready = True
        except Exception as exc:
            logger.warning("case_file_summaries schema ensure failed: %s", exc)


def _case_lock(case_id: str) -> threading.Lock:
    with _case_index_guard:
        if case_id not in _case_index_locks:
            _case_index_locks[case_id] = threading.Lock()
        return _case_index_locks[case_id]


def _batch_doc_types(db: Session, file_ids: List[str]) -> Dict[str, str]:
    if not file_ids:
        return {}
    out: Dict[str, str] = {}
    try:
        rows = (
            db.query(DocumentClassification.file_id, DocumentClassification.doc_type)
            .filter(DocumentClassification.file_id.in_(file_ids))
            .all()
        )
        for fid, dtype in rows:
            if fid and dtype:
                out[str(fid)] = str(dtype)
    except Exception:
        pass
    return out


def upsert_file_summary_index(
    db: Session,
    *,
    file_id: str,
    case_id: str,
    filename: str,
    summary: str,
    doc_type: str = "other",
    key_points: Optional[Sequence[str]] = None,
    content_hash: Optional[str] = None,
) -> bool:
    """Index or refresh one file passport row (embedding + FTS)."""
    if not file_summary_index_enabled():
        return False
    _ensure_schema()
    fid = str(file_id or "").strip()
    cid = str(case_id or "").strip()
    if not fid or not cid:
        return False

    search_text = build_search_text(
        filename=filename,
        doc_type=doc_type,
        summary=summary,
        key_points=key_points,
    )
    if not search_text.strip():
        return False

    try:
        from app.services.yandex_embeddings import get_yandex_embeddings

        embeddings = get_yandex_embeddings()
        embed_input = search_text[:8000]
        vector = embeddings.embed_documents([embed_input])[0]
        vector_str = "[" + ",".join(str(float(x)) for x in vector) + "]"
    except Exception as exc:
        logger.warning("File summary embedding failed file=%s: %s", fid, exc)
        return False

    try:
        db.execute(
            text(
                """
                INSERT INTO case_file_summaries (
                    file_id, case_id, filename, doc_type, summary_text,
                    search_text, fts_vector, embedding, content_hash, updated_at
                ) VALUES (
                    :file_id, :case_id, :filename, :doc_type, :summary_text,
                    :search_text,
                    to_tsvector('russian', :search_text),
                    CAST(:embedding AS vector),
                    :content_hash,
                    NOW()
                )
                ON CONFLICT (file_id) DO UPDATE SET
                    case_id = EXCLUDED.case_id,
                    filename = EXCLUDED.filename,
                    doc_type = EXCLUDED.doc_type,
                    summary_text = EXCLUDED.summary_text,
                    search_text = EXCLUDED.search_text,
                    fts_vector = to_tsvector('russian', EXCLUDED.search_text),
                    embedding = EXCLUDED.embedding,
                    content_hash = EXCLUDED.content_hash,
                    updated_at = NOW()
                """
            ),
            {
                "file_id": fid,
                "case_id": cid,
                "filename": str(filename or "")[:255],
                "doc_type": str(doc_type or "other")[:64],
                "summary_text": str(summary or "")[:2000],
                "search_text": search_text[:12000],
                "embedding": vector_str,
                "content_hash": content_hash,
            },
        )
        db.flush()
        return True
    except Exception as exc:
        logger.warning("File summary upsert failed file=%s: %s", fid, exc)
        return False


def delete_file_summary_index(file_id: str) -> None:
    fid = str(file_id or "").strip()
    if not fid:
        return
    _ensure_schema()
    try:
        with _shared_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM case_file_summaries WHERE file_id = :fid"),
                {"fid": fid},
            )
    except Exception as exc:
        logger.debug("File summary delete failed file=%s: %s", fid, exc)


def ensure_case_summaries_indexed(db: Session, case_id: str) -> int:
    """Backfill missing summary rows for a case (lazy, once per case lock)."""
    if not file_summary_index_enabled():
        return 0
    cid = str(case_id or "").strip()
    if not cid:
        return 0
    _ensure_schema()

    with _case_lock(cid):
        indexed = 0
        try:
            missing = db.execute(
                text(
                    """
                    SELECT f.id, f.case_id, f.filename, f.doc_summary_short,
                           f.doc_key_points, f.summary_content_hash
                    FROM files f
                    LEFT JOIN case_file_summaries cfs ON cfs.file_id = f.id
                    WHERE f.case_id = :case_id
                      AND f.doc_summary_short IS NOT NULL
                      AND TRIM(f.doc_summary_short) <> ''
                      AND (
                        cfs.file_id IS NULL
                        OR cfs.content_hash IS DISTINCT FROM f.summary_content_hash
                      )
                    """
                ),
                {"case_id": cid},
            ).fetchall()
        except Exception as exc:
            logger.debug("ensure_case_summaries_indexed query failed: %s", exc)
            return 0

        if not missing:
            return 0

        file_ids = [str(r[0]) for r in missing]
        doc_types = _batch_doc_types(db, file_ids)

        for row in missing:
            fid = str(row[0])
            kps_raw = row[4]
            kps: List[str] = []
            if isinstance(kps_raw, list):
                kps = [str(x) for x in kps_raw[:8]]
            elif isinstance(kps_raw, str):
                try:
                    parsed = json.loads(kps_raw)
                    if isinstance(parsed, list):
                        kps = [str(x) for x in parsed[:8]]
                except Exception:
                    pass
            ok = upsert_file_summary_index(
                db,
                file_id=fid,
                case_id=cid,
                filename=str(row[2] or ""),
                summary=str(row[3] or ""),
                doc_type=doc_types.get(fid, "other"),
                key_points=kps,
                content_hash=str(row[5] or "") or None,
            )
            if ok:
                indexed += 1
        if indexed:
            try:
                db.flush()
            except Exception:
                pass
        return indexed


def _vector_search_files(
    *,
    case_id: str,
    query_embedding_str: str,
    k: int,
) -> List[Tuple[str, float]]:
    sql = """
        SELECT file_id, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM case_file_summaries
        WHERE case_id = :case_id AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT :k
    """
    try:
        with _shared_engine.connect() as conn:
            rows = conn.execute(
                text(sql),
                {"qvec": query_embedding_str, "case_id": case_id, "k": k},
            ).fetchall()
        return [(str(r[0]), float(r[1] or 0.0)) for r in rows]
    except Exception as exc:
        logger.warning("File summary vector search failed case=%s: %s", case_id, exc)
        return []


def _fts_search_files(
    *,
    case_id: str,
    query: str,
    k: int,
) -> List[Tuple[str, float]]:
    sql = """
        SELECT file_id,
               ts_rank_cd(fts_vector, websearch_to_tsquery('russian', :query)) AS rank
        FROM case_file_summaries
        WHERE case_id = :case_id
          AND fts_vector @@ websearch_to_tsquery('russian', :query)
        ORDER BY rank DESC
        LIMIT :k
    """
    try:
        with _shared_engine.connect() as conn:
            rows = conn.execute(
                text(sql),
                {"query": query, "case_id": case_id, "k": k},
            ).fetchall()
        return [(str(r[0]), float(r[1] or 0.0)) for r in rows]
    except Exception as exc:
        logger.warning("File summary FTS failed case=%s: %s", case_id, exc)
        return []


def search_file_summaries_hybrid(
    db: Session,
    *,
    case_id: str,
    question: str,
) -> List[FileSummaryCandidate]:
    """
    Hybrid step-1 retrieval over file passports (vector + FTS → RRF).
    """
    if not file_summary_index_enabled():
        return []

    cid = str(case_id or "").strip()
    q = (question or "").strip()
    if not cid or not q:
        return []

    _ensure_schema()
    ensure_case_summaries_indexed(db, cid)

    k = _recall_k()
    from app.services.observability.case_assistant_langfuse_tracing import case_assistant_span

    with case_assistant_span(
        "file_summary_scope",
        input_payload={"question": q[:800], "recall_k": k},
        metadata={"case_id": cid},
    ) as summary_span:
        try:
            from app.services.yandex_embeddings import get_yandex_embeddings

            with case_assistant_span(
                "file_summary.embed",
                metadata={"case_id": cid},
            ) as embed_span:
                embeddings = get_yandex_embeddings()
                query_vec = embeddings.embed_query(q[:4000])
                query_vec_str = "[" + ",".join(str(float(x)) for x in query_vec) + "]"
                embed_span["embedding_dim"] = len(query_vec or [])
        except Exception as exc:
            logger.warning("File summary query embed failed: %s", exc)
            summary_span["error"] = str(exc)[:300]
            return []

        with case_assistant_span("file_summary.dense", metadata={"case_id": cid}) as d_span:
            dense = _vector_search_files(case_id=cid, query_embedding_str=query_vec_str, k=k)
            d_span["hits"] = len(dense)
        with case_assistant_span("file_summary.fts", metadata={"case_id": cid}) as s_span:
            sparse = _fts_search_files(case_id=cid, query=q, k=k)
            s_span["hits"] = len(sparse)
        merged = rrf_merge_file_scores(dense, sparse)
        summary_span["dense_hits"] = len(dense)
        summary_span["fts_hits"] = len(sparse)
        summary_span["merged_files"] = len(merged)

    if not merged:
        return []

    filename_map: Dict[str, str] = {}
    try:
        rows = db.execute(
            text(
                "SELECT file_id, filename FROM case_file_summaries WHERE case_id = :cid"
            ),
            {"cid": cid},
        ).fetchall()
        filename_map = {str(r[0]): str(r[1] or "") for r in rows}
    except Exception:
        pass

    dense_rank = {fid: i + 1 for i, (fid, _) in enumerate(dense)}
    sparse_rank = {fid: i + 1 for i, (fid, _) in enumerate(sparse)}

    candidates = [
        FileSummaryCandidate(
            file_id=fid,
            filename=filename_map.get(fid, ""),
            score=score,
            dense_rank=dense_rank.get(fid),
            sparse_rank=sparse_rank.get(fid),
        )
        for fid, score in sorted(merged.items(), key=lambda x: x[1], reverse=True)
    ]
    return candidates


def _resolve_file_scope_from_candidates(
    candidates: List[FileSummaryCandidate],
) -> FileScopeResult:
    """Pick file scope from hybrid summary candidates (strict → relaxed → top-K)."""
    if not candidates:
        return FileScopeResult([], "empty_candidates", 0.0, "miss", ())

    file_ids, reason, top_score = select_file_ids_by_score_gap(candidates)
    if file_ids:
        return FileScopeResult(
            file_ids,
            reason,
            top_score,
            "resolved",
            tuple(candidates),
        )

    relaxed_ids, relaxed_reason, _ = select_file_ids_by_score_gap(
        candidates,
        min_threshold=_relaxed_min_score_threshold(),
        max_gap=_score_gap() * 2,
    )
    if relaxed_ids:
        return FileScopeResult(
            relaxed_ids,
            f"relaxed_{relaxed_reason}",
            top_score,
            "relaxed",
            tuple(candidates),
        )

    top_k = _near_miss_top_k()
    sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
    near_ids = [c.file_id for c in sorted_cands[:top_k]]
    if near_ids and sorted_cands[0].score > 0:
        return FileScopeResult(
            near_ids,
            "near_miss_top_k",
            top_score,
            "relaxed",
            tuple(candidates),
        )

    return FileScopeResult(
        [],
        reason or "below_threshold",
        top_score,
        "miss",
        tuple(candidates),
    )


def resolve_file_scope(
    db: Session,
    *,
    case_id: str,
    question: str,
    case_file_count: int = 0,
) -> FileScopeResult:
    """
    Step-1 funnel: hybrid search over file passports → dynamic file scope.

    scope_hint:
      resolved — confident match (score gap cluster above main threshold)
      relaxed  — weaker match (lower threshold or top-K near miss)
      miss     — no usable signal from summary index
    """
    count = case_file_count or 0
    if count <= 0:
        try:
            count = int(
                db.query(CaseFile.id).filter(CaseFile.case_id == case_id).count()
            )
        except Exception:
            count = 0

    if count == 1:
        try:
            only = (
                db.query(CaseFile.id)
                .filter(CaseFile.case_id == case_id)
                .limit(1)
                .scalar()
            )
            if only:
                return FileScopeResult(
                    [str(only)],
                    "single_file_shortcut",
                    1.0,
                    "resolved",
                    (),
                )
        except Exception:
            pass

    candidates = search_file_summaries_hybrid(db, case_id=case_id, question=question)
    return _resolve_file_scope_from_candidates(candidates)


def resolve_files_for_question(
    db: Session,
    *,
    case_id: str,
    question: str,
    case_file_count: int = 0,
) -> Tuple[List[str], str, float, str]:
    """
    Back-compat wrapper. Prefer resolve_file_scope for new code.

    scope_hint legacy mapping: resolved | full_case_fallback
    """
    result = resolve_file_scope(
        db,
        case_id=case_id,
        question=question,
        case_file_count=case_file_count,
    )
    if result.file_ids and result.scope_hint == "resolved":
        return result.file_ids, result.reason, result.top_score, "resolved"
    if result.file_ids and result.scope_hint == "relaxed":
        return result.file_ids, result.reason, result.top_score, "resolved"
    return [], result.reason, result.top_score, "full_case_fallback"
