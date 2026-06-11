"""LangChain callback: reserved for future live streaming hooks (no per-token DB writes)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class AgentRunPublishCallback(AsyncCallbackHandler):
    """
    Tracks the root model run id for optional future streaming hooks.

    Final assistant text is persisted once by the worker after the graph completes.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._root_run_id: Optional[UUID] = None

    def _is_root_stream(self, run_id: Optional[UUID], parent_run_id: Optional[UUID]) -> bool:
        if parent_run_id is not None:
            return False
        if run_id is None:
            return False
        if self._root_run_id is None:
            self._root_run_id = run_id
        return run_id == self._root_run_id

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        if parent_run_id is None and self._root_run_id is None:
            self._root_run_id = run_id

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        return

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        return
