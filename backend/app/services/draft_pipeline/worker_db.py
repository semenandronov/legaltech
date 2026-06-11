"""Thread-safe DB session helper for draft pipeline parallel nodes."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy.orm import Session


@contextmanager
def worker_db_session(parent_db: Optional[Session]) -> Iterator[Optional[Session]]:
    """One SQLAlchemy session per worker thread — never share request-scoped ``db``."""
    if parent_db is None:
        yield None
        return
    from app.utils.database import SessionLocal

    child = SessionLocal()
    try:
        yield child
    finally:
        child.close()
