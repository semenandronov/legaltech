"""Draft document generation mode (unified vs legacy decomposed)."""
from __future__ import annotations

from app.config import config

_VALID = frozenset({"unified", "decomposed"})


def get_draft_generation_mode() -> str:
    """
    ``unified`` — один LLM-проход с полным RAG (как case assistant), default.
    ``decomposed`` — legacy blueprint + parallel sections + compiler.
    """
    raw = (getattr(config, "DRAFT_GENERATION_MODE", "unified") or "unified").strip().lower()
    return raw if raw in _VALID else "unified"


def is_unified_generation() -> bool:
    return get_draft_generation_mode() == "unified"
