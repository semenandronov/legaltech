"""In-process TTL cache for case file catalog (router secretary)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.retrieval_router import CaseFileCatalogEntry

logger = logging.getLogger(__name__)

_CacheRow = Tuple[int, float, List[CaseFileCatalogEntry]]
_cache: Dict[str, _CacheRow] = {}
_guard = threading.Lock()


def _cache_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_CATALOG_CACHE_ENABLED", True))


def _ttl_sec() -> int:
    return max(30, int(getattr(config, "CASE_ASSISTANT_CATALOG_CACHE_TTL_SEC", 600) or 600))


def invalidate_case_catalog_cache(case_id: str) -> None:
    cid = str(case_id or "").strip()
    if not cid:
        return
    with _guard:
        _cache.pop(cid, None)


def get_case_file_catalog_cached(
    db: Session,
    case_id: str,
    *,
    limit: int = 80,
) -> List[CaseFileCatalogEntry]:
    """Load catalog with TTL cache keyed by current file count."""
    cid = str(case_id or "").strip()
    from app.services.chat.retrieval_router import _count_case_files, build_case_file_catalog

    if not cid or not _cache_enabled():
        return build_case_file_catalog(db, cid, limit=limit)

    try:
        file_count = _count_case_files(db, cid)
    except Exception as exc:
        logger.debug("Catalog cache count skipped case=%s: %s", cid, exc)
        return build_case_file_catalog(db, cid, limit=limit)

    now = time.monotonic()
    ttl = _ttl_sec()
    with _guard:
        row = _cache.get(cid)
        if row and row[0] == file_count and row[1] > now:
            return list(row[2])

    entries = build_case_file_catalog(db, cid, limit=limit)
    with _guard:
        _cache[cid] = (file_count, now + ttl, list(entries))
    return entries
