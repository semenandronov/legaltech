"""Draft agent session: immutable context + resolved template."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_agent.template_session import ResolvedDraftTemplate


@dataclass(frozen=True)
class DraftAgentSession:
    ctx: DraftAgentContext
    template: ResolvedDraftTemplate
    user_question: str
