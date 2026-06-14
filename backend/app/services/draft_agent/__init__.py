"""Draft mode: Deep Agent with RAG, legal corpus, calculator, and document writer."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["DraftAgentStreamService"]

if TYPE_CHECKING:
    from app.services.draft_agent.stream_service import DraftAgentStreamService


def __getattr__(name: str):
    if name == "DraftAgentStreamService":
        from app.services.draft_agent.stream_service import DraftAgentStreamService

        return DraftAgentStreamService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
