from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class ExecutionEvent:
    """Event emitted during workflow execution (SSE contract)."""

    event_type: str
    execution_id: str
    step_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    progress_percent: int = 0
    message: str = ""

