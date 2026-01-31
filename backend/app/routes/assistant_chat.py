"""Assistant UI chat endpoint for streaming responses"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import AsyncGenerator, Optional, Literal, List
import hashlib
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel, ChatMessage
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_memory import MemoryService
from app.services.llm_factory import create_llm, create_legal_llm
# Agents removed - using simple RAG chat only
from app.services.external_sources.web_research_service import get_web_research_service
from app.services.external_sources.source_router import get_source_router, initialize_source_router
from app.services.external_sources.cache_manager import get_cache_manager
# REMOVED: PipelineService, PlanningAgent, AdvancedPlanningAgent - не используются
from app.services.langchain_agents.chat_graph_service import ChatGraphService, get_chat_graph_service
from app.services.thinking_service import get_thinking_service, ThinkingStep
from app.core.container import get_rag_service, get_document_processor, get_memory_service
from app.config import config
import json
import logging
import asyncio
import re
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize classification cache
_classification_cache = None


def get_classification_cache():
    """Get or create classification cache manager"""
    global _classification_cache
    if _classification_cache is None:
        from app.config import config
        redis_url = getattr(config, 'REDIS_URL', None)
        ttl = getattr(config, 'CACHE_TTL_SECONDS', 3600)
        _classification_cache = get_cache_manager(redis_url=redis_url, default_ttl=ttl)
    return _classification_cache


class AssistantMessage(BaseModel):
    """Message model for assistant-ui"""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


class ClassificationResult(BaseModel):
    """Результат классификации запроса пользователя"""
    label: Literal["task", "question"] = Field(..., description="Метка классификации: task или question")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уровень уверенности от 0.0 до 1.0")
    rationale: Optional[str] = Field(None, description="Краткое объяснение решения классификации")


# Note: Request body is parsed manually to support assistant-ui format
# Assistant-ui sends: { messages: [...], case_id: "..." }


def normalize_text(text: str) -> str:
    """
    Нормализует текст для кэширования: lower, strip, убирает лишние пробелы
    
    Args:
        text: Исходный текст
        
    Returns:
        Нормализованный текст
    """
    return " ".join(text.lower().strip().split())


def make_classification_cache_key(question: str) -> str:
    """
    Создает cache key для результата классификации
    
    Args:
        question: Входной вопрос
        
    Returns:
        Cache key (хеш нормализованного текста)
    """
    normalized = normalize_text(question)
    key_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return f"classification:{key_hash}"


async def classify_request(question: str, llm) -> bool:
    """
    Использует LLM для определения, является ли запрос задачей для выполнения анализов
    или обычным вопросом для RAG чата.
    
    Args:
        question: Текст запроса пользователя
        llm: LLM для классификации
    
    Returns:
        True если это задача, False если вопрос
    """
    # 1. Нормализация входного текста
    normalized_question = normalize_text(question)
    question_lower = normalized_question.lower()
    
    # 2. Rule-based проверка (fast path)
    # Паттерны для запросов статей кодексов - всегда QUESTION
    article_patterns = [
        r'статья\s+\d+\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
        r'\d+\s+статья\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
        r'статья\s+\d+\s+(гражданск|арбитраж|уголовн|налогов|трудов|семейн|жилищн|земельн|конституционн)',
        r'пришли\s+статью',
        r'покажи\s+статью',
        r'найди\s+статью',
        r'текст\s+статьи',
    ]
    
    for pattern in article_patterns:
        if re.search(pattern, question_lower):
            logger.info(f"Pre-classified '{question[:50]}...' as QUESTION (matches article request pattern: {pattern})")
            return False
    
    # Паттерны для приветствий - всегда QUESTION
    greeting_patterns = [
        r'^(привет|здравствуй|здравствуйте|добрый\s+(день|вечер|утро)|hello|hi)',
    ]
    
    for pattern in greeting_patterns:
        if re.search(pattern, question_lower):
            logger.info(f"Pre-classified '{question[:50]}...' as QUESTION (matches greeting pattern: {pattern})")
            return False
    
    # 3. Проверка кэша
    cache = get_classification_cache()
    cached_result = cache.get("classification", normalized_question)
    
    if cached_result:
        label = cached_result.get("label", "question")
        cached_confidence = cached_result.get("confidence", 1.0)
        logger.info(f"Cache hit for classification: '{question[:50]}...' -> {label} (confidence: {cached_confidence:.2f})")
        return label == "task"
    
    # 4. LLM классификация с structured output
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    
    # Получаем список доступных агентов для промпта
    from app.services.langchain_agents.legacy_stubs import AVAILABLE_ANALYSES
    
    agents_list = []
    for agent_name, agent_info in AVAILABLE_ANALYSES.items():
        description = agent_info["description"]
        keywords = ", ".join(agent_info["keywords"][:3])  # Первые 3 ключевых слова
        agents_list.append(f"- {agent_name}: {description} (ключевые слова: {keywords})")
    
    agents_text = "\n".join(agents_list)
    
    # Few-shot примеры для классификации
    few_shot_examples = [
        (HumanMessage(content="Запрос: Извлеки все даты из документов"), 
         AIMessage(content='{"label": "task", "confidence": 0.95, "rationale": "Требует выполнения агента entity_extraction"}')),
        (HumanMessage(content="Запрос: Какие ключевые сроки важны в этом деле?"), 
         AIMessage(content='{"label": "question", "confidence": 0.98, "rationale": "Информационный вопрос для RAG чата"}')),
        (HumanMessage(content="Запрос: Пришли статью 135 ГПК"), 
         AIMessage(content='{"label": "question", "confidence": 0.99, "rationale": "Запрос на получение текста статьи кодекса"}')),
        (HumanMessage(content="Запрос: Найди противоречия между документами"), 
         AIMessage(content='{"label": "task", "confidence": 0.92, "rationale": "Требует выполнения агента discrepancy"}')),
        (HumanMessage(content="Запрос: Что говорится в договоре о сроках?"), 
         AIMessage(content='{"label": "question", "confidence": 0.96, "rationale": "Вопрос о содержании документов для RAG"}')),
        (HumanMessage(content="Запрос: Составь таблицу с судьями и судами"), 
         AIMessage(content='{"label": "task", "confidence": 0.94, "rationale": "Требует создания структурированной таблицы через агентов"}')),
    ]
    
    system_content = f"""Ты классификатор запросов пользователя в системе анализа юридических документов.

