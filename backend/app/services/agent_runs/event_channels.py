"""Postgres NOTIFY channel naming for agent runs."""
from __future__ import annotations

import re

_CONTROL_CHANNEL = "agent_control"
_RUN_PREFIX = "ar_"
_RUN_ID_RE = re.compile(r"[^a-z0-9_]", re.IGNORECASE)


def run_notify_channel(run_id: str) -> str:
    """Channel for per-run event hints (max 63 chars for PG identifiers)."""
    token = _RUN_ID_RE.sub("", (run_id or "").lower().replace("-", ""))
    channel = f"{_RUN_PREFIX}{token}"
    return channel[:63]


def control_notify_channel() -> str:
    return _CONTROL_CHANNEL
