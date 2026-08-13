"""
ChatGraphService - сервис для интеграции ChatGraph в API endpoints.

# РОЛЬ
Сервис-адаптер между API endpoints и ChatGraph.
Обеспечивает унифицированный интерфейс для работы с чатом.

# ФУНКЦИИ
- Streaming ответов через ChatGraph с форматированием для assistant-ui
- Маршрутизация по режимам (normal, deep_think, garant, draft)
- Сохранение истории сообщений в БД
- Кэширование экземпляра графа

# КОГДА ИСПОЛЬЗОВАТЬ
- Обработка запросов на /api/assistant-chat
- Streaming ответов в реальном времени
- Интеграция с assistant-ui frontend

# ПАТТЕРН ИСПОЛЬЗОВАНИЯ
```python
service = get_chat_graph_service(db, rag_service)
async for event in service.stream_response(
    case_id="...",
    question="...",
    user=current_user,
    deep_think=True
):
    yield event
```
"""
from typing import AsyncGenerator, Optional, List, Dict, Any, Literal
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import Command
from fastapi import HTTPException
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.utils.authorization import require_case_access
from app.services.langchain_agents.graphs.chat_graph import (
    create_chat_graph,
    create_initial_chat_state,
    ChatGraphState,
)
from app.config import config as app_config


def _case_graph_recursion_limit() -> int:
    return int(getattr(app_config, "CASE_ASSISTANT_GRAPH_RECURSION_LIMIT", 40) or 40)
from app.services.langchain_agents.utils.streaming import (
    StreamMode,
    StreamEvent,
    stream_graph_with_mode,
    stream_tokens,
    format_sse_event,
    create_text_delta_event,
    create_finish_event,
)
from app.models.user import User
from app.models.case import Case, ChatMessage
from app.services.chat.history_service import ChatHistoryService
from app.config import config
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    get_langchain_callbacks,
    langfuse_enabled,
    reset_trace_span_parent,
    set_trace_span_parent,
    trace_contract_event,
    trace_span,
    normalize_observability_metadata,
)
from app.services.observability.assistant_pipeline_langfuse_tracing import (
    assistant_step_span,
    record_assistant_step,
    record_graph_node_completed,
)
from app.services.chat.llm_streaming import incremental_stream_piece
import logging
import json
import uuid
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _format_text_delta_sse(turn_emitter: Optional[Any], text: str) -> str:
    if not text:
        return ""
    if turn_emitter is not None:
        return turn_emitter.text_delta(text)
    return f"data: {json.dumps({'type': 'text-delta', 'textDelta': text}, ensure_ascii=False)}\n\n"


def _format_content_sync_sse(turn_emitter: Optional[Any], content: str) -> str:
    if turn_emitter is not None:
        return turn_emitter.content_sync(content)
    return f"data: {json.dumps({'type': 'content_sync', 'content': content}, ensure_ascii=False)}\n\n"


def _finalize_generate_response_text(
    *,
    resp: str,
    streamed_text: str,
    text_streamed_live: bool,
    turn_emitter: Optional[Any],
) -> tuple[str, List[str]]:
    """
    Canonical answer emission after generate_response post-process.

    Live token stream is a UX preview only. After post-process (citations, sanitize)
    we always replace the bubble with ``content_sync`` so UI and DB match the node output.
    """
    canonical = resp if isinstance(resp, str) else ""
    if not (canonical or "").strip():
        return streamed_text, []
    events: List[str] = []
    if text_streamed_live:
        sse = _format_content_sync_sse(turn_emitter, canonical)
        if sse:
            events.append(sse)
        return canonical, events
    sse = _format_text_delta_sse(turn_emitter, canonical)
    if sse:
        events.append(sse)
    return canonical, events


_REASONING_PHASE_LABELS: Dict[str, str] = {
    "generate_draft_plan": "Понимаю задачу и готовлю план документа…",
    "draft": "Генерирую финальный документ по утверждённому плану…",
    "rag_retrieval": "Изучаю материалы дела…",
    "garant_retrieval": "Проверяю справочный правовой контекст…",
    "generate_response": "Формирую ответ…",
    "synthesizing": "Синтезирую ответ…",
    "understanding": "Разбираю запрос…",
    "planning": "Планирую шаги…",
    "retrieval": "Ищу релевантные фрагменты…",
    "tools": "Выполняю инструменты…",
    "tool_calls": "Выполняю инструменты…",
}


def _reasoning_phase_content(phase: str) -> str:
    """Подпись фазы для SSE reasoning: всегда по-русски, без сырого ключа узла в UI."""
    key = str(phase).strip()
    if key in _REASONING_PHASE_LABELS:
        return _REASONING_PHASE_LABELS[key]
    slug = key.replace("_", " ").strip()
    if not slug:
        return "Обрабатываю запрос…"
    return f"Этап: {slug}"


def _reasoning_delta_from_chunk(msg_chunk) -> str:
    """Извлечь reasoning delta из AIMessageChunk (если провайдер отдаёт)."""
    try:
        msg = getattr(msg_chunk, "message", msg_chunk)
        ak = getattr(msg, "additional_kwargs", None) or {}
        parts: List[str] = []
        for key in ("reasoning_content", "reasoning", "thinking"):
            v = ak.get(key)
            if isinstance(v, str) and v:
                parts.append(v)
            elif v is not None and not isinstance(v, str):
                parts.append(str(v))
        return "".join(parts)
    except Exception:
        return ""