В системе доступны следующие агенты для выполнения задач:

{agents_text}

Дополнительные агенты:
- document_classifier: Классификация документов (договор/письмо/привилегированный)
- entity_extraction: Извлечение сущностей (имена, организации, суммы, даты)
- privilege_check: Проверка привилегий документов

Определи тип запроса:

ЗАДАЧА (task) - если запрос требует выполнения одного из доступных агентов:
- Запрос относится к функциям агентов (извлечение дат, поиск противоречий, анализ рисков и т.д.)
- Требует запуска фонового анализа через агентов
- НЕ относится к простым запросам на получение информации (статьи кодексов, тексты документов)
- Примеры: "Извлеки все даты из документов", "Найди противоречия", "Проанализируй риски", "Создай резюме дела", "составь таблицу с судьями и судами"

ВОПРОС (question) - если это обычный вопрос для RAG чата:
- Вопросы с "какие", "что", "где", "когда", "кто", "почему"
- Разговорные фразы: "как дела", "привет"
- Запросы на получение информации (статьи кодексов, норм права, текстов документов)
- Требует немедленного ответа на основе уже загруженных документов или юридических источников
- Примеры: "Какие ключевые сроки важны в этом деле?", "Что говорится в договоре о сроках?", "Пришли статью 135 ГПК", "Покажи текст статьи 123 ГК РФ"

Возвращай строго JSON с полями:
- label: "task" или "question"
- confidence: число от 0.0 до 1.0 (уверенность в классификации)
- rationale: краткое объяснение решения (1-2 предложения)

