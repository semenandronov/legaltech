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
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.graphs.chat_graph import (
    create_chat_graph,
    create_initial_chat_state,
    ChatGraphState
)
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
    trace_contract_event,
    trace_span,
    normalize_observability_metadata,
)
import logging
import json
import uuid
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

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


class ChatGraphService:
    """
    Сервис для работы с ChatGraph.
    
    Обеспечивает:
    - Создание и кэширование графа
    - Streaming ответов с форматированием для assistant-ui
    - Сохранение сообщений в БД
    """
    
    _graph_instance = None
    
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
    
    def _get_or_create_graph(self):
        """Получить или создать экземпляр графа."""
        if ChatGraphService._graph_instance is None:
            ChatGraphService._graph_instance = create_chat_graph(
                db=self.db,
                rag_service=self.rag_service,
                document_processor=self.document_processor,
                use_checkpointing=True
            )
            logger.info("[ChatGraphService] Created new ChatGraph instance")
        return ChatGraphService._graph_instance
    
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
    
    def _get_or_create_session(self, case_id: str) -> str:
        """Получить или создать session_id для чата."""
        try:
            last_message = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            if last_message and last_message.created_at:
                time_diff = datetime.utcnow() - last_message.created_at
                if time_diff < timedelta(minutes=30) and last_message.session_id:
                    return last_message.session_id
            
            return str(uuid.uuid4())
        except Exception as e:
            logger.warning(f"[ChatGraphService] Error getting session: {e}")
            return str(uuid.uuid4())
    
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
    def _reset_draft_hitl_for_turn(current_state: dict, mode: str) -> None:
        """
        Сброс устаревшего LangGraph-состояния черновика между запросами.

        Если не ждём подтверждения плана — очищаем draft_plan/draft_approved, иначе
        маршрут draft_execute + interrupt_before=['draft'] даёт пустой ответ без плана.
        Если ждём «одобряю» — сохраняем план для уточнений в том же чате.
        """
        if mode == "draft":
            if current_state.get("waiting_for_approval"):
                # Новый ход в чате при показанном плане: уточнения/правки — не считаем документ одобренным,
                # пока не пришёл resume или явная короткая команда (обрабатывается оркестратором).
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
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id,
        ).first()
        if not case:
            return {"ok": False, "error": "case_not_found"}

        history = ChatHistoryService(self.db)
        resolved_session = session_id or history.get_or_create_session(case_id)

        t0 = time.monotonic()
        graph = self._get_or_create_graph()
        thread_id = self._get_or_create_thread_id(case_id, resolved_session)
        graph_run_config: Dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25,
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
    ) -> str:
        """Сохранить ответ ассистента в БД."""
        message_id = str(uuid.uuid4())
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
                session_id=session_id
            )
            self.db.add(assistant_message)
            self.db.commit()
            logger.info(f"[ChatGraphService] Saved assistant message: {message_id}")
        except Exception as e:
            self.db.rollback()
            logger.warning(f"[ChatGraphService] Failed to save assistant message: {e}")
        return message_id
    
    async def stream_response(
        self,
        case_id: str,
        question: str,
        user: User,
        deep_think: bool = False,
        legal_research: bool = False,
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
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id
        ).first()
        
        if not case:
            yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
            return

        from app.services.draft_template_context import resolve_draft_template_context

        template_context, template_label = resolve_draft_template_context(
            self.db,
            template_system_id=template_system_id,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
            user_question=question,
        )
        
        # Получаем session_id
        session_id = session_id or self._get_or_create_session(case_id)
        
        # Сохраняем сообщение пользователя (если не обрабатывается внешним оркестратором)
        if persist_history:
            self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(deep_think, legal_research, draft_mode)

        trace_ctx = get_active_trace_context()
        prep_span = trace_span(
            trace_ctx,
            name="case_chat_graph_prepare",
            metadata={"case_id": case_id, "graph_mode": mode, "persist_history": persist_history},
        )
        prep_started = time.monotonic()
        checkpoint_dialog_continued = False
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        thread_id = self._get_or_create_thread_id(case_id, session_id)
        graph_run_config: Dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25,
        }
        if langfuse_enabled():
            _lc = get_langchain_callbacks(
                session_id=session_id,
                user_id=str(user.id),
                tags=["case_assistant", "chat_graph"],
            )
            if _lc:
                graph_run_config["callbacks"] = _lc
        
        # Загружаем существующее состояние из checkpoint для продолжения диалога
        try:
            existing_state = await graph.aget_state(graph_run_config)
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
                if attached_file_ids is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_file_ids if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                # Добавляем новое сообщение пользователя
                current_messages = current_state.get("messages", [])
                current_messages.append(HumanMessage(content=question))
                current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = legal_research or mode == "garant"
                # Политика/бюджет выполнения (обновляем на каждый turn)
                if task_type is not None:
                    current_state["task_type"] = task_type
                if depth_tier is not None:
                    current_state["depth_tier"] = depth_tier
                if budget_profile is not None:
                    current_state["budget_profile"] = budget_profile
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
                # Очищаем предыдущий ответ для нового запроса
                current_state["response"] = None
                current_state["rag_context"] = None
                current_state["garant_context"] = None
                current_state["thinking_steps"] = None
                current_state["answer_blocks"] = None
                self._reset_draft_hitl_for_turn(current_state, mode)
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
                    enable_citations=True,
                    document_context=document_context,
                    document_id=document_id,
                    selected_text=selected_text,
                    existing_messages=existing_messages,
                    editor_mode_hint=editor_mode_hint,
                    template_context=template_context or None,
                    template_label=template_label,
                    attached_file_ids=attached_file_ids,
                    task_type=task_type,
                    depth_tier=depth_tier,
                    budget_profile=budget_profile,
                    corpus_size=corpus_size,
                    clarification_needed=clarification_needed,
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
                enable_citations=True,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                existing_messages=existing_messages,
                editor_mode_hint=editor_mode_hint,
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_file_ids,
                task_type=task_type,
                depth_tier=depth_tier,
                budget_profile=budget_profile,
                corpus_size=corpus_size,
                clarification_needed=clarification_needed,
            )

        prep_ms = int((time.monotonic() - prep_started) * 1000)
        if prep_span:
            try:
                prep_span.update(
                    output={
                        "prep_ms": prep_ms,
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
        stream_reasoning_ui = bool(getattr(config, "CASE_ASSISTANT_STREAM_REASONING_UI", False))

        astream_span = trace_span(
            trace_ctx,
            name="case_chat_graph_astream",
            metadata={"case_id": case_id, "graph_mode": mode},
        )
        stream_t0 = time.monotonic()
        last_graph_update_t = stream_t0

        try:
            # Token-level streaming: используем stream_mode=["messages", "updates"]
            # "messages" даёт токены по мере генерации LLM
            # "updates" даёт метаданные (citations, structured_edits и т.д.)
            try:
                async for stream_mode_type, chunk in graph.astream(
                    initial_state, config=graph_run_config,
                    stream_mode=["messages", "updates"]
                ):
                    if stream_mode_type == "messages":
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
                            # Пока идёт reasoning в том же потоке, ответ копим; первый чистый answer-chunk — отдаём весь накопленный текст сразу.
                            if native_reasoning_phase and r_delta:
                                answer_after_reasoning_buffer += token
                            elif native_reasoning_phase and not r_delta:
                                block = answer_after_reasoning_buffer + token
                                answer_after_reasoning_buffer = ""
                                native_reasoning_phase = False
                                full_response += block
                                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': block}, ensure_ascii=False)}\n\n"
                            else:
                                full_response += token
                                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': token}, ensure_ascii=False)}\n\n"

                    elif stream_mode_type == "updates":
                        # Node-level updates для метаданных
                        if isinstance(chunk, dict):
                            for node_name, node_data in chunk.items():
                                if not isinstance(node_data, dict):
                                    continue
                                _now = time.monotonic()
                                _tctx = get_active_trace_context()
                                if _tctx:
                                    trace_contract_event(
                                        _tctx,
                                        name="graph_node_completed",
                                        metadata=normalize_observability_metadata(
                                            {
                                                "graph_node": str(node_name),
                                                "since_stream_start_ms": int((_now - stream_t0) * 1000),
                                                "since_prev_graph_update_ms": int(
                                                    (_now - last_graph_update_t) * 1000
                                                ),
                                                "state_keys_preview": list(node_data.keys())[:25],
                                            },
                                            step_name="graph_node_completed",
                                            status="success",
                                        ),
                                    )
                                last_graph_update_t = _now

                                if node_name == "generate_response" and node_data.get("response") is not None:
                                    answer_after_reasoning_buffer = ""
                                    native_reasoning_phase = False

                                # Обрабатываем response: финальный текст узла — источник истины (после sanitize / цитат).
                                response = node_data.get("response")
                                if isinstance(response, str) and response != full_response:
                                    if full_response:
                                        yield f"data: {json.dumps({'type': 'content_sync', 'content': response}, ensure_ascii=False)}\n\n"
                                    else:
                                        yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': response})}\n\n"
                                    full_response = response

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

                                # Обрабатываем structured_edits (editor mode)
                                structured_edits = node_data.get("structured_edits")
                                if structured_edits:
                                    from app.services.chat.events import SSESerializer
                                    yield SSESerializer.structured_edits(structured_edits)
                                    logger.info(f"[ChatGraphService] Sent {len(structured_edits)} structured edits")

                                # Обрабатываем current_phase для прогресса (в UI — только при stream_reasoning_ui)
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
                            _tctx_fb = get_active_trace_context()
                            if _tctx_fb:
                                trace_contract_event(
                                    _tctx_fb,
                                    name="graph_node_completed",
                                    metadata=normalize_observability_metadata(
                                        {
                                            "graph_node": str(node_name),
                                            "since_stream_start_ms": int((_now_fb - stream_t0) * 1000),
                                            "since_prev_graph_update_ms": int(
                                                (_now_fb - last_graph_update_t) * 1000
                                            ),
                                            "stream_fallback": "single_mode_updates",
                                        },
                                        step_name="graph_node_completed",
                                        status="success",
                                    ),
                                )
                            last_graph_update_t = _now_fb

                            # Обрабатываем messages
                            messages = node_data.get("messages", [])
                            for msg in messages:
                                if isinstance(msg, AIMessage) and msg.content:
                                    content = msg.content
                                    if content != full_response:
                                        if full_response and content.startswith(full_response):
                                            delta = content[len(full_response):]
                                        else:
                                            delta = content
                                        if delta:
                                            yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': delta})}\n\n"
                                        full_response = content

                            response = node_data.get("response")
                            if response and response != full_response:
                                if full_response and response.startswith(full_response):
                                    delta = response[len(full_response):]
                                else:
                                    delta = response
                                if delta:
                                    yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': delta})}\n\n"
                                full_response = response

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
                                from app.services.chat.events import SSESerializer
                                yield SSESerializer.structured_edits(structured_edits)

                            phase = node_data.get("current_phase")
                            if phase:
                                if stream_reasoning_ui:
                                    yield (
                                        f"data: {json.dumps({'type': 'reasoning', 'phase': str(phase), 'step': 1, 'totalSteps': 1, 'content': _reasoning_phase_content(str(phase))}, ensure_ascii=False)}\n\n"
                                    )
                                yield f"data: {json.dumps({'type': 'status', 'phase': phase})}\n\n"

            if answer_after_reasoning_buffer:
                full_response += answer_after_reasoning_buffer
                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': answer_after_reasoning_buffer}, ensure_ascii=False)}\n\n"
                answer_after_reasoning_buffer = ""

            # Если ответ пустой, отправляем fallback
            if not full_response:
                full_response = "Не удалось получить ответ. Попробуйте переформулировать вопрос."
                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': full_response})}\n\n"

            # Догоняем citations, если граф не прислал diff по пути (редко)
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

            # Сохраняем ответ ассистента (если не обрабатывается внешним оркестратором)
            if persist_history:
                self._save_assistant_message(
                    case_id, full_response, session_id, citations, answer_blocks=answer_blocks
                )

            # Отправляем финальное событие
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'stop'})}\n\n"

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
            if astream_span:
                try:
                    astream_span.update(
                        output={
                            "astream_wall_ms": int((time.monotonic() - stream_t0) * 1000),
                            "response_chars": len(full_response or ""),
                            "citations_count": len(citations or []),
                        }
                    )
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
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id
        ).first()
        
        if not case:
            yield create_finish_event("error", "Дело не найдено")
            return

        from app.services.draft_template_context import resolve_draft_template_context

        template_context, template_label = resolve_draft_template_context(
            self.db,
            template_system_id=template_system_id,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
            user_question=question,
        )
        
        # Получаем session_id
        session_id = self._get_or_create_session(case_id)
        
        # Сохраняем сообщение пользователя
        self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(deep_think, legal_research, draft_mode)
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        thread_id = self._get_or_create_thread_id(case_id, session_id)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25
        }
        
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
                if attached_file_ids is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_file_ids if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                # Добавляем новое сообщение пользователя
                current_messages = current_state.get("messages", [])
                current_messages.append(HumanMessage(content=question))
                current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = legal_research or mode == "garant"
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
                    enable_citations=True,
                    document_context=document_context,
                    document_id=document_id,
                    selected_text=selected_text,
                    existing_messages=existing_messages,
                    template_context=template_context or None,
                    template_label=template_label,
                    attached_file_ids=attached_file_ids,
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
                enable_citations=True,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                existing_messages=existing_messages,
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_file_ids,
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
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id
        ).first()
        
        if not case:
            yield format_sse_event(StreamEvent(type="error", data={"error": "Дело не найдено"}))
            return

        from app.services.draft_template_context import resolve_draft_template_context

        template_context, template_label = resolve_draft_template_context(
            self.db,
            template_system_id=kwargs.get("template_system_id"),
            template_file_content=kwargs.get("template_file_content"),
            template_file_id=kwargs.get("template_file_id"),
            user_question=question,
        )
        attached_kw = kwargs.get("attached_file_ids")
        
        # Получаем session_id
        session_id = self._get_or_create_session(case_id)
        self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(
            kwargs.get("deep_think", False),
            kwargs.get("legal_research", False),
            kwargs.get("draft_mode", False)
        )
        
        graph = self._get_or_create_graph()
        # Получаем или создаём thread_id для checkpointing (переиспользуем session_id)
        thread_id = self._get_or_create_thread_id(case_id, session_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
        
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
                if attached_kw is not None:
                    current_state["attached_file_ids"] = [str(x) for x in attached_kw if x] or None
                elif "attached_file_ids" not in current_state:
                    current_state["attached_file_ids"] = None
                # Добавляем новое сообщение пользователя
                current_messages = current_state.get("messages", [])
                current_messages.append(HumanMessage(content=question))
                current_state["messages"] = current_messages
                # Обновляем вопрос и режим для текущего запроса
                current_state["question"] = question
                current_state["mode"] = mode
                current_state["enable_garant"] = kwargs.get("legal_research", False) or mode == "garant"
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
                    enable_citations=True,
                    document_context=kwargs.get("document_context"),
                    document_id=kwargs.get("document_id"),
                    selected_text=kwargs.get("selected_text"),
                    existing_messages=kwargs.get("existing_messages"),
                    template_context=template_context or None,
                    template_label=template_label,
                    attached_file_ids=attached_kw,
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
                enable_citations=True,
                document_context=kwargs.get("document_context"),
                document_id=kwargs.get("document_id"),
                selected_text=kwargs.get("selected_text"),
                existing_messages=kwargs.get("existing_messages"),
                template_context=template_context or None,
                template_label=template_label,
                attached_file_ids=attached_kw,
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
    
    async def resume_draft(
        self,
        case_id: str,
        thread_id: str,
        approved: bool = True,
        user: User = None
    ) -> AsyncGenerator[str, None]:
        """
        Возобновить выполнение draft после подтверждения/отмены пользователем.
        
        Используется для HITL - когда граф прерывается перед созданием документа,
        пользователь может подтвердить или отменить операцию.
        
        Args:
            case_id: ID дела
            thread_id: ID потока (из предыдущего запроса)
            approved: Подтверждено ли создание документа
            user: Текущий пользователь (для проверки доступа)
        
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        logger.info(f"[ChatGraphService] Resuming draft for thread {thread_id}, approved: {approved}")
        
        # Проверяем доступ к делу
        if user:
            case = self.db.query(Case).filter(
                Case.id == case_id,
                Case.user_id == user.id
            ).first()
            if not case:
                yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
                return
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25
        }
        
        try:
            from app.services.langchain_agents.utils.state_editing import update_state

            # Жёстко фиксируем состояние перед resume:
            # если есть draft_plan, считаем, что остаёмся в draft flow и продолжаем исполнение.
            current_state = await graph.aget_state(config)
            has_plan = bool(current_state and current_state.values and current_state.values.get("draft_plan"))
            waiting_for_approval = bool(
                current_state and current_state.values and current_state.values.get("waiting_for_approval")
            )
            if not (has_plan and waiting_for_approval):
                # Нельзя «проскочить» этап плана: approval/resume только после plan_ready.
                yield (
                    f"data: {json.dumps({'type': 'error', 'error': 'plan_not_ready'}, ensure_ascii=False)}\n\n"
                )
                yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'error'}, ensure_ascii=False)}\n\n"
                return
            if has_plan:
                await update_state(
                    graph,
                    thread_id,
                    {
                        "mode": "draft",
                        "draft_approved": approved,
                        "waiting_for_approval": True,
                    },
                )
            else:
                await update_state(graph, thread_id, {"draft_approved": approved})
            
            # Создаём Command для resume
            resume_command = Command(resume={"draft_approved": approved})
            
            # Продолжаем выполнение
            full_response = ""
            citations = []
            document_created = None
            
            async for chunk in graph.astream(resume_command, config=config):
                if isinstance(chunk, dict):
                    for node_name, node_data in chunk.items():
                        if not isinstance(node_data, dict):
                            continue
                        
                        # Обрабатываем response
                        response = node_data.get("response")
                        if response:
                            if response != full_response:
                                if full_response and response.startswith(full_response):
                                    delta = response[len(full_response):]
                                else:
                                    delta = response
                                
                                if delta:
                                    yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': delta})}\n\n"
                                
                                full_response = response
                        
                        # Обрабатываем document_created
                        doc_created = node_data.get("document_created")
                        if doc_created:
                            document_created = doc_created
                            yield f"data: {json.dumps({'type': 'document-card', 'data': doc_created})}\n\n"
                        
                        # Обрабатываем citations
                        node_citations = node_data.get("citations")
                        if node_citations:
                            citations = node_citations
            
            # Отправляем citations если есть
            if citations:
                yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"
            
            # Отправляем финальное событие
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'stop'})}\n\n"
            
            logger.info(f"[ChatGraphService] Draft resume completed: {len(full_response)} chars")
            
        except Exception as e:
            logger.error(f"[ChatGraphService] Draft resume error: {e}", exc_info=True)
            error_msg = f"Ошибка при возобновлении: {str(e)}"
            yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'error', 'error': str(e)})}\n\n"


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



