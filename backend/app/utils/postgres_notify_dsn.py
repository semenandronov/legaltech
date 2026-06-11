"""DSN helpers for Postgres LISTEN/NOTIFY (requires session, not transaction pooler)."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app.utils.postgres_dsn import canonicalize_postgres_dsn


def listen_notify_dsn(raw_url: str) -> str:
    """
    Return a DSN suitable for long-lived LISTEN connections.

    Neon/PgBouncer poolers do not deliver NOTIFY to pooled clients; use direct host when detected.
    """
    dsn = canonicalize_postgres_dsn(raw_url).dsn
    parts = urlsplit(dsn)
    host = (parts.hostname or "").strip()
    if not host or "pooler" not in host.lower():
        return dsn

    direct_host = host.replace("-pooler", "")
    netloc = parts.netloc.replace(host, direct_host, 1)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
