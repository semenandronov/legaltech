"""
Assistant Chat V2 - Упрощённый thin controller

Использует ChatOrchestrator для обработки запросов.
Этот файл содержит только роутинг и парсинг запросов.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from typing import Optional, List, Dict, Any
from types import SimpleNamespace
import logging
import json
import asyncio
import re
import random
import uuid
import time

from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.chat import (
    ChatOrchestrator,
    ChatRequest,
    get_chat_orchestrator,
    ChatHistoryService,
)
from app.services.chat.events import SSESerializer
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.legal_quality_gates import LegalQualityGates
from app.services.chat.evidence_bundle import build_evidence_bundle, evidence_citations
from app.services.chat.session_context_retrieval import (
    align_budget_profile_with_session,
    session_context_meta_from_package,
)
from app.services.chat.session_context_service import (
    build_session_context_for_turn,
    refresh_session_context_after_turn,
)
from app.services.chat.assistant_turn_persistence import (
    GlobalAssistantPersistJob,
    assistant_async_persist_enabled,
    persist_global_assistant_sync,
    schedule_global_assistant_persist,
    should_sync_persist_before_finish,
)
from app.services.chat.metrics import get_metrics
from app.config import config
from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import (
    create_trace_context,
    end_trace,
    trace_event,
    trace_span,
    update_trace,
    set_active_trace_context,
    reset_active_trace_context,
    set_trace_span_parent,
    reset_trace_span_parent,
    normalize_trace_id,
    build_assistant_trace_metadata,
    trace_contract_event,
    normalize_observability_metadata,
    get_langchain_callbacks,
)
from app.services.observability.assistant_pipeline_langfuse_tracing import (
    assistant_step_span,
    record_execution_branch,
    turn_context_trace_fields,
)
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)
def _chunk_for_stream(text: str, max_len: int = 220) -> List[str]:
    """Split long text into UI-friendly SSE chunks."""
    src = (text or "").strip()
    if not src:
        return []
    parts = re.split(r"(?<=[\.\!\?\n])\s+", src)
    chunks: List[str] = []
    buf = ""
    for p in parts:
        piece = p.strip()
        if not piece:
            continue
        if not buf:
            buf = piece
            continue
        if len(buf) + 1 + len(piece) <= max_len:
            buf = f"{buf} {piece}"
        else:
            chunks.append(buf)
            buf = piece
    if buf:
        chunks.append(buf)
    return chunks


def _chunk_for_stream_preserve_newlines(text: str, max_len: int = 220) -> List[str]:
    """
    Split long text into UI-friendly chunks WITHOUT destroying Markdown formatting.

    Unlike `_chunk_for_stream()`, this function preserves `\n` and blank lines so
    that list/card formatting remains readable in the UI.
    """
    src = text or ""
    if not src:
        return []
    if len(src) <= max_len:
        return [src]
    chunks: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        j = min(i + max_len, n)
        if j >= n:
            chunks.append(src[i:])
            break
        window = src[i:j]
        # Prefer splitting on paragraph boundary, then newline, then space.
        cut = window.rfind("\n\n")
        if cut >= max_len // 3:
            j = i + cut + 2
        else:
            cut = window.rfind("\n")
            if cut >= max_len // 3:
                j = i + cut + 1
            else:
                cut = window.rfind(" ")
                if cut >= max_len // 2:
                    j = i + cut + 1
        piece = src[i:j]
        if piece:
            chunks.append(piece)
        i = j
    return chunks


def _reasoning_delta_from_chunk(msg_chunk: Any) -> str:
    """Extract reasoning delta from AIMessageChunk if provider sends it."""
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


def _text_delta_from_llm_chunk(msg_chunk: Any) -> str:
    """Текст из чанка ``astream`` (ChatOpenAI / ChatYandexOpenAI): message/content, список блоков."""
    try:
        base = getattr(msg_chunk, "message", None)
        if base is None:
            base = msg_chunk
        if isinstance(base, tuple) and base:
            base = base[0]
        content = getattr(base, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    t = item.get("text")
                    if isinstance(t, str) and t:
                        parts.append(t)
            return "".join(parts)
        if content is not None:
            s = str(content)
            if s and s != "None":
                return s
    except Exception:
        pass
    return ""


def _ainvoke_text(message: Any) -> str:
    """Текст из результата ``ainvoke`` (AIMessage / объект с полем content)."""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    c = getattr(message, "content", None)
    if isinstance(c, str) and c.strip():
        return c
    if isinstance(c, list):
        return _text_delta_from_llm_chunk(message)
    if c is not None:
        s = str(c).strip()
        return s if s and s != "None" else ""
    return ""


router = APIRouter(tags=["assistant-chat-v2"])


def _normalize_bool(value) -> bool:
    """Нормализовать значение к bool"""
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _context_pipeline_trace_extra(chat_request: ChatRequest) -> Dict[str, Any]:
    """Langfuse metadata for case context pipeline (secretary → recall → rerank)."""
    from app.config import config as _cfg

    extra: Dict[str, Any] = {
        "context_pipeline_enabled": bool(
            getattr(_cfg, "CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED", True)
        ),
        "rerank_model": getattr(_cfg, "RERANKER_MODEL_NAME", "") or "BAAI/bge-reranker-v2-m3",
    }
    bp = chat_request.budget_profile if isinstance(chat_request.budget_profile, dict) else {}
    if bp:
        if "recall_k" in bp:
            extra["recall_k"] = bp["recall_k"]
        if "final_k" in bp:
            extra["final_k"] = bp["final_k"]
    rt = chat_request.retrieval_task if isinstance(chat_request.retrieval_task, dict) else None
    if rt:
        extra["scope_mode"] = rt.get("scope_mode")
        extra["scoped_files_count"] = len(rt.get("file_ids") or [])
        extra["router_confidence"] = rt.get("confidence")
    return extra


def _should_sample_langfuse() -> bool:
    sample_rate = float(getattr(config, "LANGFUSE_SAMPLE_RATE", 1.0) or 1.0)
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    return random.random() <= sample_rate


def _probe_case_coverage(
    *,
    orchestrator: ChatOrchestrator,
    case_id: str,
    question: str,
    attached_file_ids: Optional[List[str]],
) -> tuple[int, bool]:
    """Quick retrieval probe for routing confidence."""
    try:
        docs = orchestrator.rag_service.retrieve_context(
            case_id=case_id,
            query=question,
            k=3,
            retrieval_strategy="simple",
            db=orchestrator.db,
            file_ids=attached_file_ids,
        )
        hits = len(docs or [])
        return hits, hits >= 2
    except Exception as probe_err:
        logger.debug("coverage probe failed: %s", probe_err)
        return 0, False


def _is_overview_query(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    markers = (
        "о чем документы",
        "о чем документ",
        "о чем все документы",
        "обзор документов",
        "обзор по документам",
        "по всем документам",
        "что в документах",
        "кратко по документам",
        "суммарно по документам",
        "summary документов",
    )
    return any(marker in q for marker in markers)


@router.post("/api/v2/assistant/chat/warmup")
async def assistant_chat_warmup(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Прогрев при открытии экрана чата по делу: кэш графа + чтение LangGraph checkpoint.
    Уменьшает задержку первого сообщения. Идемпотентно, без записи сообщений.
    Возвращает session_id (как у оркестратора), если клиент ещё не передал свой.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    case_id = body.get("case_id") or body.get("caseId")
    if not case_id:
        raise HTTPException(status_code=400, detail="case_id is required")
    raw_session = body.get("session_id") or body.get("sessionId")
    session_hint = (str(raw_session).strip() if raw_session else None) or None

    from app.services.langchain_agents.chat_graph_service import get_chat_graph_service

    svc = get_chat_graph_service(db=db)
    result = await svc.warmup_case_graph(
        str(case_id),
        current_user,
        session_id=session_hint,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return result


@router.post("/api/v2/assistant/chat")
async def assistant_chat_v2(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Streaming chat endpoint V2 (использует ChatOrchestrator)
    
    Accepts:
        - messages: array of {role, content}
        - case_id: ID дела
        - web_search: включить веб-поиск
        - legal_research: включить справочник (GLOBAL_LEGAL_CORPUS) в ответе по делу — только из тела запроса (тумблер UI).
        - use_legal_corpus: то же, что legal_research (совместимость с UI глобального ассистента)
        - deep_think: включить глубокое мышление
        - draft_mode: режим создания документа
        - document_context: контекст документа (для редактора)
        - document_id: ID документа
        - selected_text: выделенный текст
        - template_file_id: ID файла-шаблона
        - template_file_content: контент локального шаблона
        - attached_file_ids: прикреплённые файлы
        
    Returns:
        SSE stream с событиями
    """
    try:
        # Парсим тело запроса
        body = await request.json()

        # Извлекаем параметры
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        
        if not case_id:
            raise HTTPException(status_code=400, detail="case_id is required")

        try:
            from app.services.bm25_case_prewarm import schedule_bm25_prewarm

            schedule_bm25_prewarm(str(case_id))
        except Exception as bm25_sched_err:
            logger.debug("BM25 prewarm schedule on chat start skipped: %s", bm25_sched_err)

        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")

        # Legacy-флаги web_search/deep_think в контуре внутреннего ассистента отключены.
        requested_web_search = _normalize_bool(body.get("web_search", False))
        legal_research = _normalize_bool(body.get("legal_research", False))
        use_legal_corpus_body = _normalize_bool(body.get("use_legal_corpus", False))
        # Только тумблер в UI: legal_research и use_legal_corpus из тела запроса (без env-автовключения).
        legal_research = bool(legal_research or use_legal_corpus_body)
        requested_deep_think = _normalize_bool(body.get("deep_think", False))
        draft_mode = _normalize_bool(body.get("draft_mode", False))
        from app.services.chat.chat_instrument_policy import normalize_chat_instrument_flags

        court_practice = _normalize_bool(body.get("court_practice", False))
        draft_mode, legal_research, court_practice = normalize_chat_instrument_flags(
            draft_mode=draft_mode,
            legal_research=legal_research,
            use_legal_corpus=use_legal_corpus_body,
            court_practice=court_practice,
        )
        web_search = False
        deep_think = False
        if requested_web_search or requested_deep_think:
            logger.info(
                "assistant_chat_v2: legacy flags ignored (web_search=%s, deep_think=%s)",
                requested_web_search,
                requested_deep_think,
            )


        question = (last_message.get("content") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question is required")
        
        # Опциональные параметры
        document_context = body.get("document_context")
        document_id = body.get("document_id")
        selected_text = body.get("selected_text")
        editor_mode_hint = body.get("editor_mode_hint")  # 'edit' or 'ask' from UI toggle
        template_file_id = body.get("template_file_id")
        template_file_content = body.get("template_file_content")
        attached_file_ids = body.get("attached_file_ids")
        if attached_file_ids is not None and not isinstance(attached_file_ids, list):
            raise HTTPException(status_code=400, detail="attached_file_ids must be a list")
        session_id = body.get("session_id") or None
        mode = body.get("mode")
        corpus_size_hint = 0
        for _hint_key in ("corpus_size", "num_documents", "case_doc_count"):
            _raw_hint = body.get(_hint_key)
            if _raw_hint is None:
                continue
            try:
                corpus_size_hint = max(corpus_size_hint, int(_raw_hint))
            except (TypeError, ValueError):
                continue

        if attached_file_ids:
            logger.info(f"Attached file IDs: {attached_file_ids}")

        trace_id = normalize_trace_id(body.get("trace_id"))
        preview_run_ctx = ConversationPolicyService.build_run_context(
            session_id=session_id,
            user_id=str(current_user.id),
            scope="case",
            case_id=case_id,
            draft_mode=draft_mode,
            legal_research=legal_research,
            deep_think=deep_think,
            document_context=document_context,
            mode_hint=mode,
        )
        sampled = _should_sample_langfuse()
        trace_ctx = None
        http_trace_token = None
        if sampled:
            trace_ctx = create_trace_context(
                name="assistant_chat_v2",
                trace_id=trace_id,
                user_id=str(current_user.id),
                session_id=session_id,
                metadata=build_assistant_trace_metadata(
                    feature="case_assistant",
                    route="/api/v2/assistant/chat",
                    environment=getattr(config, "ENVIRONMENT", None),
                    model_provider=getattr(config, "LLM_PROVIDER", None),
                    case_id=case_id,
                    draft_mode=bool(draft_mode),
                    attached_files_count=len(attached_file_ids or []),
                    web_search=bool(web_search),
                    legal_research=bool(legal_research),
                    deep_think=bool(deep_think),
                    assistant_type="case_assistant",
                    mode=preview_run_ctx.mode,
                    execution_path="case_langgraph_v2",
                    scope_result="scope_pending",
                    citation_result="citation_pending",
                    confidence_result="confidence_pending",
                    tags=["assistant", "case_assistant", "in_case_chat"],
                    extra={
                        "mode_hint": editor_mode_hint,
                        "mode": mode,
                    },
                ),
                input_payload={"question": question[:3000]},
            )
            http_trace_token = set_active_trace_context(trace_ctx)
            trace_contract_event(
                trace_ctx,
                name="request_received",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "route": "/api/v2/assistant/chat",
                        "mode": preview_run_ctx.mode or "",
                        "case_id": case_id,
                        "session_id": session_id or "",
                    },
                    step_name="request_received",
                    status="success",
                ),
                input_payload={"question": question[:3000]},
            )

        orchestrator = get_chat_orchestrator(db)

        async def _case_chat_event_stream():
            from app.config import config as app_config
            from app.services.chat.assistant_activity import (
                activity_sse,
                build_analyzing_request_activity,
                build_request_accepted_activity,
                mark_step_completed,
            )
            from app.services.chat.case_chat_request_prep import (
                CaseChatPrepParams,
                prepare_case_chat_request,
            )

            if http_trace_token is not None:
                set_active_trace_context(trace_ctx)

            yield SSESerializer.trace(trace_id)
            if getattr(app_config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True):
                accepted = build_request_accepted_activity(question=question)
                yield activity_sse(accepted)
            await asyncio.sleep(0)

            try:
                if getattr(app_config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True):
                    yield activity_sse(
                        build_analyzing_request_activity(question=question)
                    )

                prep = prepare_case_chat_request(
                    db,
                    CaseChatPrepParams(
                        case_id=str(case_id),
                        question=question,
                        current_user=current_user,
                        session_id=session_id,
                        trace_id=trace_id,
                        preview_mode=preview_run_ctx.mode,
                        draft_mode=draft_mode,
                        legal_research=legal_research,
                        court_practice=court_practice,
                        deep_think=deep_think,
                        web_search=web_search,
                        document_context=document_context,
                        document_id=document_id,
                        selected_text=selected_text,
                        template_file_id=template_file_id,
                        template_file_content=template_file_content,
                        attached_file_ids=attached_file_ids,
                        editor_mode_hint=editor_mode_hint,
                        corpus_size_hint=corpus_size_hint,
                    ),
                )
                if getattr(app_config, "CASE_ASSISTANT_STREAM_ACTIVITY_UI", True):
                    yield activity_sse(
                        mark_step_completed(
                            build_analyzing_request_activity(question=question)
                        )
                    )
                    yield activity_sse(mark_step_completed(build_request_accepted_activity(question=question)))

                async for event in _stream_with_trace(
                    orchestrator=orchestrator,
                    chat_request=prep.chat_request,
                    trace_id=trace_id,
                    trace_ctx=trace_ctx,
                    http_trace_prepared=trace_ctx is not None,
                    skip_initial_trace=True,
                ):
                    yield event
            finally:
                if http_trace_token is not None:
                    reset_active_trace_context(http_trace_token)

        return StreamingResponse(
            _case_chat_event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in assistant_chat_v2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_with_trace(
    *,
    orchestrator: ChatOrchestrator,
    chat_request: ChatRequest,
    trace_id: str,
    trace_ctx=None,
    http_trace_prepared: bool = False,
    skip_initial_trace: bool = False,
):
    # Hard cutover: in-case assistant always uses LangGraph runtime.
    graph_v2_selected = True
    sampled = _should_sample_langfuse()
    if trace_ctx is None and sampled:
        trace_ctx = create_trace_context(
            name="assistant_chat_v2",
            trace_id=trace_id,
            user_id=str(chat_request.current_user.id),
            session_id=chat_request.session_id,
            metadata=build_assistant_trace_metadata(
                feature="case_assistant",
                route="/api/v2/assistant/chat",
                environment=getattr(config, "ENVIRONMENT", None),
                model_provider=getattr(config, "LLM_PROVIDER", None),
                case_id=chat_request.case_id,
                draft_mode=bool(chat_request.draft_mode),
                attached_files_count=len(chat_request.attached_file_ids or []),
                web_search=bool(chat_request.web_search),
                legal_research=bool(chat_request.legal_research),
                deep_think=bool(chat_request.deep_think),
                assistant_type="case_assistant",
                mode=chat_request.mode,
                execution_path="case_langgraph_v2",
                scope_result="scope_pending",
                citation_result="citation_pending",
                confidence_result="confidence_pending",
                tags=["assistant", "case_assistant", "in_case_chat"],
                extra={
                    "mode_hint": chat_request.editor_mode_hint,
                    "mode": chat_request.mode,
                    **_context_pipeline_trace_extra(chat_request),
                },
            ),
            input_payload={"question": chat_request.question[:3000]},
        )
    elif trace_ctx is not None:
        try:
            update_trace(
                trace_ctx,
                metadata=build_assistant_trace_metadata(
                    feature="case_assistant",
                    route="/api/v2/assistant/chat",
                    environment=getattr(config, "ENVIRONMENT", None),
                    model_provider=getattr(config, "LLM_PROVIDER", None),
                    case_id=chat_request.case_id,
                    draft_mode=bool(chat_request.draft_mode),
                    attached_files_count=len(chat_request.attached_file_ids or []),
                    web_search=bool(chat_request.web_search),
                    legal_research=bool(chat_request.legal_research),
                    deep_think=bool(chat_request.deep_think),
                    assistant_type="case_assistant",
                    mode=chat_request.mode,
                    execution_path="case_langgraph_v2",
                    scope_result="scope_pending",
                    citation_result="citation_pending",
                    confidence_result="confidence_pending",
                    tags=["assistant", "case_assistant", "in_case_chat"],
                    extra={
                        "mode_hint": chat_request.editor_mode_hint,
                        "mode": chat_request.mode,
                        **_context_pipeline_trace_extra(chat_request),
                    },
                ),
            )
        except Exception:
            logger.debug("case trace metadata enrich failed", exc_info=True)

    started = False
    response_chars = 0
    citations_count_seen = 0
    trace_finished = False
    trace_token = set_active_trace_context(trace_ctx) if trace_ctx is not None else None
    try:
        if not skip_initial_trace:
            yield SSESerializer.trace(trace_id)
        if not http_trace_prepared:
            trace_contract_event(
                trace_ctx,
                name="request_received",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "route": "/api/v2/assistant/chat",
                        "mode": chat_request.mode or "",
                        "case_id": chat_request.case_id,
                        "session_id": chat_request.session_id or "",
                        "task_type": chat_request.task_type or "",
                        "task_family": chat_request.task_family or "",
                        "depth_tier": chat_request.depth_tier or "",
                        "attached_files_count": len(chat_request.attached_file_ids or []),
                    },
                    step_name="request_received",
                    status="success",
                ),
                input_payload={"question": (chat_request.question or "")[:3000]},
            )
        process_span = trace_span(
            trace_ctx,
            name="case_chat_orchestrator_stream",
            metadata={"route": "/api/v2/assistant/chat"},
        )
        process_parent_token = (
            set_trace_span_parent(process_span) if process_span is not None else None
        )
        try:
            trace_contract_event(
                trace_ctx,
                name="request_routed",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "case_assistant",
                        "execution_path": "case_langgraph_v2",
                        "task_type": chat_request.task_type or "",
                        "depth_tier": chat_request.depth_tier or "",
                        "corpus_size": int(chat_request.corpus_size or 0),
                        "budget_profile_name": str((chat_request.budget_profile or {}).get("name") or ""),
                        "execution_tier": (chat_request.budget_profile or {}).get("execution_tier"),
                        "semantic_intent": chat_request.semantic_intent or "",
                        "probe_hits": int(chat_request.retrieval_probe_hits or 0),
                        "probe_covered": bool(chat_request.retrieval_probe_covered),
                        **turn_context_trace_fields(
                            (chat_request.budget_profile or {}).get("turn_context")
                        ),
                    },
                    step_name="graph_v2_selected",
                    status="success",
                ),
            )
            # Канонический путь: стримим напрямую из оркестратора.
            async for event in orchestrator.process_request(chat_request):
                if not started:
                    started = True
                    trace_contract_event(
                        trace_ctx,
                        name="llm_generation",
                        metadata=normalize_observability_metadata(
                            {"assistant_type": "case_assistant"},
                            step_name="stream_started",
                            status="running",
                        ),
                    )
                response_chars += len(event or "")
                # Best-effort: extract citations count from SSE stream so top-level request_completed
                # matches actual response payload.
                try:
                    if event and '"type": "citations"' in event:
                        for line in (event or "").splitlines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[len("data: ") :].strip()
                            if not payload or payload == "[DONE]":
                                continue
                            obj = json.loads(payload)
                            if obj.get("type") == "citations":
                                citations = obj.get("citations") or []
                                if isinstance(citations, list):
                                    citations_count_seen = len(citations)
                except Exception:
                    # Do not break the stream if parsing fails.
                    pass
                yield event
            if not response_chars:
                trace_contract_event(
                    trace_ctx,
                    name="quality_gate",
                    level="ERROR",
                    metadata=normalize_observability_metadata(
                        {
                            "assistant_type": "case_assistant",
                            "gate": "answer_generation",
                            "gate_status": "answer_generation_failed",
                            "mode": chat_request.mode or "",
                        },
                        step_name="answer_generation_gate",
                        status="blocked",
                        error="Empty SSE stream response",
                    ),
                )
                yield SSESerializer.status(
                    "quality_gate",
                    gate_status="answer_generation_failed",
                    gate_message="Ответ не сформирован. Попробуйте переформулировать запрос.",
                )
                yield SSESerializer.error("Ответ не сформирован")
                raise RuntimeError("Empty SSE stream response")
            if process_span:
                process_span.update(output={"sse_chars": response_chars})
        except Exception as stream_exc:
            if process_span:
                process_span.update(
                    level="ERROR",
                    status_message="stream_failed",
                    output={"error": str(stream_exc)},
                )
            raise
        finally:
            if process_parent_token is not None:
                reset_trace_span_parent(process_parent_token)
            if process_span:
                try:
                    process_span.end()
                except Exception:
                    logger.debug("case_chat_orchestrator_stream span end failed", exc_info=True)
        trace_contract_event(
            trace_ctx,
            name="request_completed",
            metadata=normalize_observability_metadata(
                {
                    "assistant_type": "case_assistant",
                    "mode": chat_request.mode or "",
                    "session_id": chat_request.session_id or "",
                    "task_type": chat_request.task_type or "",
                    "task_family": chat_request.task_family or "",
                    "depth_tier": chat_request.depth_tier or "",
                    "corpus_size": int(chat_request.corpus_size or 0),
                    "budget_profile_name": str((chat_request.budget_profile or {}).get("name") or ""),
                },
                step_name="case_stream_complete",
                status="success",
                citations_count=citations_count_seen,
            ),
            output_payload={"sse_chars": response_chars},
        )
        end_trace(
            trace_ctx,
            status="success",
            output_payload={"sse_chars": response_chars},
            metadata={"sampled": sampled, "stream_started": started, "scope_result": "passed"},
        )
        trace_finished = True
    except Exception as exc:
        trace_event(
            trace_ctx,
            name="case_chat_stream_error",
            level="ERROR",
            metadata={"error": str(exc)},
        )
        trace_contract_event(
            trace_ctx,
            name="request_completed",
            level="ERROR",
            metadata=normalize_observability_metadata(
                {
                    "assistant_type": "case_assistant",
                    "mode": chat_request.mode or "",
                    "session_id": chat_request.session_id or "",
                },
                step_name="case_stream_complete",
                status="error",
                error=str(exc),
            ),
        )
        end_trace(
            trace_ctx,
            status="error",
            error=str(exc),
            metadata={"sampled": sampled, "stream_started": started},
        )
        trace_finished = True
        raise
    finally:
        if not trace_finished:
            end_trace(
                trace_ctx,
                status="success",
                output_payload={"sse_chars": response_chars},
                metadata={"sampled": sampled, "stream_started": started},
            )
        if trace_token is not None:
            reset_active_trace_context(trace_token)


