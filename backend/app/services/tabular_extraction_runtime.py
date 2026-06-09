"""Runtime controls for tabular column extraction (concurrency + in-flight runs)."""
from __future__ import annotations

import asyncio
from typing import Optional, Set, Tuple

from app.config import config

_ColumnKey = Tuple[str, str]

_tabular_cell_semaphore: Optional[asyncio.Semaphore] = None
_running_column_runs: Set[_ColumnKey] = set()
_column_run_lock = asyncio.Lock()


def tabular_max_parallel_cells() -> int:
    return max(1, int(getattr(config, "TABULAR_MAX_PARALLEL_CELLS", 5) or 5))


def tabular_cell_semaphore() -> asyncio.Semaphore:
    global _tabular_cell_semaphore
    if _tabular_cell_semaphore is None:
        _tabular_cell_semaphore = asyncio.Semaphore(tabular_max_parallel_cells())
    return _tabular_cell_semaphore


async def try_acquire_column_run(review_id: str, column_id: str) -> bool:
    """Return False if this column is already extracting."""
    key = (review_id, column_id)
    async with _column_run_lock:
        if key in _running_column_runs:
            return False
        _running_column_runs.add(key)
        return True


async def release_column_run(review_id: str, column_id: str) -> None:
    async with _column_run_lock:
        _running_column_runs.discard((review_id, column_id))


def reset_tabular_extraction_runtime_for_tests() -> None:
    """Clear in-memory run registry and semaphore (unit tests only)."""
    global _tabular_cell_semaphore
    _tabular_cell_semaphore = None
    _running_column_runs.clear()


async def run_column_extraction_background(
    review_id: str,
    column_id: str,
    user_id: str,
) -> None:
    """Background task: own DB session, always releases in-flight lock."""
    import logging

    from app.services.tabular_review_service import TabularReviewService
    from app.utils.database import SessionLocal

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        service = TabularReviewService(db)
        await service.execute_column_extraction(review_id, column_id, user_id)
    except Exception as exc:
        logger.error(
            "Background column extraction failed review=%s column=%s: %s",
            review_id,
            column_id,
            exc,
            exc_info=True,
        )
        try:
            service = TabularReviewService(db)
            await service._broadcast_column_extraction_completed(
                review_id,
                column_id=column_id,
                status="failed",
                saved_count=0,
                filled_count=0,
                error_count=0,
                total_tasks=0,
                message=str(exc),
            )
        except Exception:
            logger.warning("Failed to broadcast column extraction failure", exc_info=True)
    finally:
        await release_column_run(review_id, column_id)
        db.close()
