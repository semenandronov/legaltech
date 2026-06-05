"""
Semantic + lexical index over messages in one chat session.

No phrase triggers — retrieval is always query-driven.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.session_context_types import RelevantTurn, Scope
from app.utils.database import engine as _shared_engine

logger = logging.getLogger(__name__)

_schema_lock = threading.Lock()
_schema_ready = False


@dataclass(frozen=True)
class IndexedMessageHit:
    message_id: str
    role: str
    content: str
    score: float


def session_message_index_enabled() -> bool:
    return bool(getattr(config, "SESSION_CONTEXT_SEMANTIC_ENABLED", True))


def _recall_k() -> int:
    return max(3, int(getattr(config, "SESSION_CONTEXT_SEARCH_K", 8) or 8))


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
                        CREATE TABLE IF NOT EXISTS chat_session_message_index (
                            message_id VARCHAR(64) PRIMARY KEY,
                            scope VARCHAR(16) NOT NULL,
                            session_key VARCHAR(512) NOT NULL,
                            role VARCHAR(20) NOT NULL,
                            content TEXT NOT NULL DEFAULT '',
                            search_text TEXT NOT NULL DEFAULT '',
                            fts_vector tsvector,
                            embedding vector(256),
                            created_at TIMESTAMPTZ,
                            indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chat_session_msg_session "
                        "ON chat_session_message_index (scope, session_key)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chat_session_msg_fts "
                        "ON chat_session_message_index USING gin(fts_vector)"
                    )
                )
            _schema_ready = True
        except Exception as exc:
            logger.warning("chat_session_message_index schema ensure failed: %s", exc)


def upsert_session_message_index(
    db: Session,
    *,
    message_id: str,
    scope: Scope,
    session_key: str,
    role: str,
    content: str,
    created_at=None,
) -> bool:
    if not session_message_index_enabled():
        return False
    mid = (message_id or "").strip()
    sk = (session_key or "").strip()
    if not mid or not sk:
        return False
    body = (content or "").strip()
    if not body:
        return False

    _ensure_schema()
    search_text = body[:12000]
    embedding_sql = "NULL"
    params = {
        "message_id": mid,
        "scope": scope,
        "session_key": sk,
        "role": (role or "user")[:20],
        "content": body[:50000],
        "search_text": search_text,
        "created_at": created_at,
    }

    try:
        from app.services.yandex_embeddings import get_yandex_embeddings

        emb = get_yandex_embeddings()
        vec = emb.embed_documents([search_text[:8000]])[0]
        embedding_sql = "CAST(:embedding AS vector)"
        params["embedding"] = "[" + ",".join(str(float(x)) for x in vec) + "]"
    except Exception as exc:
        logger.debug("session message embedding skipped message=%s: %s", mid, exc)

    try:
        db.execute(
            text(
                f"""
                INSERT INTO chat_session_message_index (
                    message_id, scope, session_key, role, content,
                    search_text, fts_vector, embedding, created_at, indexed_at
                ) VALUES (
                    :message_id, :scope, :session_key, :role, :content,
                    :search_text,
                    to_tsvector('russian', :search_text),
                    {embedding_sql},
                    COALESCE(:created_at, NOW()),
                    NOW()
                )
                ON CONFLICT (message_id) DO UPDATE SET
                    scope = EXCLUDED.scope,
                    session_key = EXCLUDED.session_key,
                    role = EXCLUDED.role,
                    content = EXCLUDED.content,
                    search_text = EXCLUDED.search_text,
                    fts_vector = to_tsvector('russian', EXCLUDED.search_text),
                    embedding = COALESCE(EXCLUDED.embedding, chat_session_message_index.embedding),
                    indexed_at = NOW()
                """
            ),
            params,
        )
        db.flush()
        return True
    except Exception as exc:
        logger.warning("session message index upsert failed id=%s: %s", mid, exc)
        return False


def _fts_search(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    query: str,
    k: int,
) -> List[Tuple[str, str, str, float]]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        rows = db.execute(
            text(
                """
                SELECT message_id, role, content,
                       ts_rank_cd(fts_vector, plainto_tsquery('russian', :q)) AS score
                FROM chat_session_message_index
                WHERE scope = :scope
                  AND session_key = :session_key
                  AND fts_vector @@ plainto_tsquery('russian', :q)
                ORDER BY score DESC
                LIMIT :k
                """
            ),
            {"scope": scope, "session_key": session_key, "q": q[:500], "k": k},
        ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), float(r[3] or 0)) for r in rows]
    except Exception as exc:
        logger.debug("session FTS search failed: %s", exc)
        return []


def _dense_search(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    query: str,
    k: int,
) -> List[Tuple[str, str, str, float]]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        from app.services.yandex_embeddings import get_yandex_embeddings

        emb = get_yandex_embeddings()
        vec = emb.embed_query(q[:4000])
        vector_str = "[" + ",".join(str(float(x)) for x in vec) + "]"
        rows = db.execute(
            text(
                """
                SELECT message_id, role, content,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS score
                FROM chat_session_message_index
                WHERE scope = :scope
                  AND session_key = :session_key
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :k
                """
            ),
            {
                "scope": scope,
                "session_key": session_key,
                "embedding": vector_str,
                "k": k,
            },
        ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), float(r[3] or 0)) for r in rows]
    except Exception as exc:
        logger.debug("session dense search failed: %s", exc)
        return []


def _rrf_merge(
    dense: Sequence[Tuple[str, str, str, float]],
    sparse: Sequence[Tuple[str, str, str, float]],
    *,
    rrf_k: int = 60,
) -> List[IndexedMessageHit]:
    scores: dict[str, float] = {}
    meta: dict[str, Tuple[str, str, str]] = {}
    for rank, (mid, role, content, _) in enumerate(dense, start=1):
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        meta[mid] = (mid, role, content)
    for rank, (mid, role, content, _) in enumerate(sparse, start=1):
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        meta[mid] = (mid, role, content)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out: List[IndexedMessageHit] = []
    for mid, sc in ordered:
        m = meta.get(mid)
        if not m:
            continue
        out.append(IndexedMessageHit(message_id=m[0], role=m[1], content=m[2], score=sc))
    return out


def search_session_messages(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    query: str,
    k: Optional[int] = None,
) -> List[RelevantTurn]:
    """Hybrid retrieval over one session — semantic, not phrase-based."""
    sk = (session_key or "").strip()
    if not sk:
        return []
    _ensure_schema()
    limit = k if k is not None else _recall_k()
    dense = _dense_search(db, scope=scope, session_key=sk, query=query, k=limit)
    sparse = _fts_search(db, scope=scope, session_key=sk, query=query, k=limit)
    merged = _rrf_merge(dense, sparse)[:limit]
    return [
        RelevantTurn(
            message_id=h.message_id,
            role=h.role,
            content=h.content,
            score=h.score,
            source="hybrid",
        )
        for h in merged
    ]


def index_session_turns(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    turns: Sequence,
) -> int:
    """Index all turns (idempotent upsert per message_id)."""
    n = 0
    for t in turns:
        if upsert_session_message_index(
            db,
            message_id=t.message_id,
            scope=scope,
            session_key=session_key,
            role=t.role,
            content=t.content,
            created_at=getattr(t, "created_at", None),
        ):
            n += 1
    return n
