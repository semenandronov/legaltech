"""
Chat Orchestrator — оркестратор case-assistant запросов.

Execution branches:
- Draft hybrid workflow (draft_mode=True) — пайплайн + bounded gap retrieval
- Editor workflow через EditorHandler (document_context!=None)
- Strict mixed path (СПРАВОЧНИК) через RAG+legal_research
- Deterministic fast case-only path (default mode)
- Clarification path для недостаточного контекста
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from dataclasses import dataclass
from sqlalchemy.orm import Session
import logging
import re
import json
import threading

from app.services.chat.events import SSESerializer, SSEEvent
from app.services.chat.classifier import RequestClassifier, ClassificationResult
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.entity_fact_pipeline import EntityFactPipeline
from app.services.chat.citation_payload import (
    build_retrieval_citations,
    expand_dc_markers_to_cite_zw,
    fetch_original_text_map_for_case,
    repair_citation_brackets,
)
from app.services.chat.response_sanitize import strip_llm_answer_leaks
from app.services.chat.tabular_citation_policy import filter_docs_for_tabular_citations
from app.services.chat.metrics import get_metrics
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.legal_quality_gates import LegalQualityGates
from app.services.rag_service import RAGService, get_rag_service
from app.services.document_processor import DocumentProcessor, get_document_processor
from app.models.case import Case, File as CaseFile
from app.models.user import User
from app.utils.authorization import require_case_access
from fastapi import HTTPException
from app.services.langchain_agents.chat_graph_service import get_chat_graph_service
from app.services.observability.assistant_pipeline_langfuse_tracing import (
    assistant_step_span,
)
from app.services.observability.langfuse_service import (
    create_trace_context,
    end_trace,
    trace_event,
    trace_span,
    set_active_trace_context,
    reset_active_trace_context,
    set_trace_span_parent,
    reset_trace_span_parent,
    build_assistant_trace_metadata,
    start_trace_attribute_scope,
    observe_span,
    trace_contract_event,
    normalize_observability_metadata,
    get_active_trace_context,
    record_score,
    get_langchain_callbacks,
)
from app.config import config

logger = logging.getLogger(__name__)


def _citation_coverage_from_text(text: str) -> float:
    """
    Best-effort coverage metric: share of claim-like sentences that contain a citation marker.
    Supports both numeric markers [1] and chunk markers [CHUNK:...].
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    parts = [p.strip() for p in re.split(r"(?<=[\.\!\?\n])\s+", t) if p.strip()]
    # Filter tiny fragments (headers, bullet prefixes, etc.)
    sentences = [p for p in parts if len(p) >= 20]
    if not sentences:
        return 0.0
    cited = 0
    for s in sentences:
        if re.search(r"\[(\d+|CHUNK:[^\]]+)\]", s):
            cited += 1
    return max(0.0, min(1.0, cited / max(1, len(sentences))))
_SLA_REQUEST_WARN_MS = int(getattr(config, "CASE_ASSISTANT_SLA_REQUEST_WARN_MS", 60_000) or 60_000)
_SLA_TOOL_WARN_MS = int(getattr(config, "CASE_ASSISTANT_SLA_TOOL_WARN_MS", 30_000) or 30_000)
_classifier_singleton: Optional[RequestClassifier] = None
_classifier_lock = threading.Lock()

_CASE_NUMBER_RE = re.compile(
    r"\b(?:номер\s+дела|№\s*дела|id\s*дела|ид\s*дела|идентификатор\s+дела)\b",
    re.IGNORECASE,
)
_CASE_DATE_RE = re.compile(
    r"\b(?:дата\s+дела|когда\s+создано\s+дело|дата\s+создания\s+дела)\b",
    re.IGNORECASE,
)
_CASE_STATUS_RE = re.compile(
    r"\b(?:статус\s+дела|в\s+каком\s+статусе\s+дело)\b",
    re.IGNORECASE,
)
_CASE_DOCS_COUNT_RE = re.compile(
    r"\b(?:сколько\s+документ\w*\s+в\s+деле|количеств\w*\s+документ\w*\s+в\s+деле|число\s+документ\w*\s+в\s+деле)\b",
    re.IGNORECASE,
)
_CASE_TITLE_RE = re.compile(
    r"\b(?:названи\w*\s+дела|как\s+называ\w*\s+дело|заголов\w*\s+дела)\b",
    re.IGNORECASE,
)
_DOC_DATE_QUERY_RE = re.compile(
    r"\b(?:дата\w*\s+(?:выписк\w*|документ\w*|справк\w*|решени\w*)|когда\s+(?:выдан\w*|составлен\w*|подписан\w*))\b",
    re.IGNORECASE,
)
_DATE_IN_TEXT_RE = re.compile(
    r"\b(?:[0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2}|(?:19|20)\d{2}[./-][01]?\d[./-][0-3]?\d)\b"
)
_ENTITY_LOOKUP_RE = re.compile(
    r"\b(?:судья|судьи|председательствующ|истец|ответчик|третье\s+лицо|инн|огрн|кпп|дата|номер|реквизит)\b",
    re.IGNORECASE,
)
_JUDGE_QUERY_RE = re.compile(
    r"\b(?:какие?\s+судьи|кто\s+судья|фамили[яи]\s+судьи|состав\s+суда|председательствующ)\b",
    re.IGNORECASE,
)
_OVERVIEW_QUERY_RE = re.compile(
    r"\b(?:о\s+ч[её]м\s+документ\w*|сводк\w*\s+по\s+документ\w*|кратк\w+\s+содержани\w*|обзор\s+документ\w*|что\s+в\s+документ\w*)\b",
    re.IGNORECASE,
)
def _get_shared_classifier() -> Optional[RequestClassifier]:
    """Lazy singleton classifier to avoid per-request LLM initialization."""
    global _classifier_singleton
    if _classifier_singleton is not None:
        return _classifier_singleton
    with _classifier_lock:
        if _classifier_singleton is not None:
            return _classifier_singleton
        try:
            from app.services.llm_factory import create_llm
            from app.services.external_sources.cache_manager import get_cache_manager

            llm = create_llm(temperature=0.0, max_tokens=500)
            cache = get_cache_manager()
            _classifier_singleton = RequestClassifier(llm=llm, cache=cache)
        except Exception as e:
            logger.warning(
                "[ChatOrchestrator] Shared classifier init failed: %s, classification will be disabled",
                e,
            )
            _classifier_singleton = None
    return _classifier_singleton


