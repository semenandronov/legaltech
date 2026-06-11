"""Run blocking SQLAlchemy work off the asyncio event loop."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from starlette.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_sync_db(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Execute a sync DB callable in Starlette's thread pool (own Session inside)."""
    return await run_in_threadpool(func, *args, **kwargs)
