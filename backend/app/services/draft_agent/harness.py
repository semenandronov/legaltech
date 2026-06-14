"""Deep Agent harness for draft mode (legacy tools; stream uses hybrid workflow)."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from langgraph.checkpoint.memory import MemorySaver

from app.config import config
from app.services.draft_agent.context import DraftAgentContext
from app.services.agent_runs.middleware.first_turn_todos import FirstTurnWriteTodosMiddleware
from app.services.draft_agent.prompts import build_draft_system_prompt
from app.services.draft_agent.session import DraftAgentSession
from app.services.draft_agent.template_session import resolve_template_session
from app.services.draft_agent.tools.build import build_draft_agent_tools
from app.services.llm_factory import create_llm
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PROFILE_REGISTERED = False

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
    current = llm
    for _ in range(6):
        inner = getattr(current, "_llm", None)
        if inner is None:
            break
        current = inner
    return current


def _register_legal_workflow_harness_profile() -> None:
    global _PROFILE_REGISTERED
    if _PROFILE_REGISTERED:
        return
    try:
        from deepagents.profiles._harness_profiles import _HarnessProfile, _register_harness_profile
        from app.services.agent_runs.prompts import LEGAL_WORKFLOW_BASE_PROMPT

        profile = _HarnessProfile(base_system_prompt=LEGAL_WORKFLOW_BASE_PROMPT)
        _register_harness_profile("openai", profile)
        model_uri = (getattr(config, "YANDEX_GPT_MODEL_URI", None) or "").strip()
        if model_uri:
            _register_harness_profile(model_uri, profile)
        _PROFILE_REGISTERED = True
        logger.info("Registered legal workflow harness profile for draft agent")
    except Exception as exc:
        logger.warning("Draft agent harness profile registration skipped: %s", exc)


class DraftAgentHarness:
    """Builds deep agent for chat draft mode (RAG + legal + calculator + writer)."""

    def __init__(self, ctx: DraftAgentContext, *, db: Session, user_question: str):
        self.db = db
        resolved = resolve_template_session(db, ctx=ctx, user_question=user_question)
        self.session = DraftAgentSession(
            ctx=ctx,
            template=resolved,
            user_question=user_question,
        )

    def build_tools(self) -> List[Any]:
        return build_draft_agent_tools(self.session, db=self.db)

    def _build_middleware(self) -> Optional[List[Any]]:
        layers: List[Any] = []
        try:
            from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

            layers.append(_ToolExclusionMiddleware(excluded=EXCLUDED_FILESYSTEM_TOOLS))
        except Exception as exc:
            logger.warning("[DraftAgent] tool exclusion unavailable: %s", exc)

        layers.append(FirstTurnWriteTodosMiddleware())

        tool_limit = int(getattr(config, "DRAFT_AGENT_TOOL_CALL_LIMIT", 24) or 24)
        model_limit = int(getattr(config, "DRAFT_AGENT_MODEL_CALL_LIMIT", 20) or 20)

        if tool_limit > 0:
            try:
                from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

                layers.append(ToolCallLimitMiddleware(run_limit=tool_limit, exit_behavior="continue"))
            except Exception as exc:
                logger.warning("[DraftAgent] ToolCallLimitMiddleware unavailable: %s", exc)

        if model_limit > 0:
            try:
                from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware

                layers.append(ModelCallLimitMiddleware(run_limit=model_limit, exit_behavior="end"))
            except Exception as exc:
                logger.warning("[DraftAgent] ModelCallLimitMiddleware unavailable: %s", exc)

        return layers or None

    def create_agent(self, *, checkpointer: Optional[Any] = None):
        try:
            from deepagents import create_deep_agent
        except ImportError as exc:
            raise RuntimeError("deepagents package is not installed") from exc

        _register_legal_workflow_harness_profile()
        llm = _unwrap_llm_for_deepagents(
            create_llm(temperature=0.2, use_rate_limiting=False)
        )
        cp = checkpointer or MemorySaver()

        kwargs: dict = {
            "model": llm,
            "tools": self.build_tools(),
            "system_prompt": build_draft_system_prompt(self.session.template),
            "checkpointer": cp,
        }
        middleware = self._build_middleware()
        if middleware:
            kwargs["middleware"] = middleware

        return create_deep_agent(**kwargs)
