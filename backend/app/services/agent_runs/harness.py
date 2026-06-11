"""Production harness for deepagents.create_deep_agent."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from app.config import config
from app.services.agent_runs.tools import (
    build_case_rag_tool,
    build_draft_tool,
    build_legal_corpus_tool,
    build_ping_tool,
    build_tabular_review_tool,
)
from app.services.agent_runs.middleware.first_turn_todos import FirstTurnWriteTodosMiddleware
from app.services.agent_runs.prompts import DEFAULT_SYSTEM_PROMPT, LEGAL_WORKFLOW_BASE_PROMPT
from app.services.llm_factory import create_llm

logger = logging.getLogger(__name__)

_PROFILE_REGISTERED = False


def _register_legal_workflow_harness_profile() -> None:
    """Replace Deep Agents default base prompt for OpenAI-compatible models (Yandex)."""
    global _PROFILE_REGISTERED
    if _PROFILE_REGISTERED:
        return
    try:
        from deepagents.profiles._harness_profiles import _HarnessProfile, _register_harness_profile

        profile = _HarnessProfile(base_system_prompt=LEGAL_WORKFLOW_BASE_PROMPT)
        _register_harness_profile("openai", profile)
        model_uri = (getattr(config, "YANDEX_GPT_MODEL_URI", None) or "").strip()
        if model_uri:
            _register_harness_profile(model_uri, profile)
        _PROFILE_REGISTERED = True
        logger.info("Registered legal workflow harness profile (base_system_prompt override)")
    except Exception as exc:
        logger.warning("Legal workflow harness profile registration skipped: %s", exc)

# Deep Agents inject filesystem tools by default; legal workflows use RAG instead.
EXCLUDED_FILESYSTEM_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "execute",
    }
)


def _unwrap_llm_for_deepagents(llm: Any) -> Any:
    """deepagents.resolve_model requires a native chat model or provider string."""
    current = llm
    for _ in range(6):
        inner = getattr(current, "_llm", None)
        if inner is None:
            break
        current = inner
    return current


@dataclass(frozen=True)
class AgentRunHarnessContext:
    user_id: str
    case_id: str
    run_id: str
    file_ids: List[str]


class AgentRunHarness:
    """Builds a configured deep agent with production guardrails."""

    def __init__(
        self,
        ctx: AgentRunHarnessContext,
        *,
        on_tool_completed: Optional[Callable[[], None]] = None,
        extra_tools: Optional[List[Any]] = None,
    ):
        self.ctx = ctx
        self._on_tool_completed = on_tool_completed
        self._extra_tools = extra_tools or []

    def build_tools(self) -> List[Any]:
        tools: List[Any] = [
            build_case_rag_tool(
                user_id=self.ctx.user_id,
                case_id=self.ctx.case_id,
                run_id=self.ctx.run_id,
                default_file_ids=self.ctx.file_ids,
                on_tool_completed=self._on_tool_completed,
            ),
            build_legal_corpus_tool(
                run_id=self.ctx.run_id,
                on_tool_completed=self._on_tool_completed,
            ),
            build_tabular_review_tool(
                user_id=self.ctx.user_id,
                case_id=self.ctx.case_id,
                run_id=self.ctx.run_id,
                default_file_ids=self.ctx.file_ids,
                on_tool_completed=self._on_tool_completed,
            ),
            build_draft_tool(
                user_id=self.ctx.user_id,
                case_id=self.ctx.case_id,
                run_id=self.ctx.run_id,
                default_file_ids=self.ctx.file_ids,
                on_tool_completed=self._on_tool_completed,
            ),
            build_ping_tool(run_id=self.ctx.run_id, on_tool_completed=self._on_tool_completed),
        ]
        tools.extend(self._extra_tools)
        return tools

    def _build_middleware(self) -> Optional[List[Any]]:
        layers: List[Any] = []
        try:
            from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

            layers.append(_ToolExclusionMiddleware(excluded=EXCLUDED_FILESYSTEM_TOOLS))
        except Exception as exc:
            logger.warning("Filesystem tool exclusion unavailable: %s", exc)

        layers.append(FirstTurnWriteTodosMiddleware())

        tool_limit = int(getattr(config, "AGENT_RUNS_TOOL_CALL_RUN_LIMIT", 0) or 0)
        model_limit = int(getattr(config, "AGENT_RUNS_MODEL_CALL_RUN_LIMIT", 0) or 0)

        if tool_limit > 0:
            try:
                from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

                layers.append(ToolCallLimitMiddleware(run_limit=tool_limit, exit_behavior="continue"))
            except Exception as exc:
                logger.warning("ToolCallLimitMiddleware unavailable: %s", exc)

        if model_limit > 0:
            try:
                from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware

                layers.append(ModelCallLimitMiddleware(run_limit=model_limit, exit_behavior="end"))
            except Exception as exc:
                logger.warning("ModelCallLimitMiddleware unavailable: %s", exc)

        return layers or None

    def create_agent(self, *, checkpointer: Any, model: Optional[Any] = None):
        try:
            from deepagents import create_deep_agent
        except ImportError as exc:
            raise RuntimeError("deepagents package is not installed") from exc

        _register_legal_workflow_harness_profile()
        llm = _unwrap_llm_for_deepagents(model or create_llm(temperature=0.2, use_rate_limiting=False))
        kwargs: dict = {
            "model": llm,
            "tools": self.build_tools(),
            "system_prompt": getattr(config, "AGENT_RUNS_SYSTEM_PROMPT", None) or DEFAULT_SYSTEM_PROMPT,
            "checkpointer": checkpointer,
        }

        middleware = self._build_middleware()
        if middleware:
            kwargs["middleware"] = middleware

        interrupt_tools = (getattr(config, "AGENT_RUNS_INTERRUPT_ON_TOOLS", "") or "").strip()
        if interrupt_tools:
            names = [n.strip() for n in interrupt_tools.split(",") if n.strip()]
            if names:
                kwargs["interrupt_on"] = {name: True for name in names}

        return create_deep_agent(**kwargs)
