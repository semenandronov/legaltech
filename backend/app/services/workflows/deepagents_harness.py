"""DeepAgents harness for workflow execution (whitelisted tools only)."""
from __future__ import annotations

from dataclasses import dataclass
import os
import logging
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from deepagents.middleware.permissions import FilesystemPermission

from app.config import config
from app.services.workflows.tool_registry import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


WHITELIST_TOOLS = [
    "rag",
    "summarize",
    "extract_entities",
    "tabular_review",
    "playbook_check",
    "legal_db",
    "document_draft",
]


@dataclass
class WorkflowDeepAgentsContext:
    user_id: str
    case_id: Optional[str]
    execution_id: str
    previous_results: Dict[str, Any]
    legal_research: bool = False


def _tool_result_to_payload(result: ToolResult) -> Dict[str, Any]:
    return {
        "success": bool(result.success),
        "data": result.data,
        "error": result.error,
        "output_summary": result.output_summary,
        "artifacts": result.artifacts or [],
        "llm_calls": int(result.llm_calls or 0),
        "tokens_used": int(result.tokens_used or 0),
    }


class WorkflowDeepAgentsHarness:
    """Factory for deepagents create_deep_agent with strict tool whitelist."""

    def __init__(self, tool_registry: ToolRegistry, ctx: WorkflowDeepAgentsContext):
        self.tool_registry = tool_registry
        self.ctx = ctx

    def build_tools(self) -> List[Any]:
        """Return LangChain tools for create_deep_agent(tools=[...])."""

        async def _run_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
            if tool_name not in WHITELIST_TOOLS:
                raise ValueError(f"Tool '{tool_name}' is not allowed in workflow")

            writer = None
            try:
                writer = get_stream_writer()
            except Exception:
                writer = None

            if writer is not None:
                writer(
                    {
                        "type": "tool_started",
                        "tool": tool_name,
                        "params_preview": {k: params.get(k) for k in list(params.keys())[:8]},
                    }
                )

            context = {
                "user_id": self.ctx.user_id,
                "case_id": self.ctx.case_id,
                "execution_id": self.ctx.execution_id,
                "previous_results": self.ctx.previous_results,
                "legal_research": bool(self.ctx.legal_research),
            }
            result = await self.tool_registry.execute_tool(
                tool_name=tool_name,
                params=params or {},
                context=context,
            )

            payload = _tool_result_to_payload(result)
            if writer is not None:
                writer(
                    {
                        "type": "tool_completed",
                        "tool": tool_name,
                        "success": payload["success"],
                        "output_summary": payload.get("output_summary", "")[:500],
                        "result": payload,
                    }
                )
            return payload

        @tool("rag")
        async def rag(query: str, file_ids: Optional[List[str]] = None, top_k: int = 10) -> Dict[str, Any]:
            """Поиск по загруженным документам с помощью RAG."""
            return await _run_tool("rag", {"query": query, "file_ids": file_ids or [], "top_k": top_k})

        @tool("summarize")
        async def summarize(
            text: Optional[str] = None,
            file_id: Optional[str] = None,
            file_ids: Optional[List[str]] = None,
            data: Optional[Any] = None,
            style: str = "brief",
            focus: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Суммаризация текста или документов под задачу юриста."""
            params: Dict[str, Any] = {"style": style}
            if text is not None:
                params["text"] = text
            if file_id is not None:
                params["file_id"] = file_id
            if file_ids is not None:
                params["file_ids"] = file_ids
            if data is not None:
                params["data"] = data
            if focus is not None:
                params["focus"] = focus
            return await _run_tool("summarize", params)

        @tool("extract_entities")
        async def extract_entities(
            text: Optional[str] = None,
            file_id: Optional[str] = None,
            file_ids: Optional[List[str]] = None,
            entity_types: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Выделение сущностей (стороны, суммы, даты и т.п.) из текста/документов."""
            params: Dict[str, Any] = {}
            if text is not None:
                params["text"] = text
            if file_id is not None:
                params["file_id"] = file_id
            if file_ids is not None:
                params["file_ids"] = file_ids
            if entity_types is not None:
                params["entity_types"] = entity_types
            return await _run_tool("extract_entities", params)

        @tool("tabular_review")
        async def tabular_review(
            questions: List[str],
            file_ids: Optional[List[str]] = None,
            review_name: Optional[str] = None,
            wait_for_completion: bool = True,
        ) -> Dict[str, Any]:
            """Табличная проверка документов по списку вопросов/критериев."""
            params: Dict[str, Any] = {
                "questions": questions,
                "file_ids": file_ids or [],
                "wait_for_completion": bool(wait_for_completion),
            }
            if review_name:
                params["review_name"] = review_name
            return await _run_tool("tabular_review", params)

        @tool("playbook_check")
        async def playbook_check(document_id: str, playbook_id: str) -> Dict[str, Any]:
            """Проверка документа по выбранному плейбуку (чек‑листу)."""
            return await _run_tool("playbook_check", {"document_id": document_id, "playbook_id": playbook_id})

        @tool("legal_db")
        async def legal_db(query: str, max_results: int = 10) -> Dict[str, Any]:
            """Поиск по загруженному юридическому справочнику (внутренняя база)."""
            return await _run_tool("legal_db", {"query": query, "max_results": max_results})

        @tool("document_draft")
        async def document_draft(
            document_type: str,
            variables: Optional[Dict[str, Any]] = None,
            instructions: Optional[str] = None,
            title: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Подготовка проекта юридического документа по типу, переменным и инструкции."""
            params: Dict[str, Any] = {"document_type": document_type}
            if variables is not None:
                params["variables"] = variables
            if instructions is not None:
                params["instructions"] = instructions
            if title is not None:
                params["title"] = title
            return await _run_tool("document_draft", params)

        return [
            rag,
            summarize,
            extract_entities,
            tabular_review,
            playbook_check,
            legal_db,
            document_draft,
        ]

    def _tools_by_name(self) -> Dict[str, Any]:
        return {tool_obj.name: tool_obj for tool_obj in self.build_tools()}

    def _configured_skills(self) -> Optional[List[str]]:
        raw = (config.WORKFLOW_DEEPAGENTS_SKILLS_PATHS or "").strip()
        if not raw:
            return None
        items = [p.strip() for p in raw.split(",") if p.strip()]
        return items or None

    def _configured_memory(self) -> Optional[List[str]]:
        raw = (config.WORKFLOW_DEEPAGENTS_MEMORY_PATHS or "").strip()
        if not raw:
            return None
        items = [p.strip() for p in raw.split(",") if p.strip()]
        return items or None

    def _build_langchain_middleware(self) -> Optional[List[Any]]:
        """Return extra LangChain middleware for ``create_deep_agent(middleware=...)``.

        ``WORKFLOW_DEEPAGENTS_MIDDLEWARE`` is a comma-separated list of presets:
        ``todo``, ``tool_retry``, ``tool_call_limit``, ``model_call_limit``.

        Do **not** append ``TodoListMiddleware`` here: ``deepagents.create_deep_agent`` already
        prepends ``TodoListMiddleware()`` to the stack; a second instance raises
        ``AssertionError: Please remove duplicate middleware instances.`` (duplicate ``m.name``).
        For hints about ``write_todos``, extend the workflow system prompt.
        """
        layers: List[Any] = []

        presets = [p.strip().lower() for p in (config.WORKFLOW_DEEPAGENTS_MIDDLEWARE or "").split(",") if p.strip()]
        for p in presets:
            if p in ("", "none"):
                continue
            if p == "todo":
                logger.warning(
                    "WORKFLOW_DEEPAGENTS_MIDDLEWARE preset 'todo' is ignored: "
                    "TodoListMiddleware is already registered by deepagents (duplicate names are rejected)."
                )
                continue
            elif p == "tool_retry":
                try:
                    from langchain.agents.middleware.tool_retry import ToolRetryMiddleware

                    layers.append(ToolRetryMiddleware(max_retries=2))
                except Exception as exc:
                    logger.warning("ToolRetryMiddleware unavailable: %s", exc)
            elif p == "tool_call_limit":
                lim = int(getattr(config, "WORKFLOW_DEEPAGENTS_TOOL_CALL_RUN_LIMIT", 0) or 0)
                if lim > 0:
                    try:
                        from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

                        layers.append(ToolCallLimitMiddleware(run_limit=lim, exit_behavior="continue"))
                    except Exception as exc:
                        logger.warning("ToolCallLimitMiddleware unavailable: %s", exc)
            elif p == "model_call_limit":
                lim = int(getattr(config, "WORKFLOW_DEEPAGENTS_MODEL_CALL_RUN_LIMIT", 0) or 0)
                if lim > 0:
                    try:
                        from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware

                        layers.append(ModelCallLimitMiddleware(run_limit=lim, exit_behavior="end"))
                    except Exception as exc:
                        logger.warning("ModelCallLimitMiddleware unavailable: %s", exc)
            else:
                logger.warning("Unknown WORKFLOW_DEEPAGENTS_MIDDLEWARE preset: %r (ignored)", p)

        # Optional limits without explicit preset (production safety).
        tl = int(getattr(config, "WORKFLOW_DEEPAGENTS_TOOL_CALL_RUN_LIMIT", 0) or 0)
        if tl > 0 and not any(type(m).__name__ == "ToolCallLimitMiddleware" for m in layers):
            try:
                from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

                layers.append(ToolCallLimitMiddleware(run_limit=tl, exit_behavior="continue"))
            except Exception as exc:
                logger.warning("Auto ToolCallLimitMiddleware unavailable: %s", exc)
        ml = int(getattr(config, "WORKFLOW_DEEPAGENTS_MODEL_CALL_RUN_LIMIT", 0) or 0)
        if ml > 0 and not any(type(m).__name__ == "ModelCallLimitMiddleware" for m in layers):
            try:
                from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware

                layers.append(ModelCallLimitMiddleware(run_limit=ml, exit_behavior="end"))
            except Exception as exc:
                logger.warning("Auto ModelCallLimitMiddleware unavailable: %s", exc)

        return layers or None

    def _configured_interrupt_on(self) -> Optional[Dict[str, bool]]:
        raw = (config.WORKFLOW_DEEPAGENTS_INTERRUPT_ON_TOOLS or "").strip()
        if not raw:
            return None
        allowed = set(WHITELIST_TOOLS)
        names = [p.strip() for p in raw.split(",") if p.strip()]
        enabled = {name: True for name in names if name in allowed}
        return enabled or None

    @staticmethod
    def _namespace_component(value: str) -> str:
        """DeepAgents StoreBackend allows only a safe ASCII subset; hash the rest."""
        if re.match(r"^[A-Za-z0-9\-_.@+:~]+$", value):
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    def _build_runtime_backend(self) -> Tuple[Optional[Any], Optional[Any]]:
        """Return (backend, langgraph_store) for create_deep_agent.

        Composite routing matches deepagents 0.5+: default ``StateBackend`` (ephemeral)
        and ``/memories/`` either on-disk (``WORKFLOW_DEEPAGENTS_MEMORIES_DIR``) or
        ``StoreBackend`` + ``InMemoryStore`` for dev.
        """
        if not config.WORKFLOW_DEEPAGENTS_COMPOSITE_BACKEND_ENABLED:
            return None, None
        try:
            from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
            from deepagents.backends.filesystem import FilesystemBackend
            from langgraph.store.memory import InMemoryStore
        except Exception as exc:
            logger.warning("DeepAgents CompositeBackend unavailable: %s", exc)
            return None, None

        memories_dir = (config.WORKFLOW_DEEPAGENTS_MEMORIES_DIR or "").strip()
        default_backend = StateBackend()

        if memories_dir:
            # Disk-backed route (virtual paths under the route prefix).
            memories_backend: Any = FilesystemBackend(root_dir=memories_dir, virtual_mode=True)
            return (
                CompositeBackend(default=default_backend, routes={"/memories/": memories_backend}),
                None,
            )

        # LangGraph store (pass the same instance to create_deep_agent(store=...)).
        store = InMemoryStore()
        uid = self._namespace_component(self.ctx.user_id)
        eid = self._namespace_component(self.ctx.execution_id)

        def _namespace(_rt: Any) -> tuple[str, ...]:
            return (uid, "workflow", eid)

        store_route = StoreBackend(store=store, namespace=_namespace)
        return CompositeBackend(default=default_backend, routes={"/memories/": store_route}), store

    def _build_permissions(self) -> Optional[List[FilesystemPermission]]:
        if not config.WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED:
            return None

        def _to_glob_pattern(path: str) -> str:
            p = path.strip().rstrip("/")
            if not p.startswith("/"):
                p = "/" + p
            if p.endswith("/**"):
                return p
            return f"{p}/**"

        read_paths = [p for p in (config.WORKFLOW_DEEPAGENTS_ALLOWED_READ_PATHS or "").split(",") if p.strip()]
        write_paths = [p for p in (config.WORKFLOW_DEEPAGENTS_ALLOWED_WRITE_PATHS or "").split(",") if p.strip()]
        rules: List[FilesystemPermission] = []
        if read_paths:
            rules.append(
                FilesystemPermission(
                    operations=["read"],
                    paths=[_to_glob_pattern(p) for p in read_paths],
                )
            )
        if write_paths:
            rules.append(
                FilesystemPermission(
                    operations=["write"],
                    paths=[_to_glob_pattern(p) for p in write_paths],
                )
            )
        rules.append(FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"))
        return rules

    def build_subagents(self) -> List[Dict[str, Any]]:
        """
        Return role-based subagents to keep Deep Agent context focused.
        Each role has minimal tool scope and compact output requirements.
        """
        tools_map = self._tools_by_name()
        return [
            {
                "name": "research",
                "description": "Проводит правовое исследование и извлекает релевантные нормы/факты.",
                "system_prompt": (
                    "Ты подагент правового исследования. Используй только предоставленные инструменты. "
                    "Верни короткий структурированный результат: ключевые факты, источники, риски."
                ),
                "tools": [tools_map[name] for name in ("legal_db", "rag", "extract_entities") if name in tools_map],
            },
            {
                "name": "analysis",
                "description": "Проводит анализ и сводку найденных материалов.",
                "system_prompt": (
                    "Ты подагент анализа. Синтезируй найденные данные, избегай сырого вывода инструментов. "
                    "Верни краткий отчёт с выводами и неопределенностями."
                ),
                "tools": [tools_map[name] for name in ("summarize", "rag") if name in tools_map],
            },
            {
                "name": "draft",
                "description": "Готовит черновик итогового юридического документа.",
                "system_prompt": (
                    "Ты подагент подготовки документа. Создай практичный юридический черновик "
                    "на основе входных результатов и укажи, какие данные критичны для валидации."
                ),
                "tools": [tools_map[name] for name in ("document_draft",) if name in tools_map],
            },
            {
                "name": "review",
                "description": "Проверяет качество и полноту результата перед финализацией.",
                "system_prompt": (
                    "Ты подагент контроля качества. Проверяй полноту, согласованность и опору на источники. "
                    "Верни список замечаний и критерий готовности к финализации."
                ),
                "tools": [tools_map[name] for name in ("playbook_check", "summarize") if name in tools_map],
            },
        ]

    def create_agent(
        self,
        *,
        system_prompt: str,
        model: Optional[Any] = None,
        checkpointer: Optional[Any] = None,
    ):
        """Create a deep agent (LangGraph compiled graph).

        Pass an async-capable checkpointer (e.g. AsyncPostgresSaver or MemorySaver) when using
        ``graph.astream``; sync ``PostgresSaver`` does not implement ``aget_tuple``.
        """
        try:
            from deepagents import create_deep_agent
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("deepagents is not installed") from exc

        # DeepAgents/LangChain may initialize LangSmith client from env vars.
        # In workflow runtime we keep tracing disabled by default to avoid
        # auth collisions (api_key vs auth_token headers).
        if not config.WORKFLOW_DEEPAGENTS_LANGSMITH_TRACING:
            os.environ["LANGCHAIN_TRACING_V2"] = "false"
            os.environ["LANGSMITH_TRACING"] = "false"
            for key in (
                "LANGCHAIN_API_KEY",
                "LANGSMITH_API_KEY",
                "LANGCHAIN_AUTH_TOKEN",
                "LANGSMITH_AUTH_TOKEN",
            ):
                os.environ.pop(key, None)

        tools = self.build_tools()
        kwargs: Dict[str, Any] = {
            "model": model,
            "tools": tools,
            "system_prompt": system_prompt,
        }
        interrupt_on = self._configured_interrupt_on()
        if interrupt_on:
            kwargs["interrupt_on"] = interrupt_on
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
        backend, langgraph_store = self._build_runtime_backend()
        if backend is not None:
            kwargs["backend"] = backend
        if langgraph_store is not None:
            kwargs["store"] = langgraph_store
        permissions = self._build_permissions()
        if permissions:
            kwargs["permissions"] = permissions
        if config.WORKFLOW_DEEPAGENTS_SUBAGENTS_ENABLED:
            kwargs["subagents"] = self.build_subagents()
        skills = self._configured_skills()
        if skills:
            kwargs["skills"] = skills
        memory = self._configured_memory()
        if memory:
            kwargs["memory"] = memory
        middleware = self._build_langchain_middleware()
        if middleware:
            kwargs["middleware"] = middleware
        try:
            return create_deep_agent(**kwargs)
        except TypeError as exc:
            # Graceful compatibility path for older deepagents versions.
            for optional_key in (
                "interrupt_on",
                "checkpointer",
                "backend",
                "store",
                "permissions",
                "middleware",
            ):
                kwargs.pop(optional_key, None)
            logger.warning("DeepAgents optional runtime features disabled due to API mismatch: %s", exc)
            return create_deep_agent(**kwargs)