Отвечай ТОЛЬКО валидным JSON, без дополнительного текста."""
    
    # Создаем промпт с few-shot примерами
    messages = [SystemMessage(content=system_content)]
    for human_msg, ai_msg in few_shot_examples:
        messages.append(human_msg)
        messages.append(ai_msg)
    messages.append(HumanMessage(content=f"Запрос: {question}"))
    
    try:
        # Используем structured output если поддерживается
        if hasattr(llm, 'with_structured_output'):
            try:
                structured_llm = llm.with_structured_output(ClassificationResult, include_raw=True)
                response = structured_llm.invoke(messages)
                
                if hasattr(response, 'parsed') and response.parsed:
                    classification = response.parsed
                elif isinstance(response, dict) and 'parsed' in response:
                    classification = response['parsed']
                elif isinstance(response, ClassificationResult):
                    classification = response
                else:
                    # Fallback: парсим raw ответ
                    raw_content = getattr(response, 'raw', None) or (response.get('raw') if isinstance(response, dict) else str(response))
                    logger.warning(f"Structured output parsing failed, using raw response: {raw_content}")
                    raise ValueError("Failed to parse structured output")
                
                label = classification.label
                confidence = classification.confidence
                rationale = classification.rationale or ""
                
            except Exception as structured_error:
                logger.warning(f"Structured output failed: {structured_error}, falling back to JSON parsing")
                # Fallback на обычный вызов и парсинг JSON
                response = llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Пытаемся извлечь JSON из ответа
                import json
                try:
                    # Ищем JSON в ответе
                    json_match = re.search(r'\{[^}]+\}', response_text)
                    if json_match:
                        result_dict = json.loads(json_match.group())
                        label = result_dict.get("label", "question")
                        confidence = float(result_dict.get("confidence", 0.5))
                        rationale = result_dict.get("rationale", "")
                    else:
                        raise ValueError("No JSON found in response")
                except Exception as json_error:
                    logger.error(f"JSON parsing failed: {json_error}, response: {response_text}")
                    # Последний fallback: простой текстовый парсинг
                    response_lower = response_text.lower()
                    if "task" in response_lower and response_lower.find("task") < response_lower.find("question", response_lower.find("task")):
                        label = "task"
                        confidence = 0.5
                    else:
                        label = "question"
                        confidence = 0.5
                    rationale = ""
        else:
            # LLM не поддерживает structured output, используем обычный вызов
            response = llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            import json
            try:
                json_match = re.search(r'\{[^}]+\}', response_text)
                if json_match:
                    result_dict = json.loads(json_match.group())
                    label = result_dict.get("label", "question")
                    confidence = float(result_dict.get("confidence", 0.5))
                    rationale = result_dict.get("rationale", "")
                else:
                    raise ValueError("No JSON found in response")
            except Exception:
                response_lower = response_text.lower()
                if "task" in response_lower:
                    label = "task"
                    confidence = 0.5
                else:
                    label = "question"
                    confidence = 0.5
                rationale = ""
        
        # 5. Обработка confidence threshold
        if confidence >= 0.85:
            # Высокая уверенность - принимаем результат
            final_label = label
        elif confidence >= 0.6:
            # Средняя уверенность - принимаем, но логируем
            final_label = label
            logger.info(f"Medium confidence classification: '{question[:50]}...' -> {label} (confidence: {confidence:.2f})")
        else:
            # Низкая уверенность - fallback на безопасную метку
            final_label = "question"
            logger.warning(f"Low confidence classification for '{question[:50]}...': {label} (confidence: {confidence:.2f}), falling back to 'question'")
            rationale = f"Low confidence ({confidence:.2f}), fallback to question"
        
        # 6. Сохранение в кэш
        cache_data = {
            "label": final_label,
            "confidence": confidence,
            "rationale": rationale
        }
        cache.set("classification", normalized_question, cache_data, ttl=3600)
        
        # 7. Логирование и возврат результата
        logger.info(f"Classified '{question[:50]}...' as {final_label.upper()} (confidence: {confidence:.2f}, rationale: {rationale[:50] if rationale else 'N/A'})")
        return final_label == "task"
        
    except Exception as e:
        logger.error(f"Error in LLM classification: {e}", exc_info=True)
        logger.warning("LLM classification failed, defaulting to QUESTION")
        # Сохраняем ошибку в кэш с коротким TTL, чтобы не повторять неудачные вызовы
        cache_data = {"label": "question", "confidence": 0.5, "rationale": f"Error: {str(e)[:50]}"}
        cache.set("classification", normalized_question, cache_data, ttl=60)
        return False


# REMOVED: stream_chat_response function (1044 строки) - не используется, заменена на ChatGraphService


@router.post("/api/assistant/chat")
async def assistant_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Streaming chat endpoint for assistant-ui
    
    Uses RAG only - simple question answering without agents.
    Accepts request body with messages array and case_id
    Returns Server-Sent Events (SSE) stream
    """
    try:
        # Parse request body
        body = await request.json()
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        web_search_raw = body.get("web_search", False)
        # Normalize web_search to boolean
        if isinstance(web_search_raw, str):
            web_search = web_search_raw.lower() in ("true", "1", "yes")
        else:
            web_search = bool(web_search_raw)
        legal_research_raw = body.get("legal_research", False)
        # Normalize legal_research to boolean
        if isinstance(legal_research_raw, str):
            legal_research = legal_research_raw.lower() in ("true", "1", "yes")
        else:
            legal_research = bool(legal_research_raw)
        deep_think = body.get("deep_think", False)
        draft_mode_raw = body.get("draft_mode", False)
        # Normalize draft_mode to boolean
        if isinstance(draft_mode_raw, str):
            draft_mode = draft_mode_raw.lower() in ("true", "1", "yes")
        else:
            draft_mode = bool(draft_mode_raw)
        
        # Document editor context (optional)
        document_context = body.get("document_context")
        document_id = body.get("document_id")
        selected_text = body.get("selected_text")
        
        # Template file ID for draft mode (optional) - для файлов из БД
        template_file_id = body.get("template_file_id")
        # Template file content for draft mode (optional) - для локальных файлов
        template_file_content = body.get("template_file_content")
        
        # Attached file IDs for regular messages (optional) - для явного указания файлов
        attached_file_ids = body.get("attached_file_ids")
        if attached_file_ids:
            logger.info(f"Attached file IDs received: {attached_file_ids}")
        
        if not case_id:
            raise HTTPException(status_code=400, detail="case_id is required")
        
        # Get last user message
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        question = last_message.get("content", "")
        
        # Use ChatGraphService for streaming responses
        rag_service = get_rag_service()  # Lazy initialization
        document_processor = get_document_processor()  # Lazy initialization
        chat_service = get_chat_graph_service(db, rag_service, document_processor)
        
        return StreamingResponse(
            chat_service.stream_response(
                case_id=case_id,
                question=question,
                user=current_user,
                deep_think=deep_think,
                legal_research=legal_research,
                draft_mode=draft_mode,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in assistant_chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/assistant/chat/resume-draft")
async def resume_draft(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint для подтверждения/отмены создания документа (HITL).
    
    Используется когда граф прерывается перед созданием документа (draft mode).
    Пользователь может подтвердить или отменить операцию.
    """
    try:
        body = await request.json()
        case_id = body.get("case_id") or body.get("caseId")
        thread_id = body.get("thread_id")
        approved = body.get("approved", True)
        
        if not case_id:
            raise HTTPException(status_code=400, detail="case_id is required")
        if not thread_id:
            raise HTTPException(status_code=400, detail="thread_id is required")
        
        # Use ChatGraphService for resuming draft
        rag_service = get_rag_service()
        document_processor = get_document_processor()
        chat_service = get_chat_graph_service(db, rag_service, document_processor)
        
        return StreamingResponse(
            chat_service.resume_draft(
                case_id=case_id,
                thread_id=thread_id,
                approved=approved,
                user=current_user
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in resume_draft endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/assistant/chat/{case_id}/sessions")
async def get_chat_sessions_for_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of chat sessions for a specific case
    
    Returns: list of sessions with session_id, first_message, last_message, last_message_at, message_count
    """
    # Check if case exists and verify ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        from sqlalchemy import func, desc
        
        # Get all unique session_ids for this case
        sessions_query = db.query(
            ChatMessage.session_id,
            func.min(ChatMessage.created_at).label('first_message_at'),
            func.max(ChatMessage.created_at).label('last_message_at'),
            func.count(ChatMessage.id).label('message_count')
        ).filter(
            ChatMessage.case_id == case_id,
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
            ChatMessage.session_id.isnot(None)
        ).group_by(ChatMessage.session_id).order_by(desc('last_message_at')).all()
        
        sessions = []
        for session_row in sessions_query:
            session_id = session_row.session_id
            
            # Get first and last messages for preview
            first_message = db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.session_id == session_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.asc()).first()
            
            last_message = db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.session_id == session_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            first_message_preview = ""
            if first_message and first_message.content:
                first_message_preview = first_message.content[:100]
                if len(first_message.content) > 100:
                    first_message_preview += "..."
            
            last_message_preview = ""
            if last_message and last_message.content:
                last_message_preview = last_message.content[:100]
                if len(last_message.content) > 100:
                    last_message_preview += "..."
            
            sessions.append({
                "session_id": session_id,
                "first_message": first_message_preview,
                "last_message": last_message_preview,
                "first_message_at": first_message.created_at.isoformat() if first_message and first_message.created_at else None,
                "last_message_at": last_message.created_at.isoformat() if last_message and last_message.created_at else None,
                "message_count": session_row.message_count
            })
        
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"Error getting chat sessions for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get chat sessions")


@router.get("/api/assistant/chat/{case_id}/history")
async def get_assistant_chat_history(
    case_id: str,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get chat history for assistant chat
    
    Args:
        case_id: Case identifier
        session_id: Optional session ID to filter messages by session. If not provided, returns all messages for the case.
    
    Returns: list of messages with role, content, sources, created_at, session_id
    """
    # Check if case exists and verify ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get messages - фильтруем пустые сообщения и по session_id если указан
    query = db.query(ChatMessage).filter(
        ChatMessage.case_id == case_id,
        ChatMessage.content.isnot(None),
        ChatMessage.content != ""
    )
    
    if session_id:
        query = query.filter(ChatMessage.session_id == session_id)
    
    messages = query.order_by(ChatMessage.created_at.asc()).all()
    
    return {
        "messages": [
            {
                "role": msg.role,
                "content": msg.content or "",
                "sources": msg.source_references if msg.source_references is not None else [],
                "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat(),
                "session_id": msg.session_id
            }
            for msg in messages
        ]
    }


class SaveWorkflowMessageRequest(BaseModel):
    """Request model for saving workflow result as a chat message"""
    case_id: str = Field(..., description="Идентификатор дела")
    content: str = Field(..., description="Содержимое сообщения")
    workflow_id: Optional[str] = Field(None, description="Идентификатор workflow")
    workflow_name: Optional[str] = Field(None, description="Название workflow")
    artifacts: Optional[dict] = Field(None, description="Артефакты workflow (таблицы, документы и т.д.)")


@router.post("/api/assistant/chat/workflow-message")
async def save_workflow_message(
    request: SaveWorkflowMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Save workflow result as a chat message in history.
    
    This endpoint is called after workflow completion to persist the result
    in chat history so it appears when user returns to chat.
    """
    import uuid
    
    # Check if case exists and verify ownership
    case = db.query(Case).filter(
        Case.id == request.case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        # Generate new session_id for workflow result
        session_id = f"workflow-{request.workflow_id or uuid.uuid4()}"
        
        # Save assistant message with workflow result
        message_id = str(uuid.uuid4())
        chat_message = ChatMessage(
            id=message_id,
            case_id=request.case_id,
            role="assistant",
            content=request.content,
            source_references=request.artifacts,  # Store artifacts as source_references
            session_id=session_id
        )
        db.add(chat_message)
        db.commit()
        
        logger.info(f"Workflow message saved to DB with id: {message_id}, session: {session_id}")
        
        return {
            "success": True,
            "message_id": message_id,
            "session_id": session_id
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving workflow message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save workflow message")


# REMOVED: /api/assistant/chat/human-feedback endpoint (69 строк) - не работает, использует заглушки
# REMOVED: /api/assistant/chat/resume endpoint (63 строки) - не работает, использует заглушки

