"""Async SQLAlchemy engine (asyncpg) for non-blocking HTTP hot paths."""
from __future__ import annotations

import logging
import ssl
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config
from app.utils.postgres_dsn import canonicalize_postgres_dsn

logger = logging.getLogger(__name__)

_async_engine = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

# libpq/psycopg query params that asyncpg.connect() does not accept
_ASYNCPG_DROP_QUERY_PARAMS = frozenset(
    {
        "sslmode",
        "channel_binding",
        "gssencmode",
        "krbsrvname",
        "service",
        "options",
    }
)


def _to_async_sqlalchemy_url(raw_url: str) -> str:
    dsn = canonicalize_postgres_dsn(raw_url).dsn
    if dsn.startswith("postgresql+asyncpg://"):
        url = dsn
    elif dsn.startswith("postgresql://"):
        url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif dsn.startswith("postgres://"):
        url = dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    else:
        return dsn

    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _ASYNCPG_DROP_QUERY_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def _async_connect_args(async_url: str) -> dict:
    parts = urlsplit(async_url)
    host = (parts.hostname or "").strip().lower()
    if host in ("localhost", "127.0.0.1", "::1", ""):
        return {}
    return {"ssl": ssl.create_default_context()}


def get_async_engine():
    global _async_engine
    if _async_engine is None:
        async_url = _to_async_sqlalchemy_url(config.DATABASE_URL)
        connect_args = _async_connect_args(async_url)
        _async_engine = create_async_engine(
            async_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=180,
            pool_size=max(1, config.SQLALCHEMY_POOL_SIZE),
            max_overflow=max(0, config.SQLALCHEMY_MAX_OVERFLOW),
            pool_timeout=max(1, config.SQLALCHEMY_POOL_TIMEOUT),
            connect_args=connect_args,
        )
        logger.info("Async SQLAlchemy engine initialized (asyncpg)")
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_async_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