def _merge_stream_turn_persist_ctx(
    ctx: Dict[str, Any],
    node_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Accumulate graph fields needed to rebuild outbound turn_state at save time."""
    outbound: Optional[Dict[str, Any]] = None
    for key in (
        "structured_data_plane",
        "statement_scope_file_ids",
        "hybrid_rag_file_ids",
        "scoped_file_ids",
        "statement_sql_meta",
    ):
        val = node_data.get(key)
        if val is not None:
            ctx[key] = val
    if node_data.get("citations"):
        ctx["citations"] = node_data["citations"]
    ots = node_data.get("outbound_turn_state")
    if isinstance(ots, dict) and str(ots.get("domain") or "").strip().lower() not in {"", "none"}:
        ctx["outbound_turn_state"] = ots
        outbound = ots
    return outbound


class ChatGraphService:
    """
    Сервис для работы с ChatGraph.
    
    Обеспечивает:
    - Создание и кэширование графа
    - Streaming ответов с форматированием для assistant-ui
    - Сохранение сообщений в БД
    """
    
    _graph_instance = None
    
    def _require_case_for_user(self, case_id: str, user: User) -> Optional[Case]:
        """Membership ACL for case chat graph paths."""
        try:
            return require_case_access(self.db, case_id, user.id)
        except HTTPException:
            return None


    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Инициализация сервиса.
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.db = db
        self.rag_service = rag_service or RAGService()
        self.document_processor = document_processor or DocumentProcessor()
    
    def _get_or_create_graph(self) -> tuple[Any, int]:
        """Получить или создать экземпляр графа. Возвращает (graph, compile_ms)."""
        t0 = time.monotonic()
        compiled = False
        if ChatGraphService._graph_instance is None:
            ChatGraphService._graph_instance = create_chat_graph(
                db=self.db,
                rag_service=self.rag_service,
                document_processor=self.document_processor,
                use_checkpointing=True
            )
            compiled = True
            logger.info("[ChatGraphService] Created new ChatGraph instance")
        compile_ms = int((time.monotonic() - t0) * 1000) if compiled else 0
        return ChatGraphService._graph_instance, compile_ms
    
    def _determine_mode(
        self,
        deep_think: bool = False,
        legal_research: bool = False,
        draft_mode: bool = False
    ) -> Literal["normal", "deep_think", "garant", "draft"]:
        """
        Определить режим на основе флагов.
        
        Args:
            deep_think: Режим глубокого мышления
            legal_research: Режим справочного правового поиска
            draft_mode: Режим создания документа
        
        Returns:
            Режим работы графа
        """
        if draft_mode:
            return "draft"
        elif deep_think:
            return "deep_think"
        elif legal_research:
            return "garant"
        else:
            return "normal"

    def _resolve_case_canonical_messages(
        self,
        case_id: str,
        session_id: str,
        question: str,
        *,
        hydrate_from_db: bool,
    ) -> Optional[List[BaseMessage]]:
        """Load canonical LangChain messages from Postgres session transcript."""
        if not hydrate_from_db:
            return None
        sid = (session_id or "").strip()
        if not sid:
            return None
        from app.services.chat.dialog_transcript_service import build_case_turn_messages
        from app.services.chat.history_service import ChatHistoryService

        transcript = ChatHistoryService(self.db).get_history_for_context(case_id, sid)
        return build_case_turn_messages(transcript, question)

    @staticmethod
    def _apply_canonical_messages(
        state: Dict[str, Any],
        canonical_messages: List[BaseMessage],
    ) -> None:
        from app.services.chat.dialog_transcript_service import reconcile_langchain_messages

        checkpoint_messages = state.get("messages")
        merged, replaced = reconcile_langchain_messages(checkpoint_messages, canonical_messages)
        state["messages"] = merged
        if replaced:
            logger.info(
                "[ChatGraphService] DB transcript hydrated (%s messages)",
                len(merged),
            )

    def _resolve_template_context(
        self,
        *,
        question: str,
        draft_mode: bool,
        document_context: Optional[str],
        template_system_id: Optional[str] = None,
        template_file_id: Optional[str] = None,
        template_file_content: Optional[str] = None,
    ) -> tuple:
        """Шаблон draft — только в draft_mode; в case/editor чате не подбираем."""
        if not draft_mode:
            return "", None, None
        from app.services.draft_template_context import resolve_draft_template_context

        return resolve_draft_template_context(
            self.db,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
            user_question=question,
        )
    
    def _resolve_case_session(self, session_id: Optional[str]) -> str:
        """Client-authoritative session id (mint new UUID when client sends none)."""
        from app.services.chat.case_chat_session import resolve_case_chat_session_id

        resolved, _kind = resolve_case_chat_session_id(session_id)
        return resolved
    
    def _get_or_create_thread_id(self, case_id: str, session_id: str) -> str:
        """
        Получить или создать thread_id для checkpointing.
        
        Использует session_id как thread_id для переиспользования состояния между запросами.
        Это позволяет LangGraph продолжать диалог, загружая предыдущее состояние из checkpoint.
        
        Args:
            case_id: ID дела
            session_id: ID сессии чата
            
        Returns:
            thread_id для использования в config LangGraph
        """
        # Используем session_id как thread_id для переиспользования состояния
        # Формат: case_id_session_id для уникальности
        thread_id = f"{case_id}_{session_id}"
        
        logger.debug(f"[ChatGraphService] Using thread_id: {thread_id} (from session_id: {session_id})")
        return thread_id

    @staticmethod
    def _apply_new_turn_state(
        current_state: dict,
        *,
        is_editor_chat: bool,
        turn_id: Optional[str],
        editor_mode_hint: Optional[str],
        mode: str,
    ) -> None:
        """Сброс ephemeral-полей между ходами (draft HITL + editor turn contract)."""
        ChatGraphService._reset_draft_hitl_for_turn(current_state, mode)
        if is_editor_chat and turn_id:
            from app.services.chat.turn_contract import (
                normalize_editor_intent,
                reset_editor_ephemeral_for_turn,
            )

            reset_editor_ephemeral_for_turn(
                current_state,
                turn_id=turn_id,
                intent=normalize_editor_intent(editor_mode_hint),
            )
            return
        current_state["response"] = None
        current_state["rag_context"] = None
        current_state["garant_context"] = None
        current_state["rag_documents"] = None
        current_state["citations"] = []
        current_state["context_pipeline_meta"] = None
        current_state["retrieval_task"] = None
        current_state["scoped_file_ids"] = None
        current_state["scoped_doc_type"] = None
        current_state["thinking_steps"] = None
        current_state["answer_blocks"] = None

    @staticmethod
    def _reset_draft_hitl_for_turn(current_state: dict, mode: str) -> None:
        """
        Сброс устаревшего LangGraph-состояния черновика между запросами.

        Без DRAFT_PLAN_APPROVAL_ENABLED: каждый ход — сразу генерация документа (draft_approved=True).
        С планом (legacy): сохраняем waiting_for_approval и сброс одобрения между уточнениями.
        """
        if mode == "draft":
            if not bool(getattr(config, "DRAFT_PLAN_APPROVAL_ENABLED", False)):
                current_state["draft_plan"] = None
                current_state["draft_approved"] = True
                current_state["waiting_for_approval"] = False
            elif current_state.get("waiting_for_approval"):
                current_state["draft_approved"] = False
            elif not current_state.get("waiting_for_approval"):
                current_state["draft_plan"] = None
                current_state["draft_approved"] = False
        else:
            current_state["draft_plan"] = None
            current_state["draft_approved"] = False
            current_state["waiting_for_approval"] = False

    async def warmup_case_graph(
        self,
        case_id: str,
        user: User,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Прогрев при открытии экрана чата по делу: компиляция/кэш графа + чтение чекпоинта.
        Снижает задержку первого сообщения без изменения ответов.
        """
        case = self._require_case_for_user(case_id, user)
        if not case:
            return {"ok": False, "error": "case_not_found"}

        from app.services.chat.case_chat_session import resolve_case_chat_session_id

        resolved_session, _resolution = resolve_case_chat_session_id(session_id)

        t0 = time.monotonic()
        graph, graph_compile_ms = self._get_or_create_graph()
        thread_id = self._get_or_create_thread_id(case_id, resolved_session)
        graph_run_config: Dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _case_graph_recursion_limit(),
        }
        checkpoint_has_values = False
        try:
            st = await graph.aget_state(graph_run_config)
            checkpoint_has_values = bool(st and st.values)
        except Exception as exc:
            logger.warning("[ChatGraphService] warmup aget_state failed: %s", exc, exc_info=True)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[ChatGraphService] warmup case=%s session=%s checkpoint=%s ms=%s",
            case_id,
            resolved_session,
            checkpoint_has_values,
            elapsed_ms,
        )
        return {
            "ok": True,
            "case_id": case_id,
            "session_id": resolved_session,
            "thread_id": thread_id,
            "checkpoint_has_values": checkpoint_has_values,
            "warmup_ms": elapsed_ms,
            "graph_compile_ms": graph_compile_ms,
        }

    async def warmup_editor_graph(
        self,
        case_id: str,
        document_id: str,
        user: User,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Прогрев при открытии редактора: кэш графа + опционально чтение checkpoint сессии.
        """
        from app.services.chat.editor_session import (
            editor_thread_id,
            resolve_editor_chat_session_id,
        )

        case = self._require_case_for_user(case_id, user)
        if not case:
            return {"ok": False, "error": "case_not_found"}

        doc_id = (document_id or "new").strip()
        resolved_session = resolve_editor_chat_session_id(
            user_id=str(user.id),
            case_id=case_id,
            document_id=doc_id,
            requested_session_id=session_id,
        )

        t0 = time.monotonic()
        graph, graph_compile_ms = self._get_or_create_graph()
        thread_id = editor_thread_id(case_id, resolved_session)
        graph_run_config: Dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _case_graph_recursion_limit(),
        }
        checkpoint_has_values = False
        try:
            st = await graph.aget_state(graph_run_config)
            checkpoint_has_values = bool(st and st.values)
        except Exception as exc:
            logger.warning(
                "[ChatGraphService] editor warmup aget_state failed: %s",
                exc,
                exc_info=True,
            )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[ChatGraphService] editor warmup case=%s doc=%s session=%s checkpoint=%s compile_ms=%s total_ms=%s",
            case_id,
            doc_id,
            resolved_session,
            checkpoint_has_values,
            graph_compile_ms,
            elapsed_ms,
        )
        return {
            "ok": True,
            "case_id": case_id,
            "document_id": doc_id,
            "session_id": resolved_session,
            "thread_id": thread_id,
            "checkpoint_has_values": checkpoint_has_values,
            "warmup_ms": elapsed_ms,
            "graph_compile_ms": graph_compile_ms,
        }
    
    def _save_user_message(
        self,
        case_id: str,
        question: str,
        session_id: str
    ) -> str:
        """Сохранить сообщение пользователя в БД."""
        message_id = str(uuid.uuid4())
        try:
            user_message = ChatMessage(
                id=message_id,
                case_id=case_id,
                role="user",
                content=question,
                session_id=session_id
            )
            self.db.add(user_message)
            self.db.commit()
            logger.info(f"[ChatGraphService] Saved user message: {message_id}")
        except Exception as e:
            self.db.rollback()
            logger.warning(f"[ChatGraphService] Failed to save user message: {e}")
        return message_id
    
    def _save_assistant_message(
        self,
        case_id: str,
        content: str,
        session_id: str,
        citations: List[Dict] = None,
        answer_blocks: List[Dict] = None,
        turn_state: Optional[Dict[str, Any]] = None,
        persist_ctx: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Сохранить ответ ассистента в БД."""
        from app.services.chat.assistant_persist_payload import build_case_assistant_evidence
        from app.services.chat.outbound_turn_state import build_outbound_turn_state

        message_id = str(uuid.uuid4())
        resolved_turn_state = turn_state
        if not resolved_turn_state and isinstance(persist_ctx, dict):
            resolved_turn_state = build_outbound_turn_state(persist_ctx)

        evidence = build_case_assistant_evidence(
            citations=list(citations or []),
            turn_state=resolved_turn_state if isinstance(resolved_turn_state, dict) else None,
        )
        if answer_blocks:
            evidence["answer_blocks"] = answer_blocks

        try:
            refs_payload = None
            if answer_blocks:
                refs_payload = {"citations": citations or [], "answer_blocks": answer_blocks}
            elif citations:
                refs_payload = citations
            assistant_message = ChatMessage(
                id=message_id,
                case_id=case_id,
                role="assistant",
                content=content,
                source_references=json.dumps(refs_payload, ensure_ascii=False) if refs_payload else None,
                evidence=evidence,
                session_id=session_id
            )
            self.db.add(assistant_message)
            self.db.commit()
            logger.info(f"[ChatGraphService] Saved assistant message: {message_id}")
        except Exception as e:
            self.db.rollback()
            logger.warning(f"[ChatGraphService] Failed to save assistant message: {e}")
        return message_id

    @staticmethod
    def _normalize_attached_file_ids(
        attached_file_ids: Optional[List[str]],
    ) -> Optional[List[str]]:
        if not attached_file_ids:
            return None
        from app.config import config as app_config

        max_files = max(1, int(getattr(app_config, "EDITOR_ATTACH_MAX_FILES", 3) or 3))
        ids = [str(x).strip() for x in attached_file_ids if str(x).strip()]
        return ids[:max_files] if ids else None

    def _apply_editor_attached_files_context(
        self,
        state: Dict[str, Any],
        *,
        case_id: str,
        user_id: str,
        attached_file_ids: Optional[List[str]],
    ) -> None:
        """Заполняет attached_case_files_context для редактора (полный текст, без RAG)."""
        from app.config import config as app_config

        ids = self._normalize_attached_file_ids(attached_file_ids)
        state["attached_file_ids"] = ids
        if not ids or not getattr(app_config, "EDITOR_ATTACH_FULL_TEXT_ENABLED", True):
            state["attached_case_files_context"] = None
            return
        from app.services.structured_file_text import build_editor_attached_files_context

        ctx = build_editor_attached_files_context(
            self.db,
            case_id=case_id,
            user_id=user_id,
            file_ids=ids,
        )
        state["attached_case_files_context"] = ctx or None
        if ctx:
            logger.info(
                "[ChatGraphService] Editor attach full-text: %s file(s), %s chars",
                len(ids),
                len(ctx),
            )
    
    async def stream_response(
        self,
        case_id: str,
        question: str,
        user: User,
        deep_think: bool = False,
        legal_research: bool = False,
        court_practice: bool = False,
        draft_mode: bool = False,
        document_context: str = None,
        document_id: str = None,
        selected_text: str = None,
        stream_mode: str = "updates",
        enable_token_streaming: bool = False,
        existing_messages: List[BaseMessage] = None,
        editor_mode_hint: str = None,
        template_system_id: str = None,
        template_file_id: str = None,
        template_file_content: str = None,
        session_id: str = None,
        persist_history: bool = True,
        attached_file_ids: Optional[List[str]] = None,
        # Политика/бюджет выполнения (case assistant v2)
        task_type: Optional[str] = None,
        depth_tier: Optional[str] = None,
        budget_profile: Optional[Dict[str, Any]] = None,
        corpus_size: Optional[int] = None,
        clarification_needed: Optional[bool] = None,
        retrieval_task: Optional[Dict[str, Any]] = None,
        scoped_file_ids: Optional[List[str]] = None,
        scoped_doc_type: Optional[str] = None,
    session_context_prompt: Optional[str] = None,
    session_context_meta: Optional[Dict[str, Any]] = None,
    structured_data_plane: Optional[str] = None,
    statement_scope_file_ids: Optional[List[str]] = None,
    hybrid_rag_file_ids: Optional[List[str]] = None,
    structured_data_router_meta: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
        """
        Streaming ответ через ChatGraph.
        
        Args:
            case_id: ID дела
            question: Вопрос пользователя
            user: Текущий пользователь
            deep_think: Режим глубокого мышления
            legal_research: Режим справочного правового поиска
            draft_mode: Режим создания документа
            document_context: Контекст документа (для редактора)
            document_id: ID документа (для редактора)
            selected_text: Выделенный текст (для редактора)
            stream_mode: Режим streaming ("values", "updates", "messages")
            enable_token_streaming: Включить streaming токенов через astream_events
            existing_messages: Существующие сообщения для продолжения диалога
            attached_file_ids: ID файлов дела для узкого RAG (draft и др.)
        
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        logger.info(f"[ChatGraphService] Starting stream for case {case_id}, mode={self._determine_mode(deep_think, legal_research, draft_mode)}")
        
        # Проверяем доступ к делу
        case = self._require_case_for_user(case_id, user)
        
        if not case:
            yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
            return

        template_context, template_label, template_key = self._resolve_template_context(
            question=question,
            draft_mode=draft_mode,
            document_context=document_context,
            template_system_id=template_system_id,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
        )
        
        # Сессия: редактор — client session_id или стабильная нить на документ.
        is_editor_chat = bool(document_context) and not draft_mode
        attached_file_ids = self._normalize_attached_file_ids(attached_file_ids)
        if is_editor_chat:
            from app.services.chat.editor_session import resolve_editor_chat_session_id

            session_id = resolve_editor_chat_session_id(
                user_id=str(user.id),
                case_id=case_id,
                document_id=document_id or "new",
                requested_session_id=session_id,
            )
        else:
            session_id = self._resolve_case_session(session_id)

        # Сохраняем сообщение пользователя (если не обрабатывается внешним оркестратором)
        if persist_history:
            self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(deep_think, legal_research, draft_mode)

        active_turn_id: Optional[str] = str(uuid.uuid4()) if is_editor_chat else None
        turn_emitter = None
        if is_editor_chat and active_turn_id:
            from app.services.chat.turn_emitter import EditorTurnEmitter

            turn_emitter = EditorTurnEmitter.for_editor(
                active_turn_id,
                editor_mode_hint,
                document_id,
            )

        trace_ctx = get_active_trace_context()
        _prep_meta: Dict[str, Any] = {
            "case_id": case_id,
            "graph_mode": mode,
            "persist_history": persist_history,
        }
        if is_editor_chat:
            _prep_meta.update(
                {
                    "document_id": document_id,
                    "editor_mode_hint": editor_mode_hint,
                    "document_context_chars": len(document_context or ""),
                    "has_selection": bool((selected_text or "").strip()),
                }
            )
        prep_span = trace_span(
            trace_ctx,
            name="document_editor_prepare" if is_editor_chat else "case_chat_graph_prepare",
            metadata=_prep_meta,
        )
        prep_started = time.monotonic()
        checkpoint_dialog_continued = False
        editor_latency = None
        if is_editor_chat:
            from app.services.observability.editor_latency_trace import EditorTurnLatency

            editor_latency = EditorTurnLatency(
                turn_id=active_turn_id,
                document_id=document_id,
                editor_mode_hint=editor_mode_hint,
            )

        # Получаем граф
        if is_editor_chat:
            graph, graph_compile_ms = self._get_or_create_graph()
        else:
            with assistant_step_span("case", "graph_prepare.get_or_compile") as gc_out:
                graph, graph_compile_ms = self._get_or_create_graph()
                gc_out["graph_compile_ms"] = graph_compile_ms
        after_graph_ms = int((time.monotonic() - prep_started) * 1000)

        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        if is_editor_chat:
            thread_id = self._get_or_create_thread_id(case_id, session_id)
        else:
            with assistant_step_span("case", "graph_prepare.thread_id") as th_out:
                thread_id = self._get_or_create_thread_id(case_id, session_id)
                th_out["thread_id"] = thread_id
        graph_run_config: Dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _case_graph_recursion_limit(),
        }
        if langfuse_enabled():
            _lf_tags = ["case_assistant", "chat_graph"]
            if is_editor_chat:
                _lf_tags = [
                    "document_editor",
                    "chat_graph",
                    f"editor_{(editor_mode_hint or 'ask').strip().lower()}",
                ]
            _lc = get_langchain_callbacks(
                session_id=session_id,
                user_id=str(user.id),
                tags=_lf_tags,
            )
            if _lc:
                graph_run_config["callbacks"] = _lc

        if is_editor_chat:
            canonical_messages = self._resolve_case_canonical_messages(
                case_id,
                session_id,
                question,
                hydrate_from_db=not is_editor_chat,
            )
        else:
            with assistant_step_span("case", "graph_prepare.hydrate_messages") as hm_out:
                canonical_messages = self._resolve_case_canonical_messages(
                    case_id,
                    session_id,
                    question,
                    hydrate_from_db=not is_editor_chat,
                )
                hm_out["message_count"] = len(canonical_messages) if canonical_messages else 0
        
        # Загружаем существующее состояние из checkpoint для продолжения диалога
        try:
            if is_editor_chat:
                existing_state = await graph.aget_state(graph_run_config)
            else:
                with assistant_step_span("case", "graph_prepare.checkpoint_aget_state") as cp_out:
                    existing_state = await graph.aget_state(graph_run_config)
                    cp_out["has_values"] = bool(existing_state and existing_state.values)
            if existing_state and existing_state.values:
                checkpoint_dialog_continued = True
                # Продолжаем диалог - используем существующее состояние
                current_state = dict(existing_state.values)
                # Инициализируем поля HITL если их нет (для совместимости со старыми checkpoint)
                if "draft_plan" not in current_state:
                    current_state["draft_plan"] = None
                if "draft_approved" not in current_state:
                    current_state["draft_approved"] = False
                if "waiting_for_approval" not in current_state:
                    current_state["waiting_for_approval"] = False
                if "template_context" not in current_state:
                    current_state["template_context"] = ""
                if "template_label" not in current_state:
                    current_state["template_label"] = None
                if "template_key" not in current_state:
                    current_state["template_key"] = None
                if "template_system_id" not in current_state:
                    current_state["template_system_id"] = None
                if "template_field_catalog" not in current_state:
                    current_state["template_field_catalog"] = None
                if attached_file_ids is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_file_ids if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                if canonical_messages is not None:
                    self._apply_canonical_messages(current_state, canonical_messages)
                else:
                    current_messages = current_state.get("messages", [])
                    current_messages.append(HumanMessage(content=question))
                    current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = legal_research or mode == "garant"
                current_state["enable_court_practice"] = bool(court_practice)
                # Политика/бюджет выполнения (обновляем на каждый turn)
                if task_type is not None:
                    current_state["task_type"] = task_type
                if depth_tier is not None:
                    current_state["depth_tier"] = depth_tier
                if budget_profile is not None:
                    current_state["budget_profile"] = budget_profile
                    if budget_profile.get("execution_tier"):
                        current_state["execution_tier"] = budget_profile["execution_tier"]
                    if budget_profile.get("response_shape"):
                        current_state["response_shape"] = budget_profile["response_shape"]
                    if budget_profile.get("primary_intent"):
                        current_state["primary_intent"] = budget_profile["primary_intent"]
                    if budget_profile.get("resolved_question"):
                        current_state["question"] = str(budget_profile["resolved_question"])
                        current_state["original_question"] = str(
                            budget_profile.get("original_question") or question
                        )
                    current_state["retrieval_round"] = 0
                    current_state["escalated_from"] = None
                    current_state["grade_retrieval_ok"] = None
                if corpus_size is not None:
                    current_state["corpus_size"] = corpus_size
                if clarification_needed is not None:
                    current_state["clarification_needed"] = clarification_needed
                if document_context:
                    current_state["document_context"] = document_context
                if document_id:
                    current_state["document_id"] = document_id
                if selected_text:
                    current_state["selected_text"] = selected_text
                if editor_mode_hint:
                    current_state["editor_mode_hint"] = editor_mode_hint
                current_state["template_context"] = template_context or ""
                current_state["template_label"] = template_label
                if retrieval_task is not None:
                    current_state["retrieval_task"] = retrieval_task
                if scoped_file_ids is not None:
                    current_state["scoped_file_ids"] = scoped_file_ids
                if scoped_doc_type is not None:
                    current_state["scoped_doc_type"] = scoped_doc_type
                if session_context_prompt:
                    current_state["session_context_prompt"] = session_context_prompt
                if session_context_meta:
                    current_state["session_context_meta"] = session_context_meta
                if structured_data_plane is not None:
                    current_state["structured_data_plane"] = structured_data_plane
                if statement_scope_file_ids is not None:
                    current_state["statement_scope_file_ids"] = statement_scope_file_ids
                if hybrid_rag_file_ids is not None:
                    current_state["hybrid_rag_file_ids"] = hybrid_rag_file_ids
                if structured_data_router_meta is not None:
                    current_state["structured_data_router_meta"] = structured_data_router_meta
                current_state["transaction_agent_resolved"] = None
                current_state["hybrid_agent_resolved"] = None
                current_state["outbound_turn_state"] = None
                current_state["statement_sql_meta"] = None
                current_state["response"] = None
                self._apply_new_turn_state(
                    current_state,
                    is_editor_chat=is_editor_chat,
                    turn_id=active_turn_id,
                    editor_mode_hint=editor_mode_hint,
                    mode=mode,
                )
                if is_editor_chat:
                    self._apply_editor_attached_files_context(
                        current_state,
                        case_id=case_id,
                        user_id=str(user.id),
                        attached_file_ids=attached_file_ids,
                    )
                initial_state = current_state
                logger.info(f"[ChatGraphService] Continuing dialog from checkpoint, thread_id: {thread_id}")
            else:
                # Новый диалог - создаём начальное состояние
                initial_state = create_initial_chat_state(
                    case_id=case_id,
                    user_id=str(user.id),
                    question=question,
                    mode=mode,
                    enable_garant=legal_research or mode == "garant",
                    enable_court_practice=bool(court_practice),
                    enable_citations=True,
                    document_context=document_context,
                    document_id=document_id,
                    selected_text=selected_text,
                    existing_messages=existing_messages,
                    prebuilt_messages=canonical_messages,
                    editor_mode_hint=editor_mode_hint,
                    template_context=template_context or None,
                    template_label=template_label,
                    template_key=template_key,
                    template_system_id=template_system_id,
                    attached_file_ids=attached_file_ids,
                    task_type=task_type,
                    depth_tier=depth_tier,
                    budget_profile=budget_profile,
                    execution_tier=(budget_profile or {}).get("execution_tier") if budget_profile else None,
                    corpus_size=corpus_size,
                    clarification_needed=clarification_needed,
                    retrieval_task=retrieval_task,
                    scoped_file_ids=scoped_file_ids,
                    scoped_doc_type=scoped_doc_type,
                    legal_research=legal_research,
                    court_practice=court_practice,
                    session_context_prompt=session_context_prompt,
                    session_context_meta=session_context_meta,
                    structured_data_plane=structured_data_plane,
                    statement_scope_file_ids=statement_scope_file_ids,
                    hybrid_rag_file_ids=hybrid_rag_file_ids,
                    structured_data_router_meta=structured_data_router_meta,
                )
                if is_editor_chat and active_turn_id:
                    self._apply_new_turn_state(
                        initial_state,
                        is_editor_chat=True,
                        turn_id=active_turn_id,
                        editor_mode_hint=editor_mode_hint,
                        mode=mode,
                    )
                if is_editor_chat:
                    self._apply_editor_attached_files_context(
                        initial_state,
                        case_id=case_id,
                        user_id=str(user.id),
                        attached_file_ids=attached_file_ids,
                    )
                logger.info(f"[ChatGraphService] Starting new dialog, thread_id: {thread_id}")
        except Exception as e:
            # Если не удалось загрузить состояние, создаём новое
            logger.warning(f"[ChatGraphService] Failed to load state from checkpoint: {e}, creating new state")
            initial_state = create_initial_chat_state(
                case_id=case_id,
                user_id=str(user.id),
                question=question,
                mode=mode,
                enable_garant=legal_research or mode == "garant",
                enable_court_practice=bool(court_practice),
                enable_citations=True,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                existing_messages=existing_messages,
                prebuilt_messages=canonical_messages,
                editor_mode_hint=editor_mode_hint,
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_file_ids,
                task_type=task_type,
                depth_tier=depth_tier,
                budget_profile=budget_profile,
                execution_tier=(budget_profile or {}).get("execution_tier") if budget_profile else None,
                corpus_size=corpus_size,
                clarification_needed=clarification_needed,
                retrieval_task=retrieval_task,
                scoped_file_ids=scoped_file_ids,
                scoped_doc_type=scoped_doc_type,
                legal_research=legal_research,
                court_practice=court_practice,
                session_context_prompt=session_context_prompt,
                session_context_meta=session_context_meta,
                structured_data_plane=structured_data_plane,
                statement_scope_file_ids=statement_scope_file_ids,
                hybrid_rag_file_ids=hybrid_rag_file_ids,
                structured_data_router_meta=structured_data_router_meta,
            )
            if is_editor_chat and active_turn_id:
                self._apply_new_turn_state(
                    initial_state,
                    is_editor_chat=True,
                    turn_id=active_turn_id,
                    editor_mode_hint=editor_mode_hint,
                    mode=mode,
                )
            if is_editor_chat:
                self._apply_editor_attached_files_context(
                    initial_state,
                    case_id=case_id,
                    user_id=str(user.id),
                    attached_file_ids=attached_file_ids,
                )

        prep_ms = int((time.monotonic() - prep_started) * 1000)
        checkpoint_load_ms = prep_ms - after_graph_ms
        if editor_latency is not None:
            editor_latency.thread_id = thread_id
            editor_latency.set_stage(
                "prep",
                prep_ms=prep_ms,
                graph_compile_ms=graph_compile_ms,
                checkpoint_load_ms=max(0, checkpoint_load_ms),
                checkpoint_dialog_continued=checkpoint_dialog_continued,
            )
        if prep_span:
            try:
                prep_span.update(
                    output={
                        "prep_ms": prep_ms,
                        "graph_compile_ms": graph_compile_ms,
                        "checkpoint_load_ms": max(0, checkpoint_load_ms),
                        "thread_id": thread_id,
                        "checkpoint_dialog_continued": checkpoint_dialog_continued,
                    }
                )
            except Exception:
                logger.debug("case_chat_graph_prepare span update failed", exc_info=True)
            try:
                prep_span.end()
            except Exception:
                logger.debug("case_chat_graph_prepare span end failed", exc_info=True)
        
        full_response = ""
        citations = []
        answer_blocks: Optional[List[Dict[str, Any]]] = None
        document_created = None
        draft_plan_sent = False
        model_reasoning_buf = ""
        # Пока модель шлёт reasoning, не показываем ответ — затем одним блоком (корректный порядок UX).
        answer_after_reasoning_buffer = ""
        native_reasoning_phase = False
        last_citations_json: Optional[str] = None
        outbound_turn_state_snapshot: Optional[Dict[str, Any]] = None
        stream_turn_persist_ctx: Dict[str, Any] = {}
        if structured_data_plane:
            stream_turn_persist_ctx["structured_data_plane"] = structured_data_plane
        if statement_scope_file_ids:
            stream_turn_persist_ctx["statement_scope_file_ids"] = list(statement_scope_file_ids)
        if hybrid_rag_file_ids:
            stream_turn_persist_ctx["hybrid_rag_file_ids"] = list(hybrid_rag_file_ids)
        text_streamed_live = False
        stream_reasoning_ui = bool(getattr(config, "CASE_ASSISTANT_STREAM_REASONING_UI", False))
        stream_activity_ui = bool(getattr(config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True))
        # Token streaming: one channel only — custom writer from generate_response (not messages+custom).
        stream_modes: List[str] = ["updates"]
        _case_stream_tokens = bool(getattr(config, "CASE_ASSISTANT_STREAM_CASE_CHAT", True))
        _editor_custom_stream = bool(
            turn_emitter
            and turn_emitter.use_custom_stream_channel()
            and getattr(config, "EDITOR_CHAT_STREAM_ENABLED", True)
        )
        _strict_court_no_tokens = (
            bool(court_practice)
            and not bool(legal_research)
            and not bool(draft_mode)
            and not bool(document_context)
        )
        if _strict_court_no_tokens:
            stream_modes = ["updates", "custom"] if stream_activity_ui else ["updates"]
        elif _editor_custom_stream or _case_stream_tokens or stream_activity_ui:
            stream_modes = ["updates", "custom"]
        else:
            stream_modes = ["messages", "updates"]

        _astream_meta: Dict[str, Any] = {"case_id": case_id, "graph_mode": mode}
        if is_editor_chat:
            _astream_meta.update(
                {
                    "document_id": document_id,
                    "editor_mode_hint": editor_mode_hint,
                    "stream_modes": list(stream_modes),
                }
            )
        astream_span = trace_span(
            trace_ctx,
            name="document_editor_astream" if is_editor_chat else "case_chat_graph_astream",
            metadata=_astream_meta,
        )
        astream_parent_token = (
            set_trace_span_parent(astream_span) if astream_span is not None else None
        )
        stream_t0 = time.monotonic()
        last_graph_update_t = stream_t0
        first_sse_to_client_recorded = False

        def _record_first_sse_to_client() -> None:
            nonlocal first_sse_to_client_recorded
            if first_sse_to_client_recorded:
                return
            first_sse_to_client_recorded = True
            ms = int((time.monotonic() - stream_t0) * 1000)
            if editor_latency is not None:
                editor_latency.set_stage("first_sse_token_to_client", ms=ms)

        if is_editor_chat and trace_ctx:
            trace_contract_event(
                trace_ctx,
                name="llm_generation",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "document_editor",
                        "editor_mode_hint": editor_mode_hint,
                        "document_id": document_id,
                        "thread_id": thread_id,
                        "turn_id": active_turn_id,
                    },
                    step_name="editor_stream_started",
                    status="running",
                ),
                input_payload={"question": (question or "")[:800]},
            )

        if turn_emitter:
            yield turn_emitter.turn_started()

        if stream_activity_ui and not is_editor_chat:
            from app.services.chat.assistant_activity import (
                activity_sse,
                build_stream_started_activity,
            )

            started = build_stream_started_activity(question=question or "")
            yield activity_sse(started)
            _record_first_sse_to_client()

        try:
            # Token-level streaming: используем stream_mode=["messages", "updates"]
            # "messages" даёт токены по мере генерации LLM
            # "updates" даёт метаданные (citations, structured_edits и т.д.)
            try:
                async for stream_mode_type, chunk in graph.astream(
                    initial_state, config=graph_run_config,
                    stream_mode=stream_modes,
                ):
                    if stream_mode_type == "custom":
                        payload = chunk if isinstance(chunk, dict) else {}
                        if payload.get("type") == "assistant_activity":
                            import json as _json_act

                            yield f"data: {_json_act.dumps(payload, ensure_ascii=False)}\n\n"
                            _record_first_sse_to_client()
                            continue
                        if payload.get("type") == "citations" and payload.get("citations"):
                            node_citations = payload.get("citations")
                            if isinstance(node_citations, list):
                                citations = node_citations
                                _cj = json.dumps(citations, ensure_ascii=False, default=str)
                                if _cj != last_citations_json:
                                    last_citations_json = _cj
                                    yield f"data: {json.dumps({'type': 'citations', 'citations': citations}, ensure_ascii=False)}\n\n"
                                    _record_first_sse_to_client()
                            continue
                        delta = payload.get("textDelta") or payload.get("text_delta")
                        if delta:
                            piece = str(delta)
                            if piece:
                                full_response += piece
                                text_streamed_live = True
                                sse = _format_text_delta_sse(turn_emitter, piece)
                                if sse:
                                    _record_first_sse_to_client()
                                    yield sse
                    elif stream_mode_type == "messages":
                        # Token-level streaming от LLM
                        msg_chunk, metadata = chunk
                        # Не транслируем в UI токены из внутренних LLM-вызовов (multi-query, подграфы и т.д.) —
                        # только финальный ответ узла generate_response. Иначе в чат «течёт» служебный текст.
                        _meta = metadata if isinstance(metadata, dict) else {}
                        _lg_node = str(_meta.get("langgraph_node") or "").strip()
                        if _lg_node and _lg_node != "generate_response":
                            continue
                        # Нативное reasoning в SSE — только если CASE_ASSISTANT_STREAM_REASONING_UI (иначе не буферизуем ответ и не «разводим» юриста)
                        r_delta = _reasoning_delta_from_chunk(msg_chunk) if stream_reasoning_ui else ""
                        if r_delta:
                            native_reasoning_phase = True
                            model_reasoning_buf += r_delta
                            yield (
                                f"data: {json.dumps({'type': 'reasoning', 'phase': 'model_reasoning', 'step': 1, 'totalSteps': 1, 'content': model_reasoning_buf}, ensure_ascii=False)}\n\n"
                            )
                        token = ""
                        if hasattr(msg_chunk, "content") and msg_chunk.content:
                            token = msg_chunk.content
                        if token:
                            piece = str(token)
                            if not piece:
                                continue
                            to_emit = incremental_stream_piece(full_response, piece)
                            if not to_emit:
                                continue
                            # Пока идёт reasoning в том же потоке, ответ копим; первый чистый answer-chunk — отдаём весь накопленный текст сразу.
                            if native_reasoning_phase and r_delta:
                                answer_after_reasoning_buffer += to_emit
                            elif native_reasoning_phase and not r_delta:
                                block = answer_after_reasoning_buffer + to_emit
                                answer_after_reasoning_buffer = ""
                                native_reasoning_phase = False
                                full_response += block
                                text_streamed_live = True
                                sse = _format_text_delta_sse(turn_emitter, block)
                                if sse:
                                    _record_first_sse_to_client()
                                    yield sse
                            else:
                                full_response += to_emit
                                text_streamed_live = True
                                sse = _format_text_delta_sse(turn_emitter, to_emit)
                                if sse:
                                    _record_first_sse_to_client()
                                    yield sse

                    elif stream_mode_type == "updates":
                        # Node-level updates для метаданных
                        if isinstance(chunk, dict):
                            for node_name, node_data in chunk.items():
                                if not isinstance(node_data, dict):
                                    continue
                                _now = time.monotonic()
                                _since_prev_node_ms = int((_now - last_graph_update_t) * 1000)
                                _gn_extra: Dict[str, Any] = {}
                                if is_editor_chat:
                                    from app.services.observability.editor_langfuse_tracing import (
                                        enrich_editor_graph_node_metadata,
                                    )

                                    _gn_extra.update(
                                        enrich_editor_graph_node_metadata(
                                            str(node_name),
                                            node_data,
                                            editor_mode_hint=editor_mode_hint,
                                        )
                                    )
                                record_graph_node_completed(
                                    "case",
                                    node_name=str(node_name),
                                    node_data=node_data,
                                    since_stream_start_ms=int((_now - stream_t0) * 1000),
                                    since_prev_graph_update_ms=_since_prev_node_ms,
                                    extra=_gn_extra or None,
                                )
                                last_graph_update_t = _now
                                if editor_latency is not None:
                                    _node_extra: Dict[str, Any] = {}
                                    if node_name == "generate_response":
                                        _elm = node_data.get("editor_latency_meta")
                                        if isinstance(_elm, dict):
                                            _llm_sub = _elm.get("llm")
                                            if isinstance(_llm_sub, dict):
                                                editor_latency.merge_llm_metrics(_llm_sub)
                                            else:
                                                editor_latency.merge_llm_metrics(_elm)
                                            _prompt_sub = _elm.get("prompt")
                                            if isinstance(_prompt_sub, dict):
                                                editor_latency.prompt.update(_prompt_sub)
                                            for _pk in (
                                                "postprocess_ms",
                                                "strip_ms",
                                                "dc_expand_ms",
                                                "bracket_repair_ms",
                                            ):
                                                if _pk in _elm:
                                                    editor_latency.stages.setdefault(
                                                        "postprocess", {}
                                                    )[_pk] = _elm[_pk]
                                            for _pk in (
                                                "ttft_ms",
                                                "stream_wall_ms",
                                                "invoke_wall_ms",
                                                "chunk_count",
                                                "output_chars",
                                            ):
                                                if _pk in _elm:
                                                    editor_latency.merge_llm_metrics(
                                                        {_pk: _elm[_pk]}
                                                    )
                                            _node_extra["editor_latency_meta"] = True
                                    editor_latency.add_graph_node(
                                        str(node_name),
                                        since_stream_start_ms=int((_now - stream_t0) * 1000),
                                        since_prev_ms=_since_prev_node_ms,
                                        extra=_node_extra or None,
                                    )

                                if node_name == "generate_response" and node_data.get("response") is not None:
                                    answer_after_reasoning_buffer = ""
                                    native_reasoning_phase = False

                                # Финальный response (RAG, SQL, hybrid, clarify, quality gate).
                                from app.services.chat.turn_contract import (
                                    CASE_FINAL_RESPONSE_NODES,
                                    EDITOR_FINAL_RESPONSE_NODES,
                                )

                                final_nodes = (
                                    EDITOR_FINAL_RESPONSE_NODES
                                    if is_editor_chat
                                    else CASE_FINAL_RESPONSE_NODES
                                )
                                response = node_data.get("response")
                                if (
                                    isinstance(response, str)
                                    and response.strip()
                                    and node_name in final_nodes
                                ):
                                    full_response, sync_events = _finalize_generate_response_text(
                                        resp=response,
                                        streamed_text=full_response,
                                        text_streamed_live=text_streamed_live,
                                        turn_emitter=turn_emitter,
                                    )
                                    if sync_events:
                                        text_streamed_live = True
                                    for sse in sync_events:
                                        yield sse

                                ots = _merge_stream_turn_persist_ctx(stream_turn_persist_ctx, node_data)
                                if ots is not None:
                                    outbound_turn_state_snapshot = ots
                                    yield (
                                        f"data: {json.dumps({'type': 'turn_state', 'turn_state': ots}, ensure_ascii=False, default=str)}\n\n"
                                    )

                                # Citations сразу при появлении в графе (RAG → обогащение в generate_response), чтобы UI линковал сноски с первого символа ответа.
                                node_citations = node_data.get("citations")
                                if node_citations:
                                    citations = node_citations
                                    _cj = json.dumps(citations, ensure_ascii=False, default=str)
                                    if _cj != last_citations_json:
                                        last_citations_json = _cj
                                        yield f"data: {json.dumps({'type': 'citations', 'citations': citations}, ensure_ascii=False)}\n\n"

                                node_ab = node_data.get("answer_blocks")
                                if node_ab is not None:
                                    answer_blocks = node_ab

                                # Обрабатываем document_created (draft mode)
                                doc_created = node_data.get("document_created")
                                if doc_created:
                                    document_created = doc_created
                                    yield f"data: {json.dumps({'type': 'document-card', 'data': doc_created})}\n\n"

                                # Обрабатываем draft_plan (HITL draft mode)
                                draft_plan = node_data.get("draft_plan")
                                waiting_for_approval = bool(node_data.get("waiting_for_approval"))
                                if (
                                    waiting_for_approval
                                    and isinstance(draft_plan, dict)
                                    and not draft_plan_sent
                                ):
                                    draft_plan_sent = True
                                    yield (
                                        f"data: {json.dumps({'type': 'draft_plan', 'plan': draft_plan, 'waiting_for_approval': True}, ensure_ascii=False)}\n\n"
                                    )

                                # Обрабатываем thinking_steps (deep_think mode)
                                if stream_reasoning_ui:
                                    thinking_steps = node_data.get("thinking_steps")
                                    if thinking_steps:
                                        for step in thinking_steps:
                                            yield f"data: {json.dumps({'type': 'thinking-step', 'data': step})}\n\n"

                                # Patch proposals — only edit intent + producing nodes (turn contract).
                                structured_edits = node_data.get("structured_edits")
                                if structured_edits:
                                    if turn_emitter:
                                        patch_sse = turn_emitter.structured_edits_from_node(
                                            str(node_name),
                                            structured_edits,
                                        )
                                        if patch_sse:
                                            yield patch_sse
                                            logger.info(
                                                "[ChatGraphService] Sent %s structured edits (turn=%s)",
                                                turn_emitter.last_patch_count,
                                                turn_emitter.turn_id,
                                            )
                                    else:
                                        from app.services.chat.events import SSESerializer

                                        yield SSESerializer.structured_edits(structured_edits)
                                        logger.info(
                                            f"[ChatGraphService] Sent {len(structured_edits)} structured edits"
                                        )

                                if stream_activity_ui and not is_editor_chat:
                                    from app.services.chat.assistant_activity import (
                                        activity_sse,
                                        build_graph_node_activity,
                                    )

                                    activity = build_graph_node_activity(
                                        str(node_name),
                                        node_data,
                                        question=question or "",
                                    )
                                    if activity:
                                        yield activity_sse(activity)
                                        _record_first_sse_to_client()

                                # Legacy: model reasoning / static phase labels (opt-in)
                                phase = node_data.get("current_phase")
                                if phase:
                                    if stream_reasoning_ui:
                                        yield (
                                            f"data: {json.dumps({'type': 'reasoning', 'phase': str(phase), 'step': 1, 'totalSteps': 1, 'content': _reasoning_phase_content(str(phase))}, ensure_ascii=False)}\n\n"
                                        )
                                    yield f"data: {json.dumps({'type': 'status', 'phase': phase})}\n\n"

            except TypeError:
                # Fallback: если LangGraph не поддерживает multi-mode streaming
                logger.warning("[ChatGraphService] Multi-mode streaming not supported, falling back to updates mode")
                async for chunk in graph.astream(initial_state, config=graph_run_config):
                    if isinstance(chunk, dict):
                        for node_name, node_data in chunk.items():
                            if not isinstance(node_data, dict):
                                continue
                            _now_fb = time.monotonic()
                            record_graph_node_completed(
                                "case",
                                node_name=str(node_name),
                                node_data=node_data,
                                since_stream_start_ms=int((_now_fb - stream_t0) * 1000),
                                since_prev_graph_update_ms=int(
                                    (_now_fb - last_graph_update_t) * 1000
                                ),
                                extra={"stream_fallback": "single_mode_updates"},
                            )
                            last_graph_update_t = _now_fb

                            # Обрабатываем messages (legacy single-mode fallback)
                            messages = node_data.get("messages", [])
                            for msg in messages:
                                if isinstance(msg, AIMessage) and msg.content:
                                    content = str(msg.content)
                                    if content.strip():
                                        full_response, sync_events = _finalize_generate_response_text(
                                            resp=content,
                                            streamed_text=full_response,
                                            text_streamed_live=text_streamed_live,
                                            turn_emitter=turn_emitter,
                                        )
                                        if sync_events:
                                            text_streamed_live = True
                                        for sse in sync_events:
                                            yield sse

                            response = node_data.get("response")
                            if isinstance(response, str) and response.strip():
                                full_response, sync_events = _finalize_generate_response_text(
                                    resp=response,
                                    streamed_text=full_response,
                                    text_streamed_live=text_streamed_live,
                                    turn_emitter=turn_emitter,
                                )
                                if sync_events:
                                    text_streamed_live = True
                                for sse in sync_events:
                                    yield sse

                            node_citations = node_data.get("citations")
                            if node_citations:
                                citations = node_citations
                                _cj_fb = json.dumps(citations, ensure_ascii=False, default=str)
                                if _cj_fb != last_citations_json:
                                    last_citations_json = _cj_fb
                                    yield f"data: {json.dumps({'type': 'citations', 'citations': citations}, ensure_ascii=False)}\n\n"

                            node_ab = node_data.get("answer_blocks")
                            if node_ab is not None:
                                answer_blocks = node_ab

                            ots_fb = _merge_stream_turn_persist_ctx(stream_turn_persist_ctx, node_data)
                            if ots_fb is not None:
                                outbound_turn_state_snapshot = ots_fb
                                yield (
                                    f"data: {json.dumps({'type': 'turn_state', 'turn_state': ots_fb}, ensure_ascii=False, default=str)}\n\n"
                                )

                            doc_created = node_data.get("document_created")
                            if doc_created:
                                document_created = doc_created
                                yield f"data: {json.dumps({'type': 'document-card', 'data': doc_created})}\n\n"

                            draft_plan = node_data.get("draft_plan")
                            waiting_for_approval = bool(node_data.get("waiting_for_approval"))
                            if (
                                waiting_for_approval
                                and isinstance(draft_plan, dict)
                                and not draft_plan_sent
                            ):
                                draft_plan_sent = True
                                yield (
                                    f"data: {json.dumps({'type': 'draft_plan', 'plan': draft_plan, 'waiting_for_approval': True}, ensure_ascii=False)}\n\n"
                                )

                            if stream_reasoning_ui:
                                thinking_steps = node_data.get("thinking_steps")
                                if thinking_steps:
                                    for step in thinking_steps:
                                        yield f"data: {json.dumps({'type': 'thinking-step', 'data': step})}\n\n"

                            structured_edits = node_data.get("structured_edits")
                            if structured_edits:
                                if turn_emitter:
                                    patch_sse = turn_emitter.structured_edits_from_node(
                                        str(node_name),
                                        structured_edits,
                                    )
                                    if patch_sse:
                                        yield patch_sse
                                else:
                                    from app.services.chat.events import SSESerializer

                                    yield SSESerializer.structured_edits(structured_edits)

                            if stream_activity_ui and not is_editor_chat:
                                from app.services.chat.assistant_activity import (
                                    activity_sse,
                                    build_graph_node_activity,
                                )

                                activity = build_graph_node_activity(
                                    str(node_name),
                                    node_data,
                                    question=question or "",
                                )
                                if activity:
                                    yield activity_sse(activity)

                            phase = node_data.get("current_phase")
                            if phase:
                                if stream_reasoning_ui:
                                    yield (
                                        f"data: {json.dumps({'type': 'reasoning', 'phase': str(phase), 'step': 1, 'totalSteps': 1, 'content': _reasoning_phase_content(str(phase))}, ensure_ascii=False)}\n\n"
                                    )
                                yield f"data: {json.dumps({'type': 'status', 'phase': phase})}\n\n"

            _graph_loop_ms = int((time.monotonic() - stream_t0) * 1000)
            record_assistant_step(
                "case",
                "stream.graph_loop_completed",
                metadata={
                    "case_id": case_id,
                    "graph_mode": mode,
                    "since_stream_start_ms": _graph_loop_ms,
                    "text_streamed_live": text_streamed_live,
                    "response_chars_so_far": len(full_response or ""),
                },
                latency_ms=_graph_loop_ms,
            )

            with assistant_step_span(
                "case",
                "stream.finalize_response",
                metadata={"case_id": case_id, "graph_mode": mode},
            ) as finalize_out:
                if answer_after_reasoning_buffer:
                    full_response += answer_after_reasoning_buffer
                    sse = _format_text_delta_sse(turn_emitter, answer_after_reasoning_buffer)
                    if sse:
                        yield sse
                    answer_after_reasoning_buffer = ""

                if not full_response:
                    full_response = "Не удалось получить ответ. Попробуйте переформулировать вопрос."
                    sse = _format_text_delta_sse(turn_emitter, full_response)
                    if sse:
                        yield sse

                if citations:
                    _cj_end = json.dumps(citations, ensure_ascii=False, default=str)
                    if _cj_end != last_citations_json:
                        last_citations_json = _cj_end
                        yield f"data: {json.dumps({'type': 'citations', 'citations': citations}, ensure_ascii=False)}\n\n"

                if answer_blocks:
                    from app.services.chat.events import SSESerializer

                    sse_ab = SSESerializer.answer_blocks(answer_blocks)
                    if sse_ab:
                        yield sse_ab

                finalize_out["response_chars"] = len(full_response or "")
                finalize_out["citations_count"] = len(citations or [])

            if persist_history:
                with assistant_step_span(
                    "case",
                    "stream.save_message",
                    metadata={"case_id": case_id, "session_id": session_id},
                ) as save_out:
                    self._save_assistant_message(
                        case_id,
                        full_response,
                        session_id,
                        citations,
                        answer_blocks=answer_blocks,
                        turn_state=outbound_turn_state_snapshot,
                        persist_ctx=stream_turn_persist_ctx,
                    )
                    save_out["response_chars"] = len(full_response or "")

            if turn_emitter:
                yield turn_emitter.turn_completed(
                    answer=full_response or "",
                    citations_count=len(citations or []),
                    structured_edits_count=turn_emitter.last_patch_count,
                )

            if editor_latency is not None:
                from app.services.observability.editor_latency_trace import (
                    editor_latency_verbose,
                    emit_editor_turn_summary,
                    format_latency_debug_sse,
                )

                editor_latency.set_stage(
                    "astream",
                    astream_wall_ms=int((time.monotonic() - stream_t0) * 1000),
                    response_chars=len(full_response or ""),
                    text_streamed_live=text_streamed_live,
                )
                emit_editor_turn_summary(editor_latency)
                if editor_latency_verbose():
                    yield f"data: {format_latency_debug_sse(editor_latency)}\n\n"

            with assistant_step_span("case", "stream.emit_finish", metadata={"case_id": case_id}) as fin_out:
                yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'stop'})}\n\n"
                fin_out["response_chars"] = len(full_response or "")

            logger.info(f"[ChatGraphService] Stream completed: {len(full_response)} chars")

        except Exception as e:
            logger.error(f"[ChatGraphService] Stream error: {e}", exc_info=True)
            error_msg = f"Ошибка: {str(e)}"
            yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'error', 'error': str(e)})}\n\n"

            # Сохраняем ошибку как ответ (если не обрабатывается внешним оркестратором)
            if persist_history:
                self._save_assistant_message(case_id, error_msg, session_id)
        finally:
            if astream_parent_token is not None:
                reset_trace_span_parent(astream_parent_token)
            if astream_span:
                try:
                    _out: Dict[str, Any] = {
                        "astream_wall_ms": int((time.monotonic() - stream_t0) * 1000),
                        "response_chars": len(full_response or ""),
                        "citations_count": len(citations or []),
                    }
                    if editor_latency is not None:
                        _out["editor_latency"] = editor_latency.to_dict()
                    astream_span.update(output=_out)
                except Exception:
                    logger.debug("case_chat_graph_astream span update failed", exc_info=True)
                try:
                    astream_span.end()
                except Exception:
                    logger.debug("case_chat_graph_astream span end failed", exc_info=True)
    
    async def stream_response_with_tokens(
        self,
        case_id: str,
        question: str,
        user: User,
        deep_think: bool = False,
        legal_research: bool = False,
        court_practice: bool = False,
        draft_mode: bool = False,
        document_context: str = None,
        document_id: str = None,
        selected_text: str = None,
        existing_messages: List[BaseMessage] = None,
        template_system_id: str = None,
        template_file_id: str = None,
        template_file_content: str = None,
        attached_file_ids: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming ответ с токенами через astream_events.
        
        Обеспечивает real-time streaming токенов по мере их генерации LLM.
        Используется для улучшенного UX когда важна скорость отображения.
        
        Args:
            case_id: ID дела
            question: Вопрос пользователя
            user: Текущий пользователь
            deep_think: Режим глубокого мышления
            legal_research: Режим справочного правового поиска
            draft_mode: Режим создания документа
            document_context: Контекст документа
            document_id: ID документа
            selected_text: Выделенный текст
            existing_messages: Существующие сообщения
        
        Yields:
            JSON строки в формате assistant-ui SSE с токенами
        """
        logger.info(f"[ChatGraphService] Starting token stream for case {case_id}")
        
        # Проверяем доступ к делу
        case = self._require_case_for_user(case_id, user)
        
        if not case:
            yield create_finish_event("error", "Дело не найдено")
            return

        template_context, template_label, template_key = self._resolve_template_context(
            question=question,
            draft_mode=draft_mode,
            document_context=document_context,
            template_system_id=template_system_id,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
        )
        
        # Получаем session_id (legacy stream path — mint when client did not pass one)
        session_id = self._resolve_case_session(None)
        
        # Сохраняем сообщение пользователя
        self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(deep_think, legal_research, draft_mode)
        
        # Получаем граф
        graph, _ = self._get_or_create_graph()
        
        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        thread_id = self._get_or_create_thread_id(case_id, session_id)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _case_graph_recursion_limit()
        }

        canonical_messages = self._resolve_case_canonical_messages(
            case_id,
            session_id,
            question,
            hydrate_from_db=True,
        )
        
        # Загружаем существующее состояние из checkpoint для продолжения диалога
        try:
            existing_state = await graph.aget_state(config)
            if existing_state and existing_state.values:
                # Продолжаем диалог - используем существующее состояние
                current_state = dict(existing_state.values)
                # Инициализируем поля HITL если их нет (для совместимости со старыми checkpoint)
                if "draft_plan" not in current_state:
                    current_state["draft_plan"] = None
                if "draft_approved" not in current_state:
                    current_state["draft_approved"] = False
                if "waiting_for_approval" not in current_state:
                    current_state["waiting_for_approval"] = False
                if "template_context" not in current_state:
                    current_state["template_context"] = ""
                if "template_label" not in current_state:
                    current_state["template_label"] = None
                if "template_key" not in current_state:
                    current_state["template_key"] = None
                if "template_system_id" not in current_state:
                    current_state["template_system_id"] = None
                if "template_field_catalog" not in current_state:
                    current_state["template_field_catalog"] = None
                if attached_file_ids is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_file_ids if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                if canonical_messages is not None:
                    self._apply_canonical_messages(current_state, canonical_messages)
                else:
                    current_messages = current_state.get("messages", [])
                    current_messages.append(HumanMessage(content=question))
                    current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = legal_research or mode == "garant"
                current_state["enable_court_practice"] = bool(court_practice)
                if document_context:
                    current_state["document_context"] = document_context
                    current_state["editor_mode"] = True
                if document_id:
                    current_state["document_id"] = document_id
                if selected_text:
                    current_state["selected_text"] = selected_text
                current_state["template_context"] = template_context or ""
                current_state["template_label"] = template_label
                # Очищаем предыдущий ответ для нового запроса
                current_state["response"] = None
                current_state["rag_context"] = None
                current_state["garant_context"] = None
                current_state["thinking_steps"] = None
                current_state["structured_edits"] = None
                current_state["answer_blocks"] = None
                self._reset_draft_hitl_for_turn(current_state, mode)
                initial_state = current_state
                logger.info(f"[ChatGraphService] Continuing dialog from checkpoint (token stream), thread_id: {thread_id}")
            else:
                # Новый диалог - создаём начальное состояние
                initial_state = create_initial_chat_state(
                    case_id=case_id,
                    user_id=str(user.id),
                    question=question,
                    mode=mode,
                    enable_garant=legal_research or mode == "garant",
                    enable_court_practice=bool(court_practice),
                    enable_citations=True,
                    document_context=document_context,
                    document_id=document_id,
                    selected_text=selected_text,
                    existing_messages=existing_messages,
                    prebuilt_messages=canonical_messages,
                    template_context=template_context or None,
                    template_label=template_label,
                    template_key=template_key,
                    template_system_id=template_system_id,
                    attached_file_ids=attached_file_ids,
                    legal_research=legal_research,
                    court_practice=court_practice,
                )
                logger.info(f"[ChatGraphService] Starting new dialog (token stream), thread_id: {thread_id}")
        except Exception as e:
            # Если не удалось загрузить состояние, создаём новое
            logger.warning(f"[ChatGraphService] Failed to load state from checkpoint (token stream): {e}, creating new state")
            initial_state = create_initial_chat_state(
                case_id=case_id,
                user_id=str(user.id),
                question=question,
                mode=mode,
                enable_garant=legal_research or mode == "garant",
                enable_court_practice=bool(court_practice),
                enable_citations=True,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                existing_messages=existing_messages,
                prebuilt_messages=canonical_messages,
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_file_ids,
                legal_research=legal_research,
                court_practice=court_practice,
            )
        
        full_response = ""
        citations = []
        answer_blocks: Optional[List[Dict[str, Any]]] = None

        try:
            # Streaming токенов через astream_events
            async for event in stream_tokens(graph, initial_state, config):
                if event.type == "token" and event.token:
                    full_response += event.token
                    yield create_text_delta_event(event.token)
                
                elif event.type == "complete":
                    break
                
                elif event.type == "error":
                    error = event.data.get("error", "Unknown error") if event.data else "Unknown error"
                    yield create_finish_event("error", error)
                    return
            
            # Если ответ пустой, пробуем получить из состояния
            if not full_response:
                # Fallback: получаем финальное состояние
                final_state = await graph.aget_state(config)
                if final_state and final_state.values:
                    full_response = final_state.values.get("response", "")
                    citations = final_state.values.get("citations", [])
                    answer_blocks = final_state.values.get("answer_blocks")

                    if full_response:
                        yield create_text_delta_event(full_response)
            
            if not full_response:
                full_response = "Не удалось получить ответ. Попробуйте переформулировать вопрос."
                yield create_text_delta_event(full_response)
            
            # Отправляем citations
            if citations:
                yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

            if not answer_blocks:
                final_state2 = await graph.aget_state(config)
                if final_state2 and final_state2.values:
                    answer_blocks = final_state2.values.get("answer_blocks")

            if answer_blocks:
                from app.services.chat.events import SSESerializer

                sse_ab = SSESerializer.answer_blocks(answer_blocks)
                if sse_ab:
                    yield sse_ab
            
            # Сохраняем ответ
            self._save_assistant_message(
                case_id, full_response, session_id, citations, answer_blocks=answer_blocks
            )
            
            yield create_finish_event("stop")
            
            logger.info(f"[ChatGraphService] Token stream completed: {len(full_response)} chars")
            
        except Exception as e:
            logger.error(f"[ChatGraphService] Token stream error: {e}", exc_info=True)
            error_msg = f"Ошибка: {str(e)}"
            yield create_text_delta_event(error_msg)
            yield create_finish_event("error", str(e))
            self._save_assistant_message(case_id, error_msg, session_id)
    
    async def stream_with_mode(
        self,
        case_id: str,
        question: str,
        user: User,
        stream_mode: StreamMode = StreamMode.UPDATES,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Streaming с указанным режимом.
        
        Args:
            case_id: ID дела
            question: Вопрос пользователя
            user: Текущий пользователь
            stream_mode: Режим streaming
            **kwargs: Дополнительные параметры
        
        Yields:
            JSON строки в формате SSE
        """
        logger.info(f"[ChatGraphService] Starting stream with mode {stream_mode} for case {case_id}")
        
        # Проверяем доступ
        case = self._require_case_for_user(case_id, user)
        
        if not case:
            yield format_sse_event(StreamEvent(type="error", data={"error": "Дело не найдено"}))
            return

        template_context, template_label, template_key = self._resolve_template_context(
            question=question,
            draft_mode=bool(kwargs.get("draft_mode")),
            document_context=kwargs.get("document_context"),
            template_system_id=kwargs.get("template_system_id"),
            template_file_content=kwargs.get("template_file_content"),
            template_file_id=kwargs.get("template_file_id"),
        )
        attached_kw = kwargs.get("attached_file_ids")
        
        # Получаем session_id
        session_id = self._resolve_case_session(kwargs.get("session_id"))
        self._save_user_message(case_id, question, session_id)

        # Определяем режим
        mode = self._determine_mode(
            kwargs.get("deep_think", False),
            kwargs.get("legal_research", False),
            kwargs.get("draft_mode", False),
        )
        
        graph, _ = self._get_or_create_graph()
        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        thread_id = self._get_or_create_thread_id(case_id, session_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": _case_graph_recursion_limit()}

        is_editor_chat = bool(kwargs.get("document_context")) and not bool(kwargs.get("draft_mode"))
        canonical_messages = self._resolve_case_canonical_messages(
            case_id,
            session_id,
            question,
            hydrate_from_db=not is_editor_chat,
        )
        
        # Загружаем существующее состояние из checkpoint для продолжения диалога
        try:
            existing_state = await graph.aget_state(config)
            if existing_state and existing_state.values:
                # Продолжаем диалог - используем существующее состояние
                current_state = dict(existing_state.values)
                # Инициализируем поля HITL если их нет (для совместимости со старыми checkpoint)
                if "draft_plan" not in current_state:
                    current_state["draft_plan"] = None
                if "draft_approved" not in current_state:
                    current_state["draft_approved"] = False
                if "waiting_for_approval" not in current_state:
                    current_state["waiting_for_approval"] = False
                if "template_context" not in current_state:
                    current_state["template_context"] = ""
                if "template_label" not in current_state:
                    current_state["template_label"] = None
                if "template_key" not in current_state:
                    current_state["template_key"] = None
                if "template_system_id" not in current_state:
                    current_state["template_system_id"] = None
                if "template_field_catalog" not in current_state:
                    current_state["template_field_catalog"] = None
                if attached_kw is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_kw if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                if canonical_messages is not None:
                    self._apply_canonical_messages(current_state, canonical_messages)
                else:
                    current_messages = current_state.get("messages", [])
                    current_messages.append(HumanMessage(content=question))
                    current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = kwargs.get("legal_research", False) or mode == "garant"
                current_state["enable_court_practice"] = bool(kwargs.get("court_practice", False))
                if kwargs.get("document_context"):
                    current_state["document_context"] = kwargs.get("document_context")
                    current_state["editor_mode"] = True
                if kwargs.get("document_id"):
                    current_state["document_id"] = kwargs.get("document_id")
                if kwargs.get("selected_text"):
                    current_state["selected_text"] = kwargs.get("selected_text")
                current_state["template_context"] = template_context or ""
                current_state["template_label"] = template_label
                # Очищаем предыдущий ответ для нового запроса
                current_state["response"] = None
                current_state["rag_context"] = None
                current_state["garant_context"] = None
                current_state["thinking_steps"] = None
                current_state["structured_edits"] = None
                current_state["answer_blocks"] = None
                self._reset_draft_hitl_for_turn(current_state, mode)
                initial_state = current_state
                logger.info(f"[ChatGraphService] Continuing dialog from checkpoint (stream_with_mode), thread_id: {thread_id}")
            else:
                # Новый диалог - создаём начальное состояние
                initial_state = create_initial_chat_state(
                    case_id=case_id,
                    user_id=str(user.id),
                    question=question,
                    mode=mode,
                    enable_garant=kwargs.get("legal_research", False) or mode == "garant",
                    enable_court_practice=bool(kwargs.get("court_practice", False)),
                    enable_citations=True,
                    document_context=kwargs.get("document_context"),
                    document_id=kwargs.get("document_id"),
                    selected_text=kwargs.get("selected_text"),
                    existing_messages=kwargs.get("existing_messages"),
                    prebuilt_messages=canonical_messages,
                    template_context=template_context or None,
                    template_label=template_label,
                    attached_file_ids=attached_kw,
                    legal_research=bool(kwargs.get("legal_research", False)),
                    court_practice=bool(kwargs.get("court_practice", False)),
                )
                logger.info(f"[ChatGraphService] Starting new dialog (stream_with_mode), thread_id: {thread_id}")
        except Exception as e:
            # Если не удалось загрузить состояние, создаём новое
            logger.warning(f"[ChatGraphService] Failed to load state from checkpoint (stream_with_mode): {e}, creating new state")
            initial_state = create_initial_chat_state(
                case_id=case_id,
                user_id=str(user.id),
                question=question,
                mode=mode,
                enable_garant=kwargs.get("legal_research", False) or mode == "garant",
                enable_court_practice=bool(kwargs.get("court_practice", False)),
                enable_citations=True,
                document_context=kwargs.get("document_context"),
                document_id=kwargs.get("document_id"),
                selected_text=kwargs.get("selected_text"),
                existing_messages=kwargs.get("existing_messages"),
                prebuilt_messages=canonical_messages,
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_kw,
                legal_research=bool(kwargs.get("legal_research", False)),
                court_practice=bool(kwargs.get("court_practice", False)),
            )
        
        full_response = ""
        citations = []
        answer_blocks: Optional[List[Dict[str, Any]]] = None

        try:
            async for event in stream_graph_with_mode(graph, initial_state, config, stream_mode):
                yield format_sse_event(event)
                
                # Собираем ответ для сохранения
                if event.type == "response" and event.message:
                    full_response = event.message
                elif event.type == "message" and event.message:
                    full_response = event.message
                elif event.type == "citations" and event.data:
                    citations = event.data.get("citations", [])
                elif event.type == "answer_blocks" and event.data:
                    answer_blocks = event.data.get("blocks")

            if not answer_blocks:
                fs = await graph.aget_state(config)
                if fs and fs.values:
                    answer_blocks = fs.values.get("answer_blocks")

            # Сохраняем ответ
            if full_response:
                self._save_assistant_message(
                    case_id, full_response, session_id, citations, answer_blocks=answer_blocks
                )
            
        except Exception as e:
            logger.error(f"[ChatGraphService] Stream error: {e}", exc_info=True)
            yield format_sse_event(StreamEvent(type="error", data={"error": str(e)}))
    


# Глобальный экземпляр для переиспользования
_chat_graph_service: Optional[ChatGraphService] = None


def get_chat_graph_service(
    db: Session,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> ChatGraphService:
    """
    Получить экземпляр ChatGraphService.
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        ChatGraphService instance
    """
    global _chat_graph_service
    
    # Создаём новый экземпляр с текущим db session
    # (db session не должен переиспользоваться между запросами)
    return ChatGraphService(
        db=db,
        rag_service=rag_service or RAGService(),
        document_processor=document_processor or DocumentProcessor()
    )