@dataclass
class ChatRequest:
    """Запрос к чату"""
    case_id: str
    question: str
    current_user: User
    
    # Режимы (взаимоисключающие в UI)
    web_search: bool = False
    legal_research: bool = False  # СПРАВОЧНИК
    court_practice: bool = False    # Судебная практика (корпус ВС/КС и т.д.)
    deep_think: bool = False      # GigaChat Pro + Thinking
    draft_mode: bool = False      # Создание документов
    
    # Контекст редактора
    document_context: Optional[str] = None
    document_id: Optional[str] = None
    selected_text: Optional[str] = None
    editor_mode_hint: Optional[str] = None  # 'edit' or 'ask' from UI toggle
    
    # Шаблон для draft mode (файл пользователя; системный — автоподбор)
    template_file_id: Optional[str] = None
    template_file_content: Optional[str] = None
    
    # Прикреплённые файлы
    attached_file_ids: Optional[List[str]] = None

    # ID сессии (если передан клиентом — продолжаем её, иначе auto-detect)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    mode: Optional[str] = None
    route_hint: Optional[str] = None
    prompt_profile_id: Optional[str] = None
    semantic_intent: Optional[str] = None  # fact | analysis
    retrieval_probe_hits: int = 0
    retrieval_probe_covered: bool = False
    task_type: Optional[str] = None
    task_family: Optional[str] = None
    depth_tier: Optional[str] = None
    route_confidence: Optional[float] = None
    route_reason: Optional[str] = None
    fallback_reason: Optional[str] = None
    clarification_needed: bool = False
    budget_profile: Optional[Dict[str, Any]] = None
    corpus_size: int = 0
    retrieval_task: Optional[Dict[str, Any]] = None
    scoped_file_ids: Optional[List[str]] = None
    scoped_doc_type: Optional[str] = None
    # Session Context Service (case + global): prompt + meta for LangGraph state
    session_context_prompt: Optional[str] = None
    session_context_meta: Optional[Dict[str, Any]] = None
    # Structured data router (HTTP prep → graph)
    structured_data_plane: Optional[str] = None
    statement_scope_file_ids: Optional[List[str]] = None
    hybrid_rag_file_ids: Optional[List[str]] = None
    structured_data_router_meta: Optional[Dict[str, Any]] = None
    # Явное действие UI: одобрить / отклонить план без двусмысленного текста в чате
    draft_action: Optional[str] = None