@router.get("/api/v2/assistant/chat/{case_id}/sessions")
async def get_chat_sessions_v2(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить список сессий чата для дела
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).options(
            load_only(Case.id, Case.user_id),
        ).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем сессии через сервис
        history_service = ChatHistoryService(db)
        sessions = history_service.get_sessions_for_case(case_id)
        
        return {"sessions": sessions}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/assistant/chat/{case_id}/history")
async def get_chat_history_v2(
    case_id: str,
    session_id: Optional[str] = None,
    all_sessions: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить историю сообщений чата
    
    Args:
        case_id: ID дела
        session_id: ID конкретной сессии (опционально)
        all_sessions: Вернуть сообщения из всех сессий
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).options(
            load_only(Case.id, Case.user_id),
        ).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем историю через сервис
        history_service = ChatHistoryService(db)
        
        if all_sessions:
            messages = history_service.get_session_history(case_id, session_id=None)
        else:
            messages = history_service.get_session_history(case_id, session_id=session_id)
        
        # Форматируем сообщения
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "source_references": msg.source_references,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "session_id": msg.session_id
            })
        
        return {"messages": formatted_messages}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v2/assistant/chat/{case_id}/sessions/{session_id}")
async def delete_chat_session_v2(
    case_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Удалить сессию чата
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).options(
            load_only(Case.id, Case.user_id),
        ).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Удаляем сессию через сервис
        history_service = ChatHistoryService(db)
        deleted_count = history_service.delete_session(case_id, session_id)
        
        return {"deleted": deleted_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v2/assistant/global-chat")
async def assistant_global_chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Global assistant chat endpoint (LangGraph multi-source pipeline)."""
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage
    from app.services.chat.global_langgraph_service import GlobalAssistantLangGraphService
    from datetime import datetime

    try:
        # IMPORTANT: StreamingResponse may continue after request-scoped SQLAlchemy
        # session is closed. Keep only primitive user id for stream lifecycle.
        current_user_id = str(current_user.id)

        body = await request.json()
        messages = body.get("messages", [])
        session_id = body.get("session_id")
        file_contexts = list(body.get("file_contexts", []))
        draft_mode = _normalize_bool(body.get("draft_mode", False))
        draft_approved = _normalize_bool(body.get("draft_approved", False))
        draft_modifications = (body.get("draft_modifications") or "").strip()
        draft_plan = body.get("draft_plan") if isinstance(body.get("draft_plan"), dict) else None
        attached_file_ids = body.get("attached_file_ids") or []
        requested_use_legal_corpus = _normalize_bool(body.get("use_legal_corpus", False))
        from app.services.chat.chat_instrument_policy import normalize_chat_instrument_flags

        requested_court_practice = _normalize_bool(body.get("court_practice", False))
        draft_mode, use_legal_corpus, court_practice = normalize_chat_instrument_flags(
            draft_mode=draft_mode,
            use_legal_corpus=requested_use_legal_corpus,
            court_practice=requested_court_practice,
        )
        use_legal_corpus = bool(use_legal_corpus)
        court_practice = bool(court_practice)
        trace_id = normalize_trace_id(body.get("trace_id"))
        sampled = _should_sample_langfuse()
        preview_global_ctx = ConversationPolicyService.build_run_context(
            session_id=session_id,
            user_id=current_user_id,
            scope="global",
            draft_mode=bool(draft_mode),
            draft_approved=bool(draft_approved),
            legal_research=bool(use_legal_corpus),
            mode_hint=body.get("mode"),
        )
        trace_ctx = None
        http_trace_token = None
        if sampled:
            trace_ctx = create_trace_context(
                name="assistant_global_chat_v2",
                trace_id=trace_id,
                user_id=current_user_id,
                session_id=session_id,
                metadata=build_assistant_trace_metadata(
                    feature="global_assistant",
                    route="/api/v2/assistant/global-chat",
                    environment=getattr(config, "ENVIRONMENT", None),
                    model_provider=config.LLM_PROVIDER,
                    draft_mode=bool(draft_mode),
                    draft_approved=bool(draft_approved),
                    attached_files_count=len(attached_file_ids) if isinstance(attached_file_ids, list) else 0,
                    assistant_type="global_assistant",
                    mode=preview_global_ctx.mode,
                    execution_path=preview_global_ctx.execution_path,
                    scope_result="scope_pending",
                    citation_result="citation_pending",
                    confidence_result="confidence_pending",
                    tags=["assistant", "global_assistant"],
                    extra={"use_legal_corpus": bool(use_legal_corpus)},
                ),
                input_payload={"question": (messages[-1].get("content", "") if messages else "")[:3000]},
            )
            trace_contract_event(
                trace_ctx,
                name="request_received",
                metadata=normalize_observability_metadata(
                    {"assistant_type": "global_assistant", "route": "/api/v2/assistant/global-chat"},
                    step_name="request_received",
                    status="success",
                ),
            )
            http_trace_token = set_active_trace_context(trace_ctx)

        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")

        question = (last_message.get("content") or "").strip()

        try:
            with assistant_step_span(
                "global",
                "http.request_prep",
                input_payload={"question_chars": len(question)},
            ) as global_prep_out:
                if attached_file_ids:
                    with assistant_step_span(
                        "global",
                        "http.load_attached_files",
                        input_payload={"attached_count": len(attached_file_ids)},
                    ) as files_out:
                        from app.models.case import File as CaseFile

                        loaded = 0
                        for fid in attached_file_ids:
                            file_obj = db.query(CaseFile).filter(CaseFile.id == fid).first()
                            if file_obj and file_obj.original_text:
                                file_contexts.append(
                                    {
                                        "filename": file_obj.filename,
                                        "text": file_obj.original_text[:12000],
                                        "file_id": fid,
                                        "case_id": str(file_obj.case_id) if file_obj.case_id else None,
                                    }
                                )
                                loaded += 1
                        files_out["loaded_count"] = loaded

                with assistant_step_span("global", "http.get_or_create_session") as sess_out:
                    session = None
                    if session_id:
                        session = db.query(GlobalAssistantSession).filter(
                            GlobalAssistantSession.id == session_id,
                            GlobalAssistantSession.user_id == current_user_id,
                        ).first()
                    if not session:
                        session = GlobalAssistantSession(
                            user_id=current_user_id,
                            title=question[:200] if question else "Новый чат",
                        )
                        db.add(session)
                        db.commit()
                        db.refresh(session)
                    sess_out["session_id"] = session.id

                with assistant_step_span("global", "http.save_user_message") as user_out:
                    db.add(GlobalAssistantMessage(session_id=session.id, role="user", content=question))
                    db.commit()
                    user_out["saved"] = True
                current_session_id = session.id

                from app.services.chat.dialog_transcript_service import (
                    build_chat_history,
                    build_global_turn_messages,
                    load_global_chat_history,
                )

                with assistant_step_span("global", "http.load_transcript") as tx_out:
                    matter_contexts = [
                        {
                            "file_id": fc.get("file_id"),
                            "filename": fc.get("filename", "Документ"),
                            "text": fc.get("text", ""),
                            "case_id": fc.get("case_id"),
                        }
                        for fc in file_contexts
                        if fc.get("text")
                    ]
                    db_transcript = load_global_chat_history(db, current_session_id)
                    chat_history = build_chat_history(db_transcript, pending_question=question)
                    canonical_messages = None
                    if bool(getattr(config, "GLOBAL_ASSISTANT_CHECKPOINT_MESSAGES_ENABLED", True)):
                        canonical_messages = build_global_turn_messages(db_transcript, question)
                    tx_out["transcript_turns"] = len(db_transcript or [])
                global_prep_out["session_id"] = current_session_id
        finally:
            if http_trace_token is not None:
                reset_active_trace_context(http_trace_token)

        langgraph_enabled = bool(getattr(config, "GLOBAL_ASSISTANT_LANGGRAPH_ENABLED", True))

        async def generate():
            full_response = ""
            citations_out: List[Dict[str, Any]] = []
            persist_committed = False
            stream_started = False
            trace_finished = False
            trace_token = set_active_trace_context(trace_ctx) if trace_ctx is not None else None
            process_span = trace_span(
                trace_ctx,
                name="global_chat_orchestrator_stream",
                metadata={"route": "/api/v2/assistant/global-chat"},
            )
            process_parent_token = (
                set_trace_span_parent(process_span) if process_span is not None else None
            )
            try:
                yield SSESerializer.trace(trace_id)
                yield SSESerializer.session(current_session_id)
                stream_started = True
                trace_contract_event(
                    trace_ctx,
                    name="request_routed",
                    metadata=normalize_observability_metadata(
                        {
                            "assistant_type": "global_assistant",
                            "execution_path": preview_global_ctx.execution_path,
                            "mode": preview_global_ctx.mode or "",
                            "use_legal_corpus": bool(use_legal_corpus),
                            "court_practice": bool(court_practice),
                            "draft_mode": bool(draft_mode),
                        },
                        step_name="global_stream_selected",
                        status="success",
                    ),
                )
                trace_contract_event(
                    trace_ctx,
                    name="llm_generation",
                    metadata=normalize_observability_metadata(
                        {"assistant_type": "global_assistant"},
                        step_name="global_stream_started",
                        status="running",
                    ),
                )

                if not langgraph_enabled:
                    record_execution_branch(
                        "global",
                        branch="langgraph_disabled",
                        reason="config",
                    )
                    trace_event(
                        trace_ctx,
                        name="global_chat_langgraph_disabled",
                        metadata={"langgraph_enabled": False},
                    )
                    fallback = (
                        "LangGraph orchestration для глобального ассистента отключен конфигурацией. "
                        "Включите GLOBAL_ASSISTANT_LANGGRAPH_ENABLED=true."
                    )
                    full_response = fallback
                    yield SSESerializer.text_delta(fallback)
                    return

                run_ctx = ConversationPolicyService.build_run_context(
                    session_id=current_session_id,
                    user_id=current_user_id,
                    scope="global",
                    matter_context=matter_contexts,
                    draft_mode=bool(draft_mode),
                    draft_approved=bool(draft_approved),
                    legal_research=bool(use_legal_corpus),
                    mode_hint=body.get("mode"),
                )
                scope_gate = LegalQualityGates.scope_gate(run_ctx)
                get_metrics().record_mode_eval(run_ctx.mode, "scope_gate", scope_gate.allowed)
                if not scope_gate.allowed:
                    yield SSESerializer.error(scope_gate.message or "Scope gate blocked request")
                    return
                trace_event(
                    trace_ctx,
                    name="policy_scope_gate",
                    metadata={
                        "result": scope_gate.status,
                        "mode": run_ctx.mode,
                        "execution_path": run_ctx.execution_path,
                    },
                )

                session_context_prompt = ""
                session_context_meta: Dict[str, Any] = {}
                recap_done = False
                with assistant_step_span(
                    "global",
                    "session_context.build",
                    input_payload={"question_chars": len(question)},
                ) as sc_out:
                    try:
                        from app.utils.database import SessionLocal

                        resolve_db = SessionLocal()
                        try:
                            session_ctx = build_session_context_for_turn(
                                resolve_db,
                                scope="global",
                                question=question,
                                session_id=current_session_id,
                            )
                            session_context_prompt = session_ctx.prompt_block or ""
                            session_context_meta = session_context_meta_from_package(session_ctx)
                            session_reply = session_ctx.evidence_replay
                            if bool(
                                getattr(config, "GLOBAL_ASSISTANT_CHECKPOINT_MESSAGES_ENABLED", True)
                            ) and not bool(
                                getattr(config, "GLOBAL_ASSISTANT_TRANSCRIPT_REPLAY_ENABLED", False)
                            ):
                                session_reply = None
                        finally:
                            resolve_db.close()
                        sc_out["has_evidence_replay"] = session_reply is not None
                        if session_reply is not None:
                            full_response = session_reply.content
                            citations_out = session_reply.citations
                            route_decision = f"session_context_{session_reply.resolution_kind}"
                            record_execution_branch(
                                "global",
                                branch="session_evidence_replay",
                                reason=str(session_reply.resolution_kind or ""),
                                metadata={"route_decision": route_decision},
                            )
                            result = SimpleNamespace(
                                response=full_response,
                                citations=citations_out,
                                route_confidence=1.0,
                                route_decision=route_decision,
                                answer_status="ready",
                                draft_plan_id=None,
                                draft_plan=None,
                                answer_system_prompt="",
                                answer_user_prompt="",
                            )
                            recap_done = True
                            sc_out["recap_done"] = True
                    except Exception as recap_err:
                        logger.warning("global session context assembly failed: %s", recap_err)
                        session_context_prompt = ""
                        session_context_meta = {}

                if not recap_done:
                    record_execution_branch(
                        "global",
                        branch="langgraph",
                        reason=str(run_ctx.mode or "global_chat"),
                    )
                    service = GlobalAssistantLangGraphService()
                    timeout_sec = int(getattr(config, "GLOBAL_ASSISTANT_GRAPH_TIMEOUT_SEC", 360) or 360)
                    stream_graph_progress = bool(
                        getattr(config, "GLOBAL_ASSISTANT_STREAM_GRAPH_PROGRESS", True)
                    )
                    with assistant_step_span(
                        "global",
                        "langgraph.run",
                        metadata={
                            "timeout_sec": timeout_sec,
                            "stream_graph_progress": stream_graph_progress,
                        },
                    ) as lg_out:
                        run_span = trace_span(
                            trace_ctx,
                            name="global_chat_langgraph_run",
                            metadata={
                                "timeout_sec": timeout_sec,
                                "stream_graph_progress": stream_graph_progress,
                            },
                        )
                        graph_kwargs = dict(
                            user_query=question,
                            chat_history=chat_history,
                            draft_mode=draft_mode,
                            draft_approved=draft_approved,
                            draft_modifications=draft_modifications,
                            draft_plan=draft_plan,
                            use_legal_corpus=use_legal_corpus,
                            use_court_practice=court_practice,
                            matter_contexts=matter_contexts,
                            user_id=current_user_id,
                            thread_id=f"global_{current_session_id}",
                            mode=run_ctx.mode,
                            session_context_prompt=session_context_prompt or None,
                            session_context_meta=session_context_meta or None,
                            canonical_messages=canonical_messages,
                        )
                        try:
                            result = None
                            graph_started = time.monotonic()
                            if stream_graph_progress:
                                async for graph_event in service.stream(**graph_kwargs):
                                    if (time.monotonic() - graph_started) > timeout_sec:
                                        raise asyncio.TimeoutError()
                                    if graph_event.phase:
                                        yield SSESerializer.status(
                                            "routing",
                                            route=graph_event.phase[:160],
                                            phase=graph_event.phase[:160],
                                        )
                                    if graph_event.result is not None:
                                        result = graph_event.result
                                        break
                                if result is None:
                                    raise RuntimeError("Global graph stream ended without result")
                            else:
                                result = await asyncio.wait_for(
                                    service.run(**graph_kwargs),
                                    timeout=timeout_sec,
                                )
                            lg_out["answer_status"] = result.answer_status
                            lg_out["citations_count"] = len(result.citations or [])
                            if run_span:
                                run_span.update(
                                    output={
                                        "answer_status": result.answer_status,
                                        "citations_count": len(result.citations or []),
                                    }
                                )
                        except asyncio.TimeoutError:
                            logger.error("Global chat LangGraph timeout after %ss", timeout_sec)
                            if run_span:
                                run_span.update(
                                    level="ERROR",
                                    status_message="timeout",
                                    output={"timeout_sec": timeout_sec},
                                )
                            yield SSESerializer.error(
                                "Ассистент слишком долго обрабатывал запрос. Уточните вопрос или повторите попытку."
                            )
                            return
                        finally:
                            if run_span:
                                try:
                                    run_span.end()
                                except Exception:
                                    logger.debug("global_chat_langgraph_run span end failed", exc_info=True)

                full_response = result.response or ""
                if draft_mode and not draft_approved:
                    if not (result.answer_status == "plan_ready" and result.draft_plan_id and result.draft_plan):
                        # Hard gate safety: in draft mode without approval we always return plan_ready,
                        # never stream draft text in the same request.
                        fallback_plan = result.draft_plan or {
                            "reasoning": "Перед генерацией черновика требуется одобрение плана юристом.",
                            "goals": [{"description": f"Подготовить черновик по запросу: {question[:280]}"}],
                            "steps": [
                                {"description": "Проверить исходные материалы и применимые нормы."},
                                {"description": "Согласовать структуру документа с юристом."},
                                {"description": "После одобрения — сгенерировать черновик без домысливания фактов."},
                            ],
                            "questions_for_lawyer": [
                                "Подтвердите структуру документа перед генерацией черновика.",
                            ],
                        }
                        plan_payload = {
                            "type": "plan_ready",
                        "draft_state": "plan_ready",
                            "planId": result.draft_plan_id or f"global-plan-{current_session_id}",
                            "plan": fallback_plan,
                        }
                        trace_event(
                            trace_ctx,
                            name="global_chat_plan_ready_fallback",
                            metadata={"has_plan_id": bool(result.draft_plan_id)},
                        )
                        yield f"data: {json.dumps(plan_payload, ensure_ascii=False)}\n\n"
                        return

                if result.answer_status == "plan_ready" and result.draft_plan_id and result.draft_plan:
                    # UI safety: send a visible text chunk before plan payload so the user
                    # always sees assistant feedback even if plan card rendering fails.
                    plan_notice = (
                        "План подготовлен. Проверьте шаги и подтвердите, "
                        "чтобы я сгенерировал черновик."
                    )
                    yield SSESerializer.text_delta(plan_notice)
                    plan_payload = {
                        "type": "plan_ready",
                        "draft_state": "plan_ready",
                        "planId": result.draft_plan_id,
                        "plan": result.draft_plan,
                    }
                    trace_event(
                        trace_ctx,
                        name="global_chat_plan_ready",
                        metadata={"plan_id": result.draft_plan_id},
                    )
                    yield f"data: {json.dumps(plan_payload, ensure_ascii=False)}\n\n"
                    return
                if result.answer_status == "ready_to_generate":
                    system_prompt = (result.answer_system_prompt or "").strip()
                    user_prompt = (result.answer_user_prompt or "").strip()
                    trace_contract_event(
                        trace_ctx,
                        name="prompt_prepared",
                        metadata=normalize_observability_metadata(
                            {
                                "assistant_type": "global_assistant",
                                "route_decision": result.route_decision,
                                "answer_status": result.answer_status,
                            },
                            step_name="global_prompt_prepared",
                            status="success",
                        ),
                        input_payload={
                            "system_prompt": system_prompt,
                            "user_prompt": user_prompt,
                        },
                    )
                    if not system_prompt or not user_prompt:
                        trace_event(
                            trace_ctx,
                            name="global_chat_generation_prompt_missing",
                            level="ERROR",
                        )
                        yield SSESerializer.error("Не удалось подготовить промпт для потоковой генерации.")
                        return

                    llm = create_legal_llm(use_rate_limiting=False)
                    callbacks = get_langchain_callbacks(
                        session_id=current_session_id,
                        user_id=current_user_id,
                        tags=["assistant", "global_assistant", "generation"],
                    )
                    yield SSESerializer.status("draft_state", draft_state="approved")
                    reasoning_progressive = ""
                    gen_messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt),
                    ]
                    # In court_practice-only mode we buffer generation first to enforce format contract,
                    # then stream the final (possibly retried) text to the UI.
                    # If the current turn is an in-thread clarification, do not enforce
                    # the "precedent finder" format contract — we are replaying / clarifying
                    # prior content from the same chat, not generating a new court-practice подборку.
                    thread_clarify = False
                    try:
                        from app.services.chat.session_context_retrieval import is_memory_only_turn

                        thread_clarify = is_memory_only_turn(session_context_meta or None)
                    except Exception:
                        thread_clarify = False

                    strict_court_practice = bool(
                        court_practice and not use_legal_corpus and not draft_mode and not thread_clarify
                    )
                    with assistant_step_span(
                        "global",
                        "generation.stream",
                        metadata={"provider": config.LLM_PROVIDER},
                    ) as gen_step_out:
                        generation_span = trace_span(
                            trace_ctx,
                            name="global_chat_generation_stream",
                            metadata={"provider": config.LLM_PROVIDER},
                        )
                        try:
                            if strict_court_practice:
                                from app.services.chat.court_practice_answer_contract import (
                                    extract_case_numbers_from_citations,
                                )

                                # 1) First pass (buffered)
                                inv = await llm.ainvoke(
                                    gen_messages,
                                    config={"callbacks": callbacks} if callbacks else None,
                                )
                                full_response = _ainvoke_text(inv) or ""

                                # 2) Quality gate + optional retry once
                                available_cases = extract_case_numbers_from_citations(result.citations or [])
                                cp_gate = LegalQualityGates.court_practice_answer_gate(
                                    run_ctx,
                                    answer_text=full_response,
                                    citations=list(result.citations or []),
                                    enabled=True,
                                    strict_mode=True,
                                    available_case_numbers=available_cases,
                                )
                                trace_contract_event(
                                    trace_ctx,
                                    name="quality_gate",
                                    metadata=normalize_observability_metadata(
                                        {
                                            "assistant_type": "global_assistant",
                                            "gate": "court_practice_contract",
                                            "gate_status": cp_gate.status,
                                        },
                                        step_name="court_practice_contract_gate",
                                        status="passed" if cp_gate.allowed else "blocked",
                                        citations_count=len(result.citations or []),
                                    ),
                                    output_payload={"metrics": cp_gate.metadata or {}, "message": cp_gate.message or ""},
                                )
                                if not cp_gate.allowed:
                                    repair_sys = (
                                        "Ты — редактор ответа режима «подбор судебной практики».\n"
                                        "Перепиши ответ так, чтобы он строго соответствовал контракту:\n"
                                        "- Только подборка судебных актов (карточки дел), без советов/рекомендаций.\n"
                                        "- 2–6 карточек дел.\n"
                                        "- Каждая карточка начинается bullet‑строкой с номером дела и [N].\n"
                                        "- Внутри: «Что решил/сказал суд» (2–4 предложения, строго по источнику, [N]) "
                                        "и «Почему релевантно» (1–2 предложения без домыслов).\n"
                                        "- Все существенные тезисы — со ссылками [N].\n"
                                        "Не добавляй новые факты."
                                    )
                                    repair_user = (
                                        f"Доступные дела из источников: {', '.join(available_cases) if available_cases else '[не удалось извлечь номера]'}\n\n"
                                        f"Исходный ответ:\n{full_response}\n"
                                    )
                                    inv2 = await llm.ainvoke(
                                        [SystemMessage(content=repair_sys), HumanMessage(content=repair_user)],
                                        config={"callbacks": callbacks} if callbacks else None,
                                    )
                                    full_response = _ainvoke_text(inv2) or full_response

                                # 3) Stream final text in chunks (UX-friendly)
                                for text_chunk in _chunk_for_stream_preserve_newlines(full_response, max_len=220) or [full_response]:
                                    if text_chunk:
                                        yield SSESerializer.text_delta(text_chunk)
                                        await asyncio.sleep(0)
                            else:
                                async for chunk in llm.astream(
                                    gen_messages,
                                    config={"callbacks": callbacks} if callbacks else None,
                                ):
                                    r_delta = _reasoning_delta_from_chunk(chunk)
                                    if config.YANDEX_SSE_STREAM_MODEL_REASONING and r_delta:
                                        reasoning_progressive += r_delta
                                        yield SSESerializer.reasoning(
                                            phase="model_reasoning",
                                            step=1,
                                            total_steps=1,
                                            content=reasoning_progressive,
                                        )

                                    token = _text_delta_from_llm_chunk(chunk)
                                    if token:
                                        full_response += token
                                        yield SSESerializer.text_delta(token)
                            if reasoning_progressive.strip():
                                trace_contract_event(
                                    trace_ctx,
                                    name="llm_generation",
                                    metadata=normalize_observability_metadata(
                                        {"assistant_type": "global_assistant"},
                                        step_name="model_reasoning_stream",
                                        status="success",
                                    ),
                                    output_payload={"reasoning_content": reasoning_progressive},
                                )
                            if generation_span:
                                generation_span.update(
                                    output={
                                        "response_chars": len(full_response),
                                        "has_reasoning_stream": bool(reasoning_progressive.strip()),
                                        "strict_court_practice": bool(strict_court_practice),
                                    }
                                )
                            gen_step_out["response_chars"] = len(full_response)
                        finally:
                            if generation_span:
                                try:
                                    generation_span.end()
                                except Exception:
                                    logger.debug("global_chat_generation_stream span end failed", exc_info=True)
                    if not (full_response or "").strip() and not strict_court_practice:
                        try:
                            inv = await llm.ainvoke(
                                gen_messages,
                                config={"callbacks": callbacks} if callbacks else None,
                            )
                            fb = _ainvoke_text(inv)
                            if fb:
                                full_response = fb
                                yield SSESerializer.text_delta(fb)
                        except Exception as inv_err:
                            logger.warning(
                                "global_chat generation ainvoke fallback failed: %s",
                                inv_err,
                                exc_info=True,
                            )
                    if not (full_response or "").strip():
                        # Fallback: do not leave UI with an empty assistant bubble.
                        if reasoning_progressive.strip():
                            fallback = (
                                "Модель не вернула финальный текст ответа. "
                                "Попробуйте переформулировать запрос или повторить попытку."
                            )
                            full_response = fallback
                            yield SSESerializer.text_delta(fallback)
                        else:
                            if trace_ctx and not trace_finished:
                                end_trace(
                                    trace_ctx,
                                    status="error",
                                    error="empty_generation_stream",
                                    metadata={"sampled": sampled, "stream_started": stream_started},
                                )
                                trace_finished = True
                            yield SSESerializer.error("Модель не вернула текст ответа.")
                        return
                elif full_response:
                    # Fallback for non-streamable branches
                    text_chunks = _chunk_for_stream_preserve_newlines(full_response, max_len=220)
                    if not text_chunks:
                        yield SSESerializer.text_delta(full_response)
                    else:
                        for text_chunk in text_chunks:
                            yield SSESerializer.text_delta(text_chunk)
                            await asyncio.sleep(0)

                citations_out = result.citations or []
                if citations_out:
                    yield SSESerializer.citations(citations_out)
                citation_gate = LegalQualityGates.citation_gate(run_ctx, citations_out)
                trace_contract_event(
                    trace_ctx,
                    name="quality_gate",
                    metadata=normalize_observability_metadata(
                        {
                            "assistant_type": "global_assistant",
                            "gate": "citation",
                            "gate_status": citation_gate.status,
                        },
                        step_name="citation_gate",
                        status="passed" if citation_gate.allowed else "blocked",
                        citations_count=len(citations_out or []),
                    ),
                )
                if not citation_gate.allowed and not (recap_done and citations_out):
                    yield SSESerializer.status(
                        "quality_gate",
                        gate_status=citation_gate.status,
                        gate_message=citation_gate.message,
                    )
                    yield SSESerializer.text_delta(citation_gate.message or "")
                get_metrics().record_mode_eval(run_ctx.mode, "citation_gate", citation_gate.allowed)
                confidence_gate = LegalQualityGates.confidence_gate(
                    run_ctx,
                    confidence_score=float(result.route_confidence or 0.0),
                    retrieval_hits=len(citations_out or []),
                )
                trace_contract_event(
                    trace_ctx,
                    name="quality_gate",
                    metadata=normalize_observability_metadata(
                        {
                            "assistant_type": "global_assistant",
                            "gate": "confidence",
                            "gate_status": confidence_gate.status,
                        },
                        step_name="confidence_gate",
                        status="passed" if confidence_gate.allowed else "blocked",
                        citations_count=len(citations_out or []),
                    ),
                )
                get_metrics().record_mode_eval(run_ctx.mode, "confidence_gate", confidence_gate.allowed)
                if not confidence_gate.allowed:
                    yield SSESerializer.status(
                        "quality_gate",
                        gate_status=confidence_gate.status,
                        gate_message=confidence_gate.message,
                    )
                trace_event(
                    trace_ctx,
                    name="policy_citation_gate",
                    metadata={
                        "result": citation_gate.status,
                        "citations_count": len(citations_out or []),
                    },
                )
                if full_response and should_sync_persist_before_finish():
                    persist_job = GlobalAssistantPersistJob(
                        session_id=current_session_id,
                        content=full_response,
                        citations=list(citations_out or []),
                        last_user=question,
                        last_assistant=full_response,
                    )
                    persist_committed = persist_global_assistant_sync(persist_job)
                yield SSESerializer.finish()

            except Exception as e:
                logger.error("Global chat LangGraph error: %s", e, exc_info=True)
                end_trace(
                    trace_ctx,
                    status="error",
                    error=str(e),
                    metadata={"sampled": sampled, "stream_started": stream_started},
                )
                trace_finished = True
                yield SSESerializer.error(str(e))
            finally:
                if full_response and not persist_committed:
                    with assistant_step_span(
                        "global",
                        "persist.assistant_message",
                        input_payload={"content_chars": len(full_response)},
                    ) as persist_out:
                        persist_job = GlobalAssistantPersistJob(
                            session_id=current_session_id,
                            content=full_response,
                            citations=list(citations_out or []),
                            last_user=question,
                            last_assistant=full_response,
                        )
                        if assistant_async_persist_enabled():
                            schedule_global_assistant_persist(persist_job)
                            persist_out["persist_mode"] = "async"
                            trace_contract_event(
                                trace_ctx,
                                name="response_persist_scheduled",
                                metadata=normalize_observability_metadata(
                                    {
                                        "assistant_type": "global_assistant",
                                        "session_id": current_session_id,
                                        "persist_mode": "async",
                                    },
                                    step_name="save_assistant_message",
                                    status="scheduled",
                                    citations_count=len(citations_out or []),
                                ),
                                output_payload={"content_chars": len(full_response)},
                            )
                        else:
                            try:
                                save_span = trace_span(trace_ctx, name="global_chat_save_assistant_message")
                                from app.utils.database import SessionLocal

                                save_db = SessionLocal()
                                try:
                                    evidence_bundle = build_evidence_bundle(citations=citations_out or [])
                                    asst_msg = GlobalAssistantMessage(
                                        session_id=current_session_id,
                                        role="assistant",
                                        content=full_response,
                                        reasoning_steps=[
                                            {
                                                "phase": "citations",
                                                "step": 1,
                                                "totalSteps": 1,
                                                "content": json.dumps(citations_out, ensure_ascii=False),
                                            }
                                        ]
                                        if citations_out
                                        else None,
                                        evidence=evidence_bundle,
                                    )
                                    save_db.add(asst_msg)
                                    save_db.query(GlobalAssistantSession).filter(
                                        GlobalAssistantSession.id == current_session_id
                                    ).update({"updated_at": datetime.utcnow()})
                                    save_db.commit()
                                    refresh_session_context_after_turn(
                                        save_db,
                                        scope="global",
                                        session_id=current_session_id,
                                        last_user=question,
                                        last_assistant=full_response,
                                    )
                                    persist_out["persist_mode"] = "sync"
                                    if save_span:
                                        save_span.update(
                                            output={
                                                "saved": True,
                                                "session_id": current_session_id,
                                                "content_chars": len(full_response),
                                            }
                                        )
                                finally:
                                    save_db.close()
                                    if save_span:
                                        try:
                                            save_span.end()
                                        except Exception:
                                            logger.debug(
                                                "global_chat_save_assistant_message span end failed",
                                                exc_info=True,
                                            )
                            except Exception as save_err:
                                logger.error("Failed to save global assistant message: %s", save_err)
                                trace_event(
                                    trace_ctx,
                                    name="global_chat_save_failed",
                                    level="ERROR",
                                    metadata={"error": str(save_err)},
                                )
                if full_response and not trace_finished:
                    citation_result = "pending"
                    confidence_result = "pending"
                    if "citation_gate" in locals():
                        citation_result = "passed" if citation_gate.allowed else citation_gate.status
                    if "confidence_gate" in locals():
                        confidence_result = "passed" if confidence_gate.allowed else confidence_gate.status
                    trace_contract_event(
                        trace_ctx,
                        name="request_completed",
                        metadata=normalize_observability_metadata(
                            {
                                "assistant_type": "global_assistant",
                                "route_decision": result.route_decision if 'result' in locals() else None,
                                "answer_status": result.answer_status if 'result' in locals() else None,
                            },
                            step_name="global_request_completed",
                            status="success",
                            citations_count=len(citations_out or []),
                        ),
                        output_payload={"response_chars": len(full_response)},
                    )
                    end_trace(
                        trace_ctx,
                        status="success",
                        output_payload={"response_chars": len(full_response)},
                        metadata={
                            "sampled": sampled,
                            "stream_started": stream_started,
                            "scope_result": "passed",
                            "citation_result": citation_result,
                            "confidence_result": confidence_result,
                        },
                    )
                    trace_finished = True
                if not trace_finished:
                    end_trace(
                        trace_ctx,
                        status="success",
                        output_payload={"response_chars": 0},
                        metadata={"sampled": sampled, "stream_started": stream_started},
                    )
                if process_parent_token is not None:
                    reset_trace_span_parent(process_parent_token)
                if process_span:
                    try:
                        process_span.update(output={"response_chars": len(full_response or "")})
                        process_span.end()
                    except Exception:
                        logger.debug(
                            "global_chat_orchestrator_stream span end failed",
                            exc_info=True,
                        )
                if trace_token is not None:
                    reset_active_trace_context(trace_token)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Global chat error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v2/assistant/upload-file")
async def upload_file_for_assistant(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Extract text from an uploaded file and store it in DB for document preview.
    Returns file_id, filename, file_type, text, char_count.
    """
    from app.services.langchain_loaders import DocumentLoaderService
    from app.models.case import GlobalAssistantFile

    filename = file.filename or "document"
    content = await file.read()

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {
        "pdf",
        "docx",
        "txt",
        "csv",
        "xlsx",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "bmp",
        "tif",
        "tiff",
        "gif",
    }
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    if len(content) > config.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {config.MAX_FILE_SIZE // (1024 * 1024)} MB)",
        )

    try:
        documents = DocumentLoaderService.load_document(content, filename)
        text = "\n\n".join(doc.page_content for doc in documents if doc.page_content.strip())
        if len(text) > 100_000:
            text = text[:100_000] + "\n\n[...документ обрезан для контекста...]"

        # Store file in DB so it can be previewed later
        db_file = GlobalAssistantFile(
            user_id=current_user.id,
            filename=filename,
            file_type=ext,
            file_content=content,
            original_text=text,
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        return {"file_id": db_file.id, "filename": filename, "file_type": ext, "text": text, "char_count": len(text)}
    except Exception as e:
        logger.error(f"File extraction error for {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Не удалось извлечь текст из файла: {e}")


@router.post("/api/v2/assistant/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Transcribe audio using GigaChat SmartSpeech STT API.
    Expects a WAV file (PCM 16-bit, 16kHz mono).
    Returns { text: "transcribed text" }.
    """
    import asyncio
    import requests as sync_requests
    import uuid
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        content = await audio.read()
    except Exception as e:
        logger.error(f"[STT] Failed to read audio: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать аудиофайл: {e}")

    logger.info(f"[STT] Received audio file: {len(content)} bytes, filename={audio.filename}")

    # Strip WAV header (44 bytes standard, but check RIFF magic to be safe)
    if content[:4] == b'RIFF':
        pcm_data = content[44:]
        logger.info(f"[STT] Stripped WAV header, PCM size: {len(pcm_data)} bytes")
    else:
        pcm_data = content
        logger.info(f"[STT] No WAV header detected, using raw data: {len(pcm_data)} bytes")

    if not pcm_data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл")

    stt_creds = config.GIGACHAT_STT_CREDENTIALS
    if not stt_creds:
        raise HTTPException(status_code=503, detail="STT credentials not configured")

    # Run synchronous requests in a thread pool to avoid blocking the event loop
    def _get_token() -> str:
        resp = sync_requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {stt_creds}",
            },
            data={"scope": "SALUTE_SPEECH_PERS"},
            timeout=15,
            verify=False,
        )
        logger.info(f"[STT] Token response: {resp.status_code}, body: {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _recognize(token: str, pcm: bytes) -> str:
        resp = sync_requests.post(
            "https://smartspeech.sber.ru/rest/v1/speech:recognize",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "audio/x-pcm;bit=16;rate=16000",
            },
            data=pcm,
            timeout=30,
            verify=False,
        )
        logger.info(f"[STT] STT response: {resp.status_code}, body: {resp.text[:300]}")
        if resp.status_code != 200:
            raise ValueError(f"SmartSpeech вернул {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
        if isinstance(result.get("result"), list) and result["result"]:
            return result["result"][0]
        return result.get("text", "")

    try:
        access_token = await asyncio.to_thread(_get_token)
    except Exception as e:
        logger.error(f"[STT] Token error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Не удалось получить токен STT: {e}")

    try:
        text = await asyncio.to_thread(_recognize, access_token, pcm_data)
        logger.info(f"[STT] Transcribed: {repr(text[:100])}")
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[STT] Recognition error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Ошибка распознавания речи: {e}")


@router.get("/api/v2/assistant/files")
async def list_assistant_files(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List uploaded global assistant files (mirrors /api/cases/{id}/files structure)."""
    from app.models.case import GlobalAssistantFile
    files = db.query(GlobalAssistantFile).filter(
        GlobalAssistantFile.user_id == current_user.id
    ).order_by(GlobalAssistantFile.created_at.desc()).all()
    return {
        "documents": [
            {"id": f.id, "filename": f.filename, "file_type": f.file_type}
            for f in files
        ]
    }


@router.get("/api/v2/assistant/files/{file_id}/content")
async def get_assistant_file_content(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve raw file bytes for a global assistant file."""
    from app.models.case import GlobalAssistantFile
    from fastapi.responses import Response
    f = db.query(GlobalAssistantFile).filter(
        GlobalAssistantFile.id == file_id,
        GlobalAssistantFile.user_id == current_user.id,
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not f.file_content:
        raise HTTPException(status_code=404, detail="File content not stored")

    mime_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media_type = mime_map.get(f.file_type.lower(), "application/octet-stream")
    return Response(content=f.file_content, media_type=media_type)


@router.get("/api/v2/assistant/files/{file_id}/html")
async def get_assistant_file_html(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return HTML version of a DOCX global assistant file."""
    from app.models.case import GlobalAssistantFile
    f = db.query(GlobalAssistantFile).filter(
        GlobalAssistantFile.id == file_id,
        GlobalAssistantFile.user_id == current_user.id,
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Return cached HTML if available
    if f.html_content:
        return {"html": f.html_content, "cached": True, "file_id": file_id, "filename": f.filename}

    # Generate HTML from DOCX
    if f.file_type.lower() == "docx" and f.file_content:
        try:
            import mammoth, io
            result = mammoth.convert_to_html(io.BytesIO(f.file_content))
            html = result.value
            # Cache it
            f.html_content = html
            db.commit()
            return {"html": html, "cached": False, "file_id": file_id, "filename": f.filename}
        except Exception as e:
            logger.error(f"HTML conversion error for global file {file_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to convert DOCX to HTML")

    raise HTTPException(status_code=400, detail="HTML preview not available for this file type")


@router.post("/api/v2/assistant/download-docx")
async def download_draft_as_docx(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Convert draft document text to .docx and return for download."""
    from docx import Document as DocxDocument
    from docx.shared import Pt
    import io
    import re
    from fastapi.responses import Response

    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"download-docx: failed to parse JSON body: {e}")
        raise

    title = body.get("title", "Документ").strip()
    content = (body.get("content") or "").strip()
    content_type = body.get("content_type", "markdown")

    logger.info(f"download-docx: title={repr(title)}, content_type={content_type}, content_len={len(content)}")

    if not content:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "content is empty"}, status_code=400)

    try:
        doc = DocxDocument()

        # Title
        heading = doc.add_heading(title, level=0)
        if heading.runs:
            heading.runs[0].font.size = Pt(16)

        if content_type == "html":
            # Parse HTML content (from TipTap editor)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'hr'], recursive=True):
                if tag.parent and tag.parent.name in ['ul', 'ol']:
                    continue  # handled by parent
                if tag.name in ['h1', 'h2', 'h3', 'h4']:
                    level = int(tag.name[1])
                    h = doc.add_heading(tag.get_text(strip=True), level=min(level + 1, 9))
                    if h.runs:
                        h.runs[0].font.size = Pt(max(14 - (level - 1) * 2, 10))
                elif tag.name == 'p':
                    text = tag.get_text(strip=True)
                    if text:
                        doc.add_paragraph(text)
                elif tag.name in ['ul', 'ol']:
                    for li in tag.find_all('li', recursive=False):
                        prefix = '• ' if tag.name == 'ul' else ''
                        doc.add_paragraph(f"{prefix}{li.get_text(strip=True)}")
                elif tag.name == 'hr':
                    doc.add_paragraph('─' * 40)
        else:
            # Parse markdown content (legacy)
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for para_text in paragraphs:
                if para_text.startswith("**") and para_text.endswith("**") and "\n" not in para_text:
                    h = doc.add_heading(para_text.strip("*").strip(), level=2)
                    h.runs[0].font.size = Pt(12)
                else:
                    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", para_text)
                    doc.add_paragraph(clean)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        import urllib.parse
        safe_title = re.sub(r'[^\w\s-]', '', title)[:60] or "document"
        ascii_title = safe_title.encode('ascii', 'ignore').decode().strip() or "document"
        encoded_title = urllib.parse.quote(safe_title.encode('utf-8'))
        content_disposition = f"attachment; filename=\"{ascii_title}.docx\"; filename*=UTF-8''{encoded_title}.docx"
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": content_disposition},
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"download-docx: failed to generate DOCX: {e}\n{tb}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e), "traceback": tb}, status_code=500)


@router.get("/api/v2/assistant/global-sessions")
async def get_global_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List global assistant sessions for the current user, newest first."""
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage
    from sqlalchemy import func

    sessions = (
        db.query(GlobalAssistantSession)
        .filter(GlobalAssistantSession.user_id == current_user.id)
        .order_by(GlobalAssistantSession.updated_at.desc())
        .limit(50)
        .all()
    )

    result = []
    for s in sessions:
        msg_count = db.query(func.count(GlobalAssistantMessage.id)).filter(
            GlobalAssistantMessage.session_id == s.id
        ).scalar() or 0
        result.append({
            "session_id": s.id,
            "title": s.title or "Без названия",
            "message_count": msg_count,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })

    return result


@router.get("/api/v2/assistant/global-sessions/{session_id}")
async def get_global_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all messages for a global assistant session."""
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage

    session = db.query(GlobalAssistantSession).filter(
        GlobalAssistantSession.id == session_id,
        GlobalAssistantSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(GlobalAssistantMessage).filter(
        GlobalAssistantMessage.session_id == session_id
    ).order_by(GlobalAssistantMessage.created_at).all()

    return {
        "session_id": session.id,
        "title": session.title,
        "draft_title": session.draft_title,
        "draft_content": session.draft_content,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }


@router.patch("/api/v2/assistant/global-sessions/{session_id}/draft")
async def save_session_draft(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save or update the draft document associated with a global assistant session."""
    from app.models.case import GlobalAssistantSession
    body = await request.json()
    draft_title = body.get("draft_title", "")
    draft_content = body.get("draft_content", "")

    session = db.query(GlobalAssistantSession).filter(
        GlobalAssistantSession.id == session_id,
        GlobalAssistantSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.draft_title = draft_title
    session.draft_content = draft_content
    db.commit()
    return {"ok": True}


@router.get("/api/v2/recent-activity")
async def get_recent_activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return aggregated recent activity across all entity types for the current user,
    sorted by last-activity date (newest first).

    Entity types:
    - case_chat: in-case assistant session
    - global_chat: global (case-free) assistant session
    - tabular_review: tabular review project
    """
    from app.models.case import Case, ChatMessage, GlobalAssistantSession
    from app.models.tabular_review import TabularReview
    from sqlalchemy import func, desc

    PREVIEW = 80
    items = []

    # ── 1. Case chat sessions ──
    session_agg = (
        db.query(
            ChatMessage.case_id,
            ChatMessage.session_id,
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .join(Case, Case.id == ChatMessage.case_id)
        .filter(
            Case.user_id == current_user.id,
            ChatMessage.session_id.isnot(None),
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
        )
        .group_by(ChatMessage.case_id, ChatMessage.session_id)
        .order_by(desc("last_at"))
        .limit(limit)
        .all()
    )

    if session_agg:
        case_ids = list({r.case_id for r in session_agg})
        cases_map = {
            c.id: (c.title or "Дело")
            for c in db.query(Case).filter(Case.id.in_(case_ids)).all()
        }
        for row in session_agg:
            first_msg = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.case_id == row.case_id,
                    ChatMessage.session_id == row.session_id,
                    ChatMessage.role == "user",
                    ChatMessage.content.isnot(None),
                    ChatMessage.content != "",
                )
                .order_by(ChatMessage.created_at.asc())
                .first()
            )
            content = first_msg.content if first_msg else ""
            title = content[:PREVIEW] + ("…" if len(content) > PREVIEW else "")
            items.append({
                "type": "case_chat",
                "id": row.session_id,
                "title": title or "Чат",
                "case_id": row.case_id,
                "case_name": cases_map.get(row.case_id, "Дело"),
                "updated_at": row.last_at.isoformat() if row.last_at else None,
            })

    # ── 2. Global assistant sessions ──
    global_sessions = (
        db.query(GlobalAssistantSession)
        .filter(GlobalAssistantSession.user_id == current_user.id)
        .order_by(desc(GlobalAssistantSession.updated_at))
        .limit(limit)
        .all()
    )
    for s in global_sessions:
        items.append({
            "type": "global_chat",
            "id": s.id,
            "title": s.title or "Новый чат",
            "case_id": None,
            "case_name": None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })

    # ── 3. Tabular reviews ──
    reviews_q = (
        db.query(TabularReview, Case.title.label("case_title"))
        .join(Case, Case.id == TabularReview.case_id)
        .filter(TabularReview.user_id == current_user.id)
        .order_by(desc(TabularReview.updated_at))
        .limit(limit)
        .all()
    )
    for review, case_title in reviews_q:
        items.append({
            "type": "tabular_review",
            "id": review.id,
            "title": review.name or "Таблица",
            "case_id": review.case_id,
            "case_name": case_title or "Дело",
            "updated_at": review.updated_at.isoformat() if review.updated_at else None,
        })

    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"items": items[:limit]}
