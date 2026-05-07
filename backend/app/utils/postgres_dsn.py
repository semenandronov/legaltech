from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class PostgresDsn:
    """Canonicalized Postgres DSN for all connectors (SQLAlchemy, psycopg, LangGraph).

    Goal: make remote DB connections stable by ensuring a consistent scheme and sslmode.
    """

    dsn: str


def canonicalize_postgres_dsn(raw_url: str) -> PostgresDsn:
    """Normalize various SQLAlchemy/driver URLs into a stable Postgres DSN.

    - Convert sqlalchemy driver schemes (postgresql+psycopg, postgresql+psycopg2) to plain postgresql://
    - Ensure sslmode is set for non-local targets (default: require)
    """
    if not raw_url:
        return PostgresDsn(dsn=raw_url)

    url = raw_url
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)

    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres"):
        return PostgresDsn(dsn=url)

    host = (parts.hostname or "").strip().lower()
    is_local = host in ("localhost", "127.0.0.1", "::1", "")

    # Preserve existing query params; add sslmode=require for remote DBs if missing.
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if not is_local and "sslmode" not in {k.lower(): v for k, v in query.items()}:
        query["sslmode"] = "require"

    new_parts = parts._replace(query=urlencode(query, doseq=True))
    return PostgresDsn(dsn=urlunsplit(new_parts))

