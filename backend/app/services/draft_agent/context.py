"""Runtime context for a single draft agent session."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class DraftAgentContext:
    user_id: str
    case_id: str
    session_id: str
    file_ids: List[str] = field(default_factory=list)
    template_file_id: Optional[str] = None
    template_file_content: Optional[str] = None

    @property
    def thread_id(self) -> str:
        return f"draft-agent-{self.case_id}-{self.session_id}"