class ChatOrchestrator:
    """
    Главный оркестратор чат-запросов.
    Поддерживает fast/deep/clarify контур для case-assistant.
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None,
        classifier: Optional[RequestClassifier] = None
    ):
        """
        Инициализация оркестратора
        
        Args:
            db: SQLAlchemy сессия
            rag_service: RAG сервис (создаётся если не передан)
            document_processor: Document processor (создаётся если не передан)
            classifier: Классификатор запросов (для метрик)
        """
        self.db = db
        self.document_processor = document_processor or get_document_processor()
        self.rag_service = rag_service or get_rag_service(self.document_processor)
        self.classifier = classifier
        
        # Инициализируем сервисы
        self.history_service = ChatHistoryService(db)
        
        # Инициализируем handlers
        self.editor_handler = EditorHandler(self.rag_service, db)
        
        # Метрики
        self.metrics = get_metrics()
        
        logger.info("ChatOrchestrator initialized (strict router: draft/mixed/case-only)")
    
    async def process_request(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """
        Обработать запрос к чату
        
        Args:
            request: ChatRequest с параметрами запроса
            
        Yields:
            SSE события (строки в формате "data: {...}\n\n")
        """
        import time
        
        start_time = time.time()
        wall_start = time.monotonic()
        mode = self._determine_mode(request)
        active_trace_ctx = get_active_trace_context()
        owns_trace = active_trace_ctx is None
        trace_ctx = active_trace_ctx or create_trace_context(
            name="chat_orchestrator_process_request",
            trace_id=request.trace_id,
            user_id=str(request.current_user.id),
            session_id=request.session_id,
            metadata=build_assistant_trace_metadata(
                feature="case_assistant",
                route="/api/v2/assistant/chat",
                environment=getattr(config, "ENVIRONMENT", None),
                model_provider=getattr(config, "LLM_PROVIDER", None),
                case_id=request.case_id,
                draft_mode=bool(request.draft_mode),
                attached_files_count=len(request.attached_file_ids or []),
                web_search=bool(request.web_search),
                legal_research=bool(request.legal_research),
                deep_think=bool(request.deep_think),
                assistant_type="case_assistant",
                mode=mode,
                execution_path="case_orchestrator",
                scope_result="scope_pending",
                citation_result="citation_pending",
                confidence_result="confidence_pending",
                extra={"mode": mode, "component": "chat_orchestrator"},
            ),
            input_payload={"question": (request.question or "")[:3000]},
        )
        trace_token = set_active_trace_context(trace_ctx) if owns_trace else None
        runtime_scope = None

        try:
            # Записываем метрику запроса
            self.metrics.record_request(mode)
            trace_contract_event(
                trace_ctx,
                name="request_received",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "mode": mode,
                        "case_id": request.case_id,
                        "session_id": request.session_id or "",
                        "attached_files_count": len(request.attached_file_ids or []),
                        "task_type": request.task_type or "",
                        "task_family": request.task_family or "",
                        "depth_tier": request.depth_tier or "",
                        "clarification_needed": bool(request.clarification_needed),
                        "route_confidence": float(request.route_confidence or 0.0),
                        "route_reason": request.route_reason or "",
                        "flags": {
                            "web_search": bool(request.web_search),
                            "legal_research": bool(request.legal_research),
                            "deep_think": bool(request.deep_think),
                            "draft_mode": bool(request.draft_mode),
                        },
                    },
                    step_name="request_received",
                    status="success",
                ),
                input_payload={"question": (request.question or "")[:3000]},
            )
            trace_contract_event(
                trace_ctx,
                name="request_routed",
                metadata=normalize_observability_metadata(
                    {"mode": mode, "assistant_type": "case_assistant"},
                    step_name="route_request",
                    status="success",
                ),
            )

            if getattr(config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True):
                from app.services.chat.assistant_activity import (
                    activity_sse,
                    build_preparing_session_activity,
                )

                yield activity_sse(
                    build_preparing_session_activity(question=request.question or "")
                )
            
            # Проверяем доступ к делу
            verify_span = trace_span(
                trace_ctx,
                name="case_chat_verify_case_access",
                metadata={"case_id": request.case_id},
            )
            try:
                case = self._verify_case_access(request.case_id, request.current_user)
                if not case:
                    trace_event(
                        trace_ctx,
                        name="case_chat_case_not_found",
                        level="ERROR",
                        metadata={"case_id": request.case_id},
                    )
                    if verify_span:
                        verify_span.update(
                            level="ERROR",
                            status_message="case_not_found",
                            output={"case_found": False},
                        )
                    self.metrics.record_error(f"{mode}:case_not_found")
                    yield SSESerializer.error("Дело не найдено")
                    return
                if verify_span:
                    verify_span.update(output={"case_found": True})
            finally:
                if verify_span:
                    try:
                        verify_span.end()
                    except Exception:
                        logger.debug("case_chat_verify_case_access span end failed", exc_info=True)
            
            # Создаём сессию и сохраняем сообщение пользователя
            session_span = trace_span(
                trace_ctx,
                name="case_chat_prepare_session",
                metadata={"requested_session_id": request.session_id},
            )
            try:
                with assistant_step_span(
                    "case",
                    "orchestrator.prepare_session",
                    metadata={"case_id": request.case_id},
                ) as orch_prep_out:
                    session_id = request.session_id or self.history_service.get_or_create_session(request.case_id)
                    orch_prep_out["session_id"] = session_id
                run_ctx = ConversationPolicyService.build_run_context(
                    session_id=session_id,
                    user_id=str(request.current_user.id),
                    scope="case",
                    case_id=request.case_id,
                    matter_context=[],
                    draft_mode=bool(request.draft_mode),
                    legal_research=bool(request.legal_research),
                    deep_think=bool(request.deep_think),
                    document_context=request.document_context,
                    mode_hint=getattr(request, "mode", None),
                )
                scope_gate = LegalQualityGates.scope_gate(run_ctx)
                self.metrics.record_mode_eval(run_ctx.mode, "scope_gate", scope_gate.allowed)
                if not scope_gate.allowed:
                    trace_contract_event(
                        trace_ctx,
                        name="quality_gate",
                        level="WARNING",
                        metadata=normalize_observability_metadata(
                            {"gate": "scope", "gate_status": scope_gate.status},
                            step_name="scope_gate",
                            status="blocked",
                            error=scope_gate.message or "Scope gate blocked request",
                        ),
                    )
                    yield SSESerializer.text_delta(scope_gate.message or "Scope gate blocked request")
                    return
                user_message = self.history_service.save_user_message(
                    case_id=request.case_id,
                    content=request.question,
                    session_id=session_id
                )
                if session_span:
                    session_span.update(
                        output={
                            "session_id": session_id,
                            "user_message_saved": bool(user_message),
                        }
                    )
                # session_id становится известен после get_or_create_session:
                # запускаем вложенный propagate_attributes scope, чтобы все дальнейшие
                # observations в этом запросе были корректно сгруппированы по session.
                runtime_scope = start_trace_attribute_scope(
                    session_id=session_id,
                    user_id=str(request.current_user.id),
                    metadata={"case_id": request.case_id},
                    tags=["case_assistant", "in_case_chat"],
                )
            except Exception as session_err:
                if session_span:
                    session_span.update(
                        level="ERROR",
                        status_message="session_prepare_failed",
                        output={"error": str(session_err)},
                    )
                raise
            finally:
                if session_span:
                    try:
                        session_span.end()
                    except Exception:
                        logger.debug("case_chat_prepare_session span end failed", exc_info=True)
            # Сообщаем клиенту session_id чтобы он мог продолжать ту же сессию
            yield SSESerializer.session(session_id)
            if getattr(config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True):
                from app.services.chat.assistant_activity import (
                    activity_sse,
                    build_preparing_session_activity,
                    mark_step_completed,
                )

                yield activity_sse(
                    mark_step_completed(
                        build_preparing_session_activity(question=request.question or "")
                    )
                )

            # Создаём placeholder для ответа ассистента
            assistant_placeholder = self.history_service.create_assistant_placeholder(
                case_id=request.case_id,
                session_id=session_id
            )

            # Определяем handler и обрабатываем запрос
            full_response = ""
            draft_document_created: Optional[dict] = None
            citations_data = []
            answer_blocks_data: list = []
            turn_state_data: Optional[dict] = None
            route_started_at = time.monotonic()
            route_finished_at = route_started_at
            save_latency_ms = 0

            try:
                route_span = trace_span(
                    trace_ctx,
                    name="case_chat_route_to_handler",
                    metadata={"mode": mode},
                )
                parent_token = set_trace_span_parent(route_span)
                try:
                    async for event in self._route_to_handler(request, session_id):
                        yield event
                        # Извлекаем текст для сохранения
                        full_response += self._extract_text_from_event(event)
                        doc_card = self._extract_document_card_from_event(event)
                        if doc_card:
                            draft_document_created = doc_card
                        # Захватываем citations для сохранения в БД
                        extracted_citations = self._extract_citations_from_event(event)
                        if extracted_citations:
                            citations_data = extracted_citations
                        extracted_ab = self._extract_answer_blocks_from_event(event)
                        if extracted_ab:
                            answer_blocks_data = extracted_ab
                        extracted_ts = self._extract_turn_state_from_event(event)
                        if extracted_ts:
                            turn_state_data = extracted_ts
                    route_finished_at = time.monotonic()
                    if route_span:
                        route_span.update(
                            output={
                                "response_chars": len(full_response),
                                "citations_count": len(citations_data or []),
                            }
                        )
                except Exception as handler_err:
                    if route_span:
                        route_span.update(
                            level="ERROR",
                            status_message="handler_failed",
                            output={"error": str(handler_err)},
                        )
                    raise
                finally:
                    reset_trace_span_parent(parent_token)
                    if route_span:
                        try:
                            route_span.end()
                        except Exception:
                            logger.debug("case_chat_route_to_handler span end failed", exc_info=True)

            finally:
                # Draft: документ в редакторе — валидный исход даже без textDelta.
                if not (full_response or "").strip() and draft_document_created:
                    doc_title = str(draft_document_created.get("title") or "Документ")
                    doc_id = str(draft_document_created.get("id") or "")
                    case_id = str(draft_document_created.get("case_id") or request.case_id)
                    full_response = (
                        f'✅ Документ «{doc_title}» создан.\n'
                        f"Открыть в редакторе: /cases/{case_id}/editor/{doc_id}"
                    )
                    yield SSESerializer.text_delta(full_response)

                # Fail-closed: пустой финальный ответ не допускаем.
                if not (full_response or "").strip():
                    trace_contract_event(
                        trace_ctx,
                        name="quality_gate",
                        level="ERROR",
                        metadata=normalize_observability_metadata(
                            {
                                "assistant_type": "case_assistant",
                                "gate": "answer_generation",
                                "gate_status": "answer_generation_failed",
                                "mode": mode,
                                "session_id": session_id,
                                "document_created": bool(draft_document_created),
                            },
                            step_name="answer_generation_gate",
                            status="blocked",
                            error="Empty assistant response",
                        ),
                    )
                    yield SSESerializer.status(
                        "quality_gate",
                        gate_status="answer_generation_failed",
                        gate_message="Ответ не сформирован. Попробуйте переформулировать вопрос или уточнить, какой документ/факт нужен.",
                    )
                    yield SSESerializer.error("Ответ не сформирован")
                    self.metrics.record_error(f"{mode}:empty_answer")
                    if owns_trace:
                        end_trace(
                            trace_ctx,
                            status="error",
                            error="Empty assistant response",
                            metadata={"mode": mode, "session_id": session_id},
                        )
                    return

                # Сохраняем ответ в БД
                if full_response:
                    save_span = trace_span(
                        trace_ctx,
                        name="case_chat_save_assistant_message",
                        metadata={"message_id": assistant_placeholder.id if assistant_placeholder else None},
                    )
                    try:
                        save_started_at = time.monotonic()
                        with assistant_step_span(
                            "case",
                            "orchestrator.save_assistant_message",
                            metadata={
                                "case_id": request.case_id,
                                "session_id": session_id,
                            },
                        ) as orch_save_out:
                            refs_save = None
                            if answer_blocks_data:
                                refs_save = {
                                    "citations": citations_data or [],
                                    "answer_blocks": answer_blocks_data,
                                }
                            elif citations_data:
                                refs_save = citations_data
                            from app.services.chat.assistant_persist_payload import (
                                build_case_assistant_evidence,
                            )

                            evidence_save = build_case_assistant_evidence(
                                citations=citations_data or [],
                                turn_state=turn_state_data,
                            )
                            if answer_blocks_data:
                                evidence_save["answer_blocks"] = answer_blocks_data
                            self.history_service.update_assistant_message(
                                message_id=assistant_placeholder.id,
                                content=full_response,
                                source_references=refs_save,
                                evidence=evidence_save,
                            )
                            orch_save_out["content_chars"] = len(full_response)
                            orch_save_out["citations_count"] = len(citations_data or [])
                        save_latency_ms = int((time.monotonic() - save_started_at) * 1000)
                        trace_contract_event(
                            trace_ctx,
                            name="response_saved",
                            metadata=normalize_observability_metadata(
                                {"assistant_type": "case_assistant", "session_id": session_id},
                                step_name="save_assistant_message",
                                status="success",
                                citations_count=len(citations_data or []),
                                latency_ms=save_latency_ms,
                            ),
                            output_payload={"response_length": len(full_response)},
                        )
                        if save_span:
                            save_span.update(
                                output={
                                    "saved": True,
                                    "content_chars": len(full_response),
                                    "citations_count": len(citations_data or []),
                                }
                            )
                    except Exception as save_err:
                        trace_event(
                            trace_ctx,
                            name="case_chat_save_failed",
                            level="ERROR",
                            metadata={"error": str(save_err)},
                        )
                        if save_span:
                            save_span.update(
                                level="ERROR",
                                status_message="save_failed",
                                output={"error": str(save_err)},
                            )
                        raise
                    finally:
                        if save_span:
                            try:
                                save_span.end()
                            except Exception:
                                logger.debug("case_chat_save_assistant_message span end failed", exc_info=True)
                
                # Записываем метрику латентности
                latency = time.time() - start_time
                self.metrics.record_latency(mode, latency)
                final_quality: Dict[str, Any] = {}
                total_latency_ms = int((time.monotonic() - wall_start) * 1000)
                route_latency_ms = int((route_finished_at - route_started_at) * 1000)
                orchestration_latency_ms = max(0, total_latency_ms - route_latency_ms - save_latency_ms)
                phase_latencies = {
                    "orchestration_ms": orchestration_latency_ms,
                    "route_and_tooling_ms": route_latency_ms,
                    "persistence_ms": save_latency_ms,
                    "total_ms": total_latency_ms,
                }
                if "run_ctx" in locals():
                    citation_gate = LegalQualityGates.citation_gate(
                        run_ctx,
                        citations_data or [],
                        prompt_profile_id=request.prompt_profile_id,
                    )
                    self.metrics.record_mode_eval(run_ctx.mode, "citation_gate", citation_gate.allowed)
                    final_quality["citation_result"] = "passed" if citation_gate.allowed else citation_gate.status
                    confidence_gate = LegalQualityGates.confidence_gate(
                        run_ctx,
                        retrieval_hits=len(citations_data or []),
                        prompt_profile_id=request.prompt_profile_id,
                    )
                    self.metrics.record_mode_eval(run_ctx.mode, "confidence_gate", confidence_gate.allowed)
                    final_quality["confidence_result"] = "passed" if confidence_gate.allowed else confidence_gate.status
                    # Simple normalized scoring for trend analysis in Langfuse.
                    has_citations = len(citations_data or []) > 0
                    answer_has_content = bool((full_response or "").strip()) and len((full_response or "").strip()) >= 60
                    answer_groundedness = 1.0 if citation_gate.allowed else (0.6 if has_citations else 0.2)
                    citation_coverage_text = _citation_coverage_from_text(full_response or "")
                    citation_coverage_heur = min(1.0, len(citations_data or []) / 3.0)
                    response_usefulness = 1.0 if answer_has_content else 0.2
                    score_meta = {
                        "assistant_type": "case_assistant",
                        "mode": mode,
                        "prompt_profile_id": request.prompt_profile_id or "legacy_default",
                        "session_id": session_id,
                    }
                    record_score(
                        trace_id=trace_ctx.trace_id,
                        name="answer_groundedness",
                        value=answer_groundedness,
                        metadata=score_meta,
                    )
                    record_score(
                        trace_id=trace_ctx.trace_id,
                        name="citation_coverage",
                        value=citation_coverage_text,
                        metadata=score_meta,
                    )
                    record_score(
                        trace_id=trace_ctx.trace_id,
                        name="citation_coverage_heur",
                        value=citation_coverage_heur,
                        metadata=score_meta,
                    )
                    record_score(
                        trace_id=trace_ctx.trace_id,
                        name="response_usefulness",
                        value=response_usefulness,
                        metadata=score_meta,
                    )
                    final_quality.update(
                        {
                            "answer_groundedness": answer_groundedness,
                            "citation_coverage": citation_coverage_text,
                            "citation_coverage_heur": citation_coverage_heur,
                            "response_usefulness": response_usefulness,
                        }
                    )
                logger.info(f"[ChatOrchestrator] {mode} completed in {latency:.2f}s, response length: {len(full_response)}")
                if total_latency_ms > _SLA_REQUEST_WARN_MS:
                    trace_contract_event(
                        trace_ctx,
                        name="sla_warning",
                        level="WARNING",
                        metadata=normalize_observability_metadata(
                            {
                                "assistant_type": "case_assistant",
                                "sla_type": "request_latency",
                                "threshold_ms": _SLA_REQUEST_WARN_MS,
                                "actual_ms": total_latency_ms,
                                "mode": mode,
                            },
                            step_name="sla_request_latency",
                            status="warning",
                            latency_ms=total_latency_ms,
                        ),
                    )
                if route_latency_ms > _SLA_TOOL_WARN_MS:
                    trace_contract_event(
                        trace_ctx,
                        name="sla_warning",
                        level="WARNING",
                        metadata=normalize_observability_metadata(
                            {
                                "assistant_type": "case_assistant",
                                "sla_type": "route_tooling_latency",
                                "threshold_ms": _SLA_TOOL_WARN_MS,
                                "actual_ms": route_latency_ms,
                                "mode": mode,
                            },
                            step_name="sla_route_tooling_latency",
                            status="warning",
                            latency_ms=route_latency_ms,
                        ),
                    )
                trace_contract_event(
                    trace_ctx,
                    name="request_completed",
                    metadata=normalize_observability_metadata(
                        {
                            "assistant_type": "case_assistant",
                            "mode": mode,
                            "session_id": session_id,
                            "prompt_profile_id": request.prompt_profile_id or "legacy_default",
                            "task_type": request.task_type or "",
                            "task_family": request.task_family or "",
                            "depth_tier": request.depth_tier or "",
                            "clarification_needed": bool(request.clarification_needed),
                            "route_confidence": float(request.route_confidence or 0.0),
                            "route_reason": request.route_reason or "",
                            "fallback_reason": request.fallback_reason or "",
                            **phase_latencies,
                            **final_quality,
                        },
                        step_name="orchestrator_complete",
                        status="success",
                        latency_ms=int(latency * 1000),
                        citations_count=len(citations_data or []),
                    ),
                    output_payload={
                        "response_length": len(full_response),
                        "response_preview": (full_response or "")[:3000],
                    },
                )
                if owns_trace:
                    end_trace(
                        trace_ctx,
                        status="success",
                        output_payload={
                            "response_length": len(full_response),
                            "response_preview": (full_response or "")[:3000],
                        },
                        metadata={"latency_sec": latency, "session_id": session_id, **final_quality},
                    )

        except Exception as e:
            self.metrics.record_error(f"{mode}:exception")
            logger.error(f"[ChatOrchestrator] Error in {mode}: {e}", exc_info=True)
            trace_event(
                trace_ctx,
                name="case_chat_orchestrator_error",
                level="ERROR",
                metadata={"error": str(e), "mode": mode},
            )
            if owns_trace:
                end_trace(trace_ctx, status="error", error=str(e))
            yield SSESerializer.error(str(e))
        finally:
            if runtime_scope is not None:
                try:
                    runtime_scope.__exit__(None, None, None)
                except Exception:
                    logger.debug("Failed to exit runtime Langfuse attribute scope", exc_info=True)
            if owns_trace and trace_token is not None:
                reset_active_trace_context(trace_token)
    
    @observe_span("case_chat_determine_mode")
    def _determine_mode(self, request: ChatRequest) -> str:
        """Определить режим обработки запроса"""
        if request.draft_mode:
            return "draft"
        elif request.document_context:
            return "editor"
        elif request.deep_think:
            return "react_agent_deep"
        elif request.legal_research:
            return "react_agent_garant"
        else:
            return "react_agent"
    
    async def _route_to_handler(
        self,
        request: ChatRequest,
        session_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Маршрутизация к соответствующему handler'у
        """
        
        if request.draft_mode:
            from app.services.draft_agent import DraftAgentStreamService

            draft_service = DraftAgentStreamService(self.db)
            async for event in draft_service.stream(
                case_id=request.case_id,
                question=request.question,
                user=request.current_user,
                session_id=session_id,
                attached_file_ids=request.attached_file_ids,
                template_file_id=request.template_file_id,
                template_file_content=request.template_file_content,
            ):
                yield event
            return

        elif request.document_context:
            # Editor mode: редактирование документов
            async for event in self.editor_handler.handle(
                case_id=request.case_id,
                question=request.question,
                current_user=request.current_user,
                document_id=request.document_id or "",
                document_context=request.document_context,
                selected_text=request.selected_text,
                editor_mode_hint=request.editor_mode_hint
            ):
                yield event
        
        else:
            # Канонический runtime: всегда LangGraph ChatGraphService.
            # Это убирает параллельный движок ReAct и делает качество/гейты единообразными.
            chat_service = get_chat_graph_service(
                db=self.db,
                rag_service=self.rag_service,
                document_processor=self.document_processor,
            )
            async for event in chat_service.stream_response(
                case_id=request.case_id,
                question=request.question,
                user=request.current_user,
                deep_think=bool(request.deep_think),
                legal_research=bool(request.legal_research),
                court_practice=bool(request.court_practice),
                draft_mode=False,
                document_context=None,
                document_id=None,
                selected_text=None,
                existing_messages=None,
                editor_mode_hint=request.editor_mode_hint,
                template_file_id=None,
                template_file_content=None,
                session_id=session_id,
                persist_history=False,
                attached_file_ids=request.attached_file_ids,
                task_type=request.task_type,
                depth_tier=request.depth_tier,
                budget_profile=request.budget_profile,
                corpus_size=request.corpus_size,
                clarification_needed=bool(request.clarification_needed),
                retrieval_task=request.retrieval_task,
                scoped_file_ids=request.scoped_file_ids,
                scoped_doc_type=request.scoped_doc_type,
                session_context_prompt=request.session_context_prompt,
                session_context_meta=request.session_context_meta,
                structured_data_plane=request.structured_data_plane,
                statement_scope_file_ids=request.statement_scope_file_ids,
                hybrid_rag_file_ids=request.hybrid_rag_file_ids,
                structured_data_router_meta=request.structured_data_router_meta,
            ):
                yield event
            return

    async def _run_fast_path(
        self,
        *,
        request: ChatRequest,
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Fast deterministic path: targeted retrieval + short synthesis + citations.
        Avoids agent loops for simple factual questions.
        """
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        trace_contract_event(
            get_active_trace_context(),
            name="request_routed",
            metadata=normalize_observability_metadata(
                {
                    "assistant_type": "case_assistant",
                    "execution_path": "fast_path",
                    "task_type": request.task_type or "",
                    "corpus_size": int(request.corpus_size or 0),
                    "budget_profile_name": str((request.budget_profile or {}).get("name") or ""),
                    "semantic_intent": request.semantic_intent or "",
                    "probe_hits": int(request.retrieval_probe_hits or 0),
                    "probe_covered": bool(request.retrieval_probe_covered),
                },
                step_name="fast_path_routed",
                status="success",
            ),
        )
        yield SSESerializer.status("routing", route="fast_path", task_type=request.task_type or "")
        stream_activity_ui = bool(getattr(config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True))
        if stream_activity_ui:
            from app.services.chat.assistant_activity import (
                activity_sse,
                build_fast_path_scope_activity,
                build_stream_started_activity,
            )

            yield activity_sse(build_stream_started_activity(question=request.question))
            yield activity_sse(
                build_fast_path_scope_activity(
                    question=request.question,
                    attached_count=len(request.attached_file_ids or []),
                )
            )
        elif getattr(config, "CASE_ASSISTANT_STREAM_REASONING_UI", False):
            yield SSESerializer.reasoning(
                phase="retrieving",
                step=1,
                total_steps=3,
                content="Быстрый поиск релевантных фрагментов...",
            )

        metadata_fast = self._build_case_metadata_answer(
            question=request.question,
            case_id=request.case_id,
        )
        if metadata_fast is not None:
            metadata_answer, metadata_citation, metadata_kind = metadata_fast
            yield SSESerializer.text_delta(metadata_answer)
            yield SSESerializer.citations([metadata_citation])
            yield SSESerializer.status(
                "finalizing",
                mode=f"metadata_fast_path_{metadata_kind}",
                session_id=session_id,
                citations_count=1,
            )
            return

        if self._is_judge_lookup_query(request.question) or (
            (request.task_family or "").strip().lower() == "entity_fact"
        ):
            entity_pipeline = EntityFactPipeline(self.rag_service, self.db)
            entity_result = entity_pipeline.run_entity_fact_lookup(
                case_id=request.case_id,
                question=request.question,
                attached_file_ids=request.attached_file_ids,
                budget_profile=request.budget_profile,
            )
            trace_contract_event(
                get_active_trace_context(),
                name="coverage_gate",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "pipeline": "entity_fact",
                        "query_kind": "entity_fact",
                        "result_confidence": entity_result.confidence,
                        **entity_result.coverage.to_metadata(),
                    },
                    step_name="coverage_gate",
                    status="passed" if entity_result.coverage.negative_answer_allowed else "blocked",
                ),
            )
            if entity_result.kind == "insufficient_coverage":
                yield SSESerializer.status(
                    "quality_gate",
                    gate_status="insufficient_coverage",
                    gate_message=entity_result.answer,
                )
                yield SSESerializer.text_delta(entity_result.answer)
                return
            yield SSESerializer.text_delta(entity_result.answer)
            if entity_result.citations:
                yield SSESerializer.citations(entity_result.citations)
            yield SSESerializer.status(
                "finalizing",
                mode=f"entity_pipeline_{entity_result.kind}",
                session_id=session_id,
                citations_count=len(entity_result.citations),
                confidence=entity_result.confidence,
            )
            return

        retrieval_strategy, retrieve_k = self._select_fast_retrieval_policy(request)

        docs = self.rag_service.retrieve_context(
            case_id=request.case_id,
            query=request.question,
            k=retrieve_k,
            retrieval_strategy=retrieval_strategy,
            db=self.db,
            file_ids=request.attached_file_ids,
        )
        if stream_activity_ui:
            from app.services.chat.assistant_activity import (
                activity_sse,
                build_fast_path_recall_completed,
            )

            unique_files = {
                str((d.metadata or {}).get("file_id") or "")
                for d in docs
                if (d.metadata or {}).get("file_id")
            }
            yield activity_sse(
                build_fast_path_recall_completed(
                    question=request.question,
                    retrieved_chunks=len(docs),
                    docs_used=len(unique_files),
                )
            )
        if self._is_document_date_query(request.question):
            date_answer = self._build_document_date_answer_from_docs(docs)
            if date_answer:
                yield SSESerializer.text_delta(date_answer)
                originals = (
                    fetch_original_text_map_for_case(self.db, request.case_id)
                    if self.db and request.case_id
                    else {}
                )
                sources = build_retrieval_citations(
                    list(docs[:5]),
                    original_text_by_file_id=originals or None,
                )
                if sources:
                    yield SSESerializer.citations(sources)
                yield SSESerializer.status(
                    "finalizing",
                    mode="fast_path_date_lookup",
                    session_id=session_id,
                    citations_count=len(sources),
                )
                return

        budget = request.budget_profile or {}
        budget_llm_calls = int(budget.get("max_llm_calls", 1) or 1)
        budget_context = int(
            getattr(config, "CASE_ASSISTANT_FAST_MAX_CONTEXT_CHARS", 3200)
            or 3200
        )
        is_overview_query = self._is_overview_query(request.question)
        max_context_chars = max(1200, min(9000, budget_context))
        docs_limit = max(1, min(8, int(budget.get("max_tool_calls", 2) or 2) * 2))
        if is_overview_query:
            docs_limit = max(docs_limit, 6)
            max_context_chars = max(max_context_chars, 5200)
        docs_for_prompt = docs[:docs_limit]
        docs_for_prompt = filter_docs_for_tabular_citations(docs_for_prompt)
        context, prompt_docs = self.rag_service.format_sources_for_prompt_with_docs(
            docs_for_prompt, max_context_chars=max_context_chars
        )
        trace_contract_event(
            get_active_trace_context(),
            name="coverage_gate",
            metadata=normalize_observability_metadata(
                {
                    "assistant_type": "case_assistant",
                    "pipeline": "fast_path_llm",
                    "coverage_status": "covered" if len(docs_for_prompt) >= 2 else "partial",
                    "retrieval_k": retrieve_k,
                    "retrieved_chunks_count": len(docs),
                    "negative_answer_allowed": len(docs_for_prompt) >= 2,
                },
                step_name="coverage_gate",
                status="passed" if len(docs_for_prompt) >= 2 else "blocked",
            ),
        )
        llm = create_legal_llm(
            temperature=0.0,
            use_rate_limiting=False,
            max_tokens=700,
        )
        callbacks = get_langchain_callbacks(
            session_id=session_id,
            user_id=str(request.current_user.id),
            tags=["assistant", "case_assistant", "fast_path"],
        )

        if stream_activity_ui:
            from app.services.chat.assistant_activity import (
                activity_sse,
                build_fast_path_synthesis_activity,
            )

            yield activity_sse(
                build_fast_path_synthesis_activity(overview=is_overview_query)
            )
        elif getattr(config, "CASE_ASSISTANT_STREAM_REASONING_UI", False):
            yield SSESerializer.reasoning(
                phase="synthesizing",
                step=2,
                total_steps=3,
                content=(
                    "Формирую обзор по найденным материалам..."
                    if is_overview_query
                    else "Формирую краткий ответ по найденным фактам..."
                ),
            )
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Ты юридический ассистент. "
                        "Любой видимый пользователю текст, включая рассуждения, — только на русском. "
                        + (
                            "Сделай краткий обзор материалов дела строго по контексту: "
                            "1) предмет документов, 2) ключевые факты/даты/реквизиты, 3) возможные пробелы в данных. "
                            "Ответ 4-7 предложений, без выдумок и без просьбы об уточнении, если в контексте есть данные."
                            if is_overview_query
                            else "Дай короткий фактологический ответ на основе контекста. "
                            "Максимум 3 предложения. Если данных недостаточно — честно напиши, что точный факт не найден в контексте."
                        )
                        + "\n\n"
                        + "ССЫЛКИ НА ФРАГМЕНТЫ ДЕЛА: в контексте у каждого фрагмента указаны «Документ Dd …, чанк Cc». "
                        + "После каждого смыслового фрагмента ответа, который опирается на материалы дела, ставь маркеры "
                        + "строго в виде [Dd:Cc] (например [D1:C3]) — только те пары d и c, что реально есть в шапках фрагментов. "
                        + "Несколько фрагментов: [D1:C0][D2:C1]. Не используй номера, которых нет в контексте. "
                        + "Допустимо также кратко [N], если N — порядковый номер фрагмента в контексте (1,2,3… сверху вниз). "
                        + "Если утверждение не из контекста — маркеры не ставь. "
                        + "Не вставляй JSON, ```json и не выводи {\"blocks\": ...} в ответе. "
                        + "На вопросы «пункт N» без указания документа отвечай только по фрагменту дела из контекста, без длинных подборок «возможных значений термина». "
                        + "Не используй подписи «Ответ по существу:», «Обоснование:», «Уточнения:» — пиши связными абзацами."
                    )
                ),
                HumanMessage(
                    content=f"Контекст:\n{context}\n\nВопрос: {request.question}\n\nОтвет:"
                ),
            ],
            config={"callbacks": callbacks} if callbacks else None,
        )
        answer = response.content if hasattr(response, "content") else str(response)
        answer_text = (answer if isinstance(answer, str) else str(answer)).strip()
        answer_text = strip_llm_answer_leaks(answer_text)
        if not answer_text:
            # Прямой RAG-контур без отказных quality-gate сообщений:
            # если модель вернула пусто, отдаем краткий фрагмент retrieval-контекста.
            first_chunk = str((docs[0].page_content if docs else "") or "").strip()
            answer_text = first_chunk[:700].strip() if first_chunk else "Ответ не сформирован."

        originals = (
            fetch_original_text_map_for_case(self.db, request.case_id)
            if self.db and request.case_id
            else {}
        )
        sources = build_retrieval_citations(
            list(prompt_docs),
            original_text_by_file_id=originals or None,
        )
        answer_text, dc_meta = expand_dc_markers_to_cite_zw(answer_text, sources)
        if dc_meta.get("removed_invalid_dc"):
            trace_contract_event(
                get_active_trace_context(),
                name="citation_dc_expand",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "pipeline": "fast_path_llm",
                        **dc_meta,
                    },
                    step_name="citation_dc_expand",
                    status="warn",
                ),
            )
        answer_text, repair_meta = repair_citation_brackets(answer_text, len(sources))
        # Safety net: если нет ни [N], ни встроенных CITE-маркеров — добавить компактные [1]..[k].
        if (
            sources
            and not re.search(r"\[\d+\]", answer_text)
            and not re.search(r"CITE_cit_", answer_text)
        ):
            refs = "".join(f"[{i+1}]" for i in range(len(sources)))
            answer_text = (answer_text.rstrip() + " " + refs).strip()
        if repair_meta.get("removed_invalid") or repair_meta.get("removed_all_due_to_zero"):
            trace_contract_event(
                get_active_trace_context(),
                name="citation_bracket_repair",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "pipeline": "fast_path_llm",
                        **repair_meta,
                    },
                    step_name="citation_bracket_repair",
                    status="warn",
                ),
            )

        yield SSESerializer.text_delta(answer_text)

        if sources:
            yield SSESerializer.citations(sources)

        yield SSESerializer.status(
            "finalizing",
            mode="fast_path",
            session_id=session_id,
            citations_count=len(sources),
        )

    @staticmethod
    def _build_extractive_fallback_answer(*, question: str, docs: List[Any]) -> str:
        """
        Minimal deterministic fallback for ordinary RAG:
        return the most relevant sentence fragments from retrieved chunks
        instead of a generic refusal.
        """
        q = (question or "").strip().lower()
        if not docs:
            return ""
        snippets: List[str] = []
        for doc in docs:
            text = str((getattr(doc, "page_content", "") or "")).strip()
            if not text:
                continue
            # Prefer short first sentence-like fragment; keep answer concise.
            fragment = re.split(r"(?<=[\.\!\?])\s+|\n+", text)[0].strip()
            if not fragment:
                fragment = text[:240].strip()
            if len(fragment) > 260:
                fragment = fragment[:260].rstrip() + "..."
            if fragment and fragment not in snippets:
                snippets.append(fragment)
            if len(snippets) >= 2:
                break
        if not snippets:
            return ""
        if any(token in q for token in ("дата", "когда", "срок")):
            return f"По документам найдено: {snippets[0]}"
        return "По документам найдено:\n- " + "\n- ".join(snippets)

    def _select_fast_retrieval_policy(self, request: ChatRequest) -> tuple[str, int]:
        """
        Ordinary RAG policy for internal assistant:
        fixed retrieval strategy and fixed k.
        """
        return "simple", 5

    @staticmethod
    def _is_entity_lookup_query(question: str) -> bool:
        if not question:
            return False
        return bool(_ENTITY_LOOKUP_RE.search(question))

    @staticmethod
    def _is_judge_lookup_query(question: str) -> bool:
        if not question:
            return False
        return bool(_JUDGE_QUERY_RE.search(question))

    @staticmethod
    def _is_overview_query(question: str) -> bool:
        if not question:
            return False
        return bool(_OVERVIEW_QUERY_RE.search(question))

    @staticmethod
    def _is_case_number_query(question: str) -> bool:
        text = (question or "").strip()
        if not text:
            return False
        return bool(_CASE_NUMBER_RE.search(text))

    @staticmethod
    def _is_case_date_query(question: str) -> bool:
        return bool(_CASE_DATE_RE.search((question or "").strip()))

    @staticmethod
    def _is_document_date_query(question: str) -> bool:
        return bool(_DOC_DATE_QUERY_RE.search((question or "").strip()))

    @staticmethod
    def _build_document_date_answer_from_docs(docs: List[Any]) -> Optional[str]:
        for doc in docs or []:
            text = str((getattr(doc, "page_content", "") or "")).strip()
            if not text:
                continue
            match = _DATE_IN_TEXT_RE.search(text)
            if match:
                return f"Дата документа: {match.group(0)}."
        return "В найденных фрагментах дата документа не указана."

    @staticmethod
    def _is_case_status_query(question: str) -> bool:
        return bool(_CASE_STATUS_RE.search((question or "").strip()))

    @staticmethod
    def _is_case_docs_count_query(question: str) -> bool:
        return bool(_CASE_DOCS_COUNT_RE.search((question or "").strip()))

    @staticmethod
    def _is_case_title_query(question: str) -> bool:
        return bool(_CASE_TITLE_RE.search((question or "").strip()))

    def _build_case_metadata_answer(
        self,
        *,
        question: str,
        case_id: str,
    ) -> Optional[tuple[str, Dict[str, Any], str]]:
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if case is None:
            return None

        if self._is_case_number_query(question):
            answer, citation = self._build_case_number_answer(case_id, case=case)
            return answer, citation, "number"
        if self._is_case_date_query(question):
            created = case.created_at.isoformat() if case.created_at else "не указана"
            answer = f"Дата создания дела: {created}."
            citation = self._build_case_metadata_citation(case_id, f"created_at: {created}")
            return answer, citation, "date"
        if self._is_case_status_query(question):
            status = (case.status or "").strip() or "не указан"
            answer = f"Статус дела: {status}."
            citation = self._build_case_metadata_citation(case_id, f"status: {status}")
            return answer, citation, "status"
        if self._is_case_docs_count_query(question):
            docs_count = int(case.num_documents or 0)
            answer = f"Количество документов в деле: {docs_count}."
            citation = self._build_case_metadata_citation(case_id, f"num_documents: {docs_count}")
            return answer, citation, "docs_count"
        if self._is_case_title_query(question):
            title = (case.title or "").strip() or "не указано"
            answer = f"Название дела: {title}."
            citation = self._build_case_metadata_citation(case_id, f"title: {title}")
            return answer, citation, "title"
        return None

    def _build_case_number_answer(
        self,
        case_id: str,
        *,
        case: Optional[Case] = None,
    ) -> tuple[str, Dict[str, Any]]:
        resolved_number = None
        if case is not None:
            meta = case.case_metadata if isinstance(case.case_metadata, dict) else {}
            for key in ("case_number", "number", "matter_number", "court_case_number"):
                raw = meta.get(key)
                if isinstance(raw, str) and raw.strip():
                    resolved_number = raw.strip()
                    break
            if not resolved_number:
                resolved_number = str(case.id)
        else:
            resolved_number = str(case_id)

        answer = f"Номер дела: {resolved_number}."
        citation = self._build_case_metadata_citation(case_id, f"ID/номер дела: {resolved_number}")
        return answer, citation

    @staticmethod
    def _build_case_metadata_citation(case_id: str, quote: str) -> Dict[str, Any]:
        return {
            "source_id": str(case_id),
            "file_name": "Карточка дела",
            "quote": quote,
            "source_type": "document",
        }

    def _extract_text_from_event(self, event: str) -> str:
        """Извлечь текст из SSE события"""
        import json

        if "textDelta" not in event:
            return ""

        try:
            data = json.loads(event.replace("data: ", "").strip())
            return data.get("textDelta", "")
        except:
            return ""

    def _extract_document_card_from_event(self, event: str) -> Optional[dict]:
        """Извлечь document-card из SSE (draft workflow)."""
        import json

        if "document-card" not in event:
            return None

        try:
            data = json.loads(event.replace("data: ", "").strip())
            if data.get("type") != "document-card":
                return None
            payload = data.get("data")
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _extract_citations_from_event(self, event: str) -> list:
        """Извлечь citations из SSE события типа citations"""
        import json

        if "citations" not in event:
            return []

        try:
            data = json.loads(event.replace("data: ", "").strip())
            if data.get("type") == "citations" and isinstance(data.get("citations"), list):
                return data["citations"]
        except:
            pass
        return []

    def _extract_answer_blocks_from_event(self, event: str) -> list:
        """Извлечь answer_blocks из SSE (Phase 2)."""
        import json

        if "answer_blocks" not in event:
            return []

        try:
            data = json.loads(event.replace("data: ", "").strip())
            if data.get("type") == "answer_blocks" and isinstance(data.get("blocks"), list):
                return data["blocks"]
        except Exception:
            pass
        return []

    def _extract_turn_state_from_event(self, event: str) -> Optional[dict]:
        """Извлечь turn_state из SSE для persistence follow-up turns."""
        import json

        if "turn_state" not in event:
            return None

        try:
            data = json.loads(event.replace("data: ", "").strip())
            if data.get("type") == "turn_state" and isinstance(data.get("turn_state"), dict):
                return data["turn_state"]
        except Exception:
            pass
        return None
    
    @observe_span("case_chat_verify_case_access_internal")
    def _verify_case_access(self, case_id: str, user: User) -> Optional[Case]:
        """
        Проверить доступ пользователя к делу (membership ACL).

        Returns:
            Case если доступ есть, None иначе
        """
        try:
            return require_case_access(self.db, case_id, user.id)
        except HTTPException:
            logger.warning(
                "[ChatOrchestrator] Case access denied: case_id=%s user_id=%s",
                case_id,
                user.id,
            )
            return None
    
    async def classify_request(self, question: str) -> ClassificationResult:
        """
        Классифицировать запрос (task/question)
        
        Args:
            question: Текст запроса
            
        Returns:
            ClassificationResult
        """
        classifier = self.classifier or _get_shared_classifier()
        if not classifier:
            return ClassificationResult(
                label="question",
                confidence=0.5,
                rationale="Classifier unavailable",
            )
        return await classifier.classify(question)


# =============================================================================
# Factory function для создания оркестратора
# =============================================================================

def get_chat_orchestrator(db: Session) -> ChatOrchestrator:
    """
    Создать ChatOrchestrator с зависимостями
    
    Args:
        db: SQLAlchemy сессия
        
    Returns:
        ChatOrchestrator instance
    """
    document_processor = get_document_processor()
    rag_service = get_rag_service(document_processor)
    return ChatOrchestrator(
        db=db,
        rag_service=rag_service,
        document_processor=document_processor,
    )


def prewarm_chat_runtime() -> Dict[str, Any]:
    """
    Prewarm heavy case-assistant runtime dependencies at startup.

    Returns:
        Dict with component readiness flags and elapsed time.
    """
    import time

    started = time.monotonic()
    readiness: Dict[str, Any] = {
        "document_processor_ready": False,
        "rag_service_ready": False,
        "classifier_ready": False,
        "legal_llm_ready": False,
        "reranker_ready": False,
        "docling_ready": False,
    }
    try:
        document_processor = get_document_processor()
        readiness["document_processor_ready"] = document_processor is not None
    except Exception as exc:
        logger.warning("Case assistant prewarm: document_processor failed: %s", exc, exc_info=True)

    try:
        # Reuse already-initialized document processor singleton if available.
        rag_service = get_rag_service(get_document_processor())
        readiness["rag_service_ready"] = rag_service is not None
    except Exception as exc:
        logger.warning("Case assistant prewarm: rag_service failed: %s", exc, exc_info=True)

    try:
        classifier = _get_shared_classifier()
        readiness["classifier_ready"] = classifier is not None
    except Exception as exc:
        logger.warning("Case assistant prewarm: classifier failed: %s", exc, exc_info=True)

    try:
        from app.services.llm_factory import create_legal_llm

        # Warm exactly the same profile as fast-path uses to avoid cache misses
        # on the first in-request synthesis call.
        llm = create_legal_llm(
            temperature=0.0,
            use_rate_limiting=False,
            max_tokens=700,
        )
        readiness["legal_llm_ready"] = llm is not None
    except Exception as exc:
        logger.warning("Case assistant prewarm: legal_llm failed: %s", exc, exc_info=True)

    try:
        from app.services.yandex_embeddings import warmup_yandex_embeddings

        readiness["yandex_embeddings_ready"] = warmup_yandex_embeddings()
    except Exception as exc:
        logger.warning("Case assistant prewarm: yandex embeddings failed: %s", exc, exc_info=True)
        readiness["yandex_embeddings_ready"] = False

    try:
        from app.services.reranker_service import get_light_reranker_service

        reranker = get_light_reranker_service()
        if reranker._cross_encoder is not None:
            reranker._cross_encoder.predict([["prewarm", "prewarm query"]])
        readiness["reranker_ready"] = reranker._cross_encoder is not None
    except Exception as exc:
        logger.warning("Case assistant prewarm: reranker failed: %s", exc, exc_info=True)
        readiness["reranker_ready"] = False

    try:
        from app.services.document_converter_service import DocumentConverterService

        readiness["docling_ready"] = DocumentConverterService.warmup()
    except Exception as exc:
        logger.warning("Case assistant prewarm: docling failed: %s", exc, exc_info=True)
        readiness["docling_ready"] = False

    readiness["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return readiness
