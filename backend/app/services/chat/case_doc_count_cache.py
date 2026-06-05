"""TTL cache for case document count (avoids Neon round-trip per chat turn)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config

logger = logging.getLogger(__name__)

_CacheRow = Tuple[int, float]
_cache: Dict[str, _CacheRow] = {}
_guard = threading.Lock()


def _cache_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_DOC_COUNT_CACHE_ENABLED", True))


def _ttl_sec() -> int:
    return max(30, int(getattr(config, "CASE_ASSISTANT_DOC_COUNT_CACHE_TTL_SEC", 300) or 300))


def invalidate_case_doc_count_cache(case_id: str) -> None:
    cid = str(case_id or "").strip()
    if not cid:
        return
    with _guard:
        _cache.pop(cid, None)


def _store_cached(case_id: str, count: int) -> None:
    cid = str(case_id or "").strip()
    if not cid or count < 0:
        return
    with _guard:
        _cache[cid] = (count, time.monotonic() + _ttl_sec())


def _load_from_db(db: Session, case_id: str) -> int:
    from app.models.case import Case as CaseModel

    case_obj = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if case_obj is None:
        return 0
    return int(case_obj.num_documents or 0)


def resolve_case_doc_count(
    db: Session,
    case_id: str,
    *,
    hint: Optional[int] = None,
) -> int:
    """Resolve document count: client hint → TTL cache → Postgres."""
    cid = str(case_id or "").strip()
    if not cid:
        return 0

    hinted = int(hint or 0)
    if hinted > 0:
        _store_cached(cid, hinted)
        return hinted

    if _cache_enabled():
        now = time.monotonic()
        with _guard:
            row = _cache.get(cid)
            if row and row[1] > now:
                return row[0]

    try:
        count = _load_from_db(db, cid)
    except Exception as exc:
        logger.debug("case doc count db lookup failed case=%s: %s", cid, exc)
        return 0

    _store_cached(cid, count)
    return count
