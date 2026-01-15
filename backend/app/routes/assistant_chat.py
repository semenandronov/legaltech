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
from app.services.langchain_agents.pipeline_service import PipelineService
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
from app.config import config
import json
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize services
rag_service = RAGService()
document_processor = DocumentProcessor()
memory_service = MemoryService()

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
    import re
    
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
    from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
    
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


async def stream_chat_response(
    case_id: str,
    question: str,
    db: Session,
    current_user: User,
    background_tasks: BackgroundTasks,
    web_search: bool = False,
    legal_research: bool = False,
    deep_think: bool = False,
    draft_mode: bool = False,
    document_context: Optional[str] = None,
    document_id: Optional[str] = None,
    selected_text: Optional[str] = None,
    template_file_id: Optional[str] = None,
    template_file_content: Optional[str] = None,
    attached_file_ids: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    """
    Stream chat response using RAG and LLM with optional web search and legal research
    
    Yields:
        JSON strings in assistant-ui format
    """
    try:
        # Verify case ownership
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
            return
        
        # Режим Draft: создание документа через ИИ
        if draft_mode:
            # Сохраняем пользовательское сообщение в БД
            import uuid
            from datetime import datetime, timedelta
            user_message_id = str(uuid.uuid4())
            assistant_message_id = None
            
            # Определяем session_id
            session_id = None
            try:
                last_message = db.query(ChatMessage).filter(
                    ChatMessage.case_id == case_id,
                    ChatMessage.content.isnot(None),
                    ChatMessage.content != ""
                ).order_by(ChatMessage.created_at.desc()).first()
                
                if last_message and last_message.created_at:
                    time_diff = datetime.utcnow() - last_message.created_at
                    if time_diff < timedelta(minutes=30) and last_message.session_id:
                        session_id = last_message.session_id
                    else:
                        session_id = str(uuid.uuid4())
                else:
                    session_id = str(uuid.uuid4())
            except Exception as session_error:
                logger.warning(f"Error determining session_id: {session_error}, creating new session")
                session_id = str(uuid.uuid4())
            
            try:
                user_message = ChatMessage(
                    id=user_message_id,
                    case_id=case_id,
                    role="user",
                    content=question,
                    session_id=session_id
                )
                db.add(user_message)
                
                assistant_message_id = str(uuid.uuid4())
                assistant_message_placeholder = ChatMessage(
                    id=assistant_message_id,
                    case_id=case_id,
                    role="assistant",
                    content="",
                    source_references=None,
                    session_id=session_id
                )
                db.add(assistant_message_placeholder)
                db.commit()
                logger.info(f"[Draft Mode] Messages saved to DB, session: {session_id}")
            except Exception as save_error:
                db.rollback()
                logger.warning(f"[Draft Mode] Error saving messages to DB: {save_error}")
            
            try:
                from app.services.langchain_agents.template_graph import create_template_graph
                from app.services.langchain_agents.template_state import TemplateState
                from app.services.document_editor_service import DocumentEditorService
                from app.services.llm_factory import create_legal_llm
                from langchain_core.messages import HumanMessage
                
                logger.info(f"[Draft Mode] Creating document for case {case_id} based on: {question[:100]}...")
                logger.info(f"[Draft Mode] Template file ID: {template_file_id}, Template file content length: {len(template_file_content) if template_file_content else 0}")
                
                # Извлечь название документа из описания
                try:
                    llm = create_legal_llm(temperature=0.1)
                    title_prompt = f"Извлеки краткое название документа (максимум 5-7 слов) из описания: {question}. Ответь только названием, без дополнительных слов."
                    title_response = llm.invoke([HumanMessage(content=title_prompt)])
                    title_text = title_response.content if hasattr(title_response, 'content') else str(title_response)
                    document_title = title_text.strip().replace('"', '').replace("'", "").strip()[:255]
                    
                    if not document_title or len(document_title) < 3:
                        document_title = "Новый документ"
                    if len(document_title) > 255:
                        document_title = document_title[:252] + "..."
                except Exception as title_error:
                    logger.warning(f"[Draft Mode] Error generating title: {title_error}")
                    document_title = "Новый документ"
                
                # Создаем граф для работы с шаблонами
                graph = create_template_graph(db)
                
                # Инициализируем состояние для графа
                initial_state: TemplateState = {
                    "user_query": question,
                    "case_id": case_id,
                    "user_id": current_user.id,
                    "cached_template": None,
                    "garant_template": None,
                    "template_source": None,
                    "final_template": None,
                    "adapted_content": None,
                    "document_id": None,
                    "messages": [],
                    "errors": [],
                    "metadata": {},
                    "should_adapt": True,  # Адаптируем шаблон под запрос
                    "document_title": document_title,
                    "template_file_id": template_file_id,  # ID файла-шаблона от пользователя (из БД)
                    "template_file_content": template_file_content,  # HTML контент локального файла или None
                    "case_context": None  # Будет заполнено в get_case_context_node
                }
                
                # Запускаем граф
                logger.info("[Draft Mode] Running template graph...")
                result = await graph.ainvoke(initial_state)
                
                # Проверяем критические ошибки (если документ не создан)
                if not result.get("document_id"):
                    if result.get("errors"):
                        error_msg = "; ".join(result["errors"])
                        logger.error(f"[Draft Mode] Template graph errors: {error_msg}")
                        raise Exception(error_msg)
                    else:
                        raise Exception("Не удалось создать документ")
                
                # Если документ создан, но есть некритичные ошибки (например, файл не найден) - логируем, но не прерываем
                if result.get("errors"):
                    # Фильтруем некритичные ошибки (ошибки загрузки файла, если документ все равно создан)
                    critical_errors = [
                        err for err in result["errors"] 
                        if "Нет содержимого для создания документа" in err or 
                           "Ошибка при создании/обновлении документа" in err
                    ]
                    if critical_errors:
                        error_msg = "; ".join(critical_errors)
                        logger.error(f"[Draft Mode] Critical template graph errors: {error_msg}")
                        raise Exception(error_msg)
                    else:
                        # Некритичные ошибки (например, файл не найден, но документ создан с нуля)
                        warning_msg = "; ".join(result["errors"])
                        logger.warning(f"[Draft Mode] Non-critical template graph warnings: {warning_msg}")
                
                # Получаем созданный документ
                doc_service = DocumentEditorService(db)
                document = doc_service.get_document(result["document_id"], current_user.id)
                
                if not document:
                    raise Exception("Созданный документ не найден")
                
                logger.info(f"[Draft Mode] Document created successfully: {document.id} (source: {result.get('template_source', 'unknown')})")
                
                # Сохраняем ответ в БД
                response_text = f'✅ Документ "{document.title}" успешно создан! Вы можете открыть его в редакторе для дальнейшего редактирования.'
                try:
                    if assistant_message_id:
                        assistant_message = db.query(ChatMessage).filter(
                            ChatMessage.id == assistant_message_id
                        ).first()
                        if assistant_message:
                            assistant_message.content = response_text
                            db.commit()
                            logger.info(f"[Draft Mode] Response saved to DB")
                except Exception as save_error:
                    db.rollback()
                    logger.warning(f"[Draft Mode] Failed to save response: {save_error}")
                
                # Отправить событие в SSE stream
                yield f"data: {json.dumps({
                    'type': 'document_created',
                    'document': {
                        'id': document.id,
                        'title': document.title,
                        'content': document.content[:500] if document.content else '',  # Превью
                        'case_id': document.case_id
                    }
                }, ensure_ascii=False)}\n\n"
                
                # Также отправим текстовое сообщение о создании документа
                yield f"data: {json.dumps({
                    'textDelta': response_text
                }, ensure_ascii=False)}\n\n"
                
                return
                
            except Exception as draft_error:
                logger.error(f"[Draft Mode] Error creating document: {draft_error}", exc_info=True)
                yield f"data: {json.dumps({
                    'textDelta': f'\n\n❌ Ошибка при создании документа: {str(draft_error)}. Попробуйте еще раз или опишите документ более подробно.'
                }, ensure_ascii=False)}\n\n"
                return
        
        # Verify case has files uploaded (только для обычного режима, не для draft)
        file_count = db.query(FileModel).filter(FileModel.case_id == case_id).count()
        if file_count == 0:
            yield f"data: {json.dumps({'error': 'В деле нет загруженных документов. Пожалуйста, сначала загрузите документы.'})}\n\n"
            return
        
        # Сохраняем пользовательское сообщение в БД
        import uuid
        from datetime import datetime, timedelta
        user_message_id = str(uuid.uuid4())
        assistant_message_id = None
        
        # Определяем session_id: если есть недавние сообщения (в течение 30 минут), используем их session_id
        # Иначе создаём новую сессию
        session_id = None
        try:
            # Проверяем последнее сообщение для этого дела
            last_message = db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            if last_message and last_message.created_at:
                # Проверяем, прошло ли менее 30 минут с последнего сообщения
                time_diff = datetime.utcnow() - last_message.created_at
                if time_diff < timedelta(minutes=30) and last_message.session_id:
                    # Продолжаем текущую сессию
                    session_id = last_message.session_id
                    logger.info(f"Continuing existing session {session_id} for case {case_id}")
                else:
                    # Создаём новую сессию
                    session_id = str(uuid.uuid4())
                    logger.info(f"Creating new session {session_id} for case {case_id}")
            else:
                # Первое сообщение в деле - создаём новую сессию
                session_id = str(uuid.uuid4())
                logger.info(f"Creating first session {session_id} for case {case_id}")
        except Exception as session_error:
            logger.warning(f"Error determining session_id: {session_error}, creating new session")
            session_id = str(uuid.uuid4())
        
        try:
            user_message = ChatMessage(
                id=user_message_id,
                case_id=case_id,
                role="user",
                content=question,
                session_id=session_id
            )
            db.add(user_message)
            
            # Создаём placeholder для сообщения ассистента ДО streaming
            # Это гарантирует, что сообщение будет сохранено даже при ошибке после streaming
            assistant_message_id = str(uuid.uuid4())
            assistant_message_placeholder = ChatMessage(
                id=assistant_message_id,
                case_id=case_id,
                role="assistant",
                content="",  # Пустой контент, будет обновлён после streaming
                source_references=None,
                session_id=session_id
            )
            db.add(assistant_message_placeholder)
            db.commit()
            logger.info(f"User message saved to DB with id: {user_message_id}, assistant placeholder: {assistant_message_id}, session: {session_id}")
        except Exception as save_error:
            db.rollback()
            logger.error(f"Error saving messages to DB: {save_error}", exc_info=True)
            # Продолжаем без сохранения - не критичная ошибка
        
        # Переменные для накопления ответа и источников
        full_response_text = ""
        sources_list = []
        
        # Используем только RAG - эта функция используется для простых вопросов через PipelineService
        logger.info(f"Processing RAG query for case {case_id}: {question[:100]}...")
        
        # Логируем прикрепленные файлы
        if attached_file_ids:
            logger.info(f"Attached file IDs for this query: {attached_file_ids}")
            # Файлы уже в базе и доступны через RAG по case_id
            # RAG автоматически найдет их при поиске по case_id
        
        # asyncio уже импортирован глобально
        loop = asyncio.get_event_loop()
        
        # Загружаем историю сообщений для контекста - ТОЛЬКО из текущей сессии
        chat_history = []
        try:
            # Фильтруем по session_id, чтобы ИИ видел только текущий чат, а не все чаты в деле
            history_query = db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            )
            
            # Если есть session_id, загружаем только сообщения из этой сессии
            if session_id:
                history_query = history_query.filter(ChatMessage.session_id == session_id)
            
            history_messages = history_query.order_by(ChatMessage.created_at.desc()).limit(10).all()
            
            # Формируем историю в формате для промпта (от старых к новым)
            chat_history = []
            for msg in reversed(history_messages):
                if msg.role == "user" and msg.content:
                    chat_history.append(f"Пользователь: {msg.content}")
                elif msg.role == "assistant" and msg.content:
                    chat_history.append(f"Ассистент: {msg.content[:500]}...")  # Ограничиваем длину
            
            if chat_history:
                logger.info(f"Loaded {len(chat_history)} previous messages for context from session {session_id}")
            else:
                logger.info(f"No previous messages found for context in session {session_id}")
        except Exception as history_error:
            logger.warning(f"Failed to load chat history: {history_error}, continuing without history")
            # Continue without history - не критичная ошибка
        
        # Web search integration - выполняем ПЕРВЫМ, если включен
        web_search_context = ""
        web_search_successful = False
        
        if web_search:
            try:
                logger.info(f"Web search enabled for query: {question[:100]}...")
                web_research_service = get_web_research_service()
                research_result = await web_research_service.research(
                    query=question,
                    max_results=5,
                    use_cache=True,
                    validate_sources=True
                )
                
                if research_result.sources:
                    web_search_parts = []
                    web_search_parts.append(f"\n\n=== Результаты веб-поиска ===")
                    web_search_parts.append(f"Найдено источников: {len(research_result.sources)}")
                    
                    for i, source in enumerate(research_result.sources[:5], 1):
                        title = source.get("title", "Без названия")
                        url = source.get("url", "")
                        content = source.get("content", "")
                        if content:
                            web_search_parts.append(f"\n[Источник {i}: {title}]")
                            if url:
                                web_search_parts.append(f"URL: {url}")
                            web_search_parts.append(f"Содержание: {content[:300]}...")
                    
                    web_search_context = "\n".join(web_search_parts)
                    web_search_successful = True
                    logger.info(f"Web search completed: {len(research_result.sources)} sources found")
                else:
                    logger.warning("Web search returned no results")
            except Exception as web_search_error:
                logger.warning(f"Web search failed: {web_search_error}, continuing without web search")
                # Continue without web search - не критичная ошибка
        
        # Если включен legal_research (ГАРАНТ), сначала ищем в ГАРАНТ
        # ВАЖНО: GigaChat SDK не поддерживает functions/tools, поэтому
        # вызываем ГАРАНТ напрямую и добавляем результаты в контекст
        garant_context = ""
        if legal_research:
            try:
                logger.info(f"[ГАРАНТ] Legal research enabled, searching in ГАРАНТ for: {question[:100]}...")
                from app.services.langchain_agents.garant_tools import _garant_search_sync
                
                # Выполняем поиск в ГАРАНТ
                garant_results = _garant_search_sync(query=question, doc_type="all", max_results=5)
                
                if garant_results and not garant_results.startswith("Ошибка") and not garant_results.startswith("Не найдено"):
                    garant_context = f"\n\n=== РЕЗУЛЬТАТЫ ПОИСКА В ГАРАНТ ===\n{garant_results}\n=== КОНЕЦ РЕЗУЛЬТАТОВ ГАРАНТ ===\n"
                    logger.info(f"[ГАРАНТ] Found results, context length: {len(garant_context)} chars")
                else:
                    logger.warning(f"[ГАРАНТ] No results or error: {garant_results[:200] if garant_results else 'empty'}")
            except Exception as garant_error:
                logger.error(f"[ГАРАНТ] Error searching in ГАРАНТ: {garant_error}", exc_info=True)
        
        # Подмешиваем контекст из документов дела (RAG) для вопросов по делу
        rag_context = ""
        try:
            # Берем релевантный контекст по вопросу
            rag_docs = rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=5,
                retrieval_strategy="multi_query",
                db=db
            )
            if rag_docs:
                rag_context = rag_service.format_sources_for_prompt(rag_docs, max_context_chars=4000)
                logger.info(f"[RAG] Added {len(rag_docs)} docs to context (len={len(rag_context)})")
        except Exception as rag_error:
            logger.warning(f"[RAG] Failed to load context: {rag_error}")
        
        # ВСЕГДА используем умного ChatAgent
        # Передаем legal_research для включения tools ГАРАНТ + добавляем контекст ГАРАНТ напрямую для надежности
        from app.services.langchain_agents.chat_agent import ChatAgent
        
        logger.info(f"[ChatAgent] Initializing ChatAgent for question: {question[:100]}... (legal_research={legal_research})")
        chat_agent = ChatAgent(
            case_id=case_id,
            rag_service=rag_service,
            db=db,
            legal_research_enabled=legal_research  # Включаем tools ГАРАНТ если legal_research=True
        )
        logger.info(f"[ChatAgent] ChatAgent initialized successfully, legal_research_enabled={legal_research}")
        
        logger.info("[ChatAgent] Using ChatAgent with tools and ГАРАНТ context injection")
        
        # Добавляем контекст документа редактора и ГАРАНТ в вопрос
        enhanced_question = question
        
        # Добавляем инструкцию для глубокого мышления если включено
        if deep_think:
            deep_think_instruction = """

=== РЕЖИМ ГЛУБОКОГО МЫШЛЕНИЯ ===
Для этой задачи включено глубокое размышление. Ты ДОЛЖЕН:
1. Выполнить многошаговый анализ проблемы
2. Рассмотреть вопрос с разных сторон и перспектив
3. Объяснять свой reasoning на каждом этапе
4. Проверить свои выводы и найти возможные противоречия
5. Дать развернутый, обоснованный ответ

Структурируй свой ответ следующим образом:
📊 **Анализ вопроса**: что именно спрашивает пользователь
🔍 **Рассмотрение аспектов**: ключевые факторы для ответа
💭 **Размышление**: логические выводы из анализа
✅ **Заключение**: итоговый ответ с обоснованием
=== КОНЕЦ ИНСТРУКЦИИ ===

"""
            enhanced_question = deep_think_instruction + enhanced_question
            logger.info(f"[Deep Think] Added deep thinking instructions to question")
        
        # Добавляем результаты ГАРАНТ если есть
        if garant_context:
            enhanced_question = f"{enhanced_question}\n\n{garant_context}\n\nИспользуй информацию из ГАРАНТ для ответа на вопрос пользователя. Цитируй источники из ГАРАНТ."
            logger.info(f"[ChatAgent] Added ГАРАНТ context to question")

        # Добавляем RAG контекст по документам дела
        if rag_context:
            enhanced_question = f"{enhanced_question}\n\n=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ДЕЛА ===\n{rag_context}\n=== КОНЕЦ КОНТЕКСТА ===\n"
            logger.info("[ChatAgent] Added RAG context to question")
        
        if document_context or selected_text:
            context_parts = []
            if document_context:
                # Ограничиваем размер контекста документа (первые 4000 символов)
                doc_preview = document_context[:4000]
                context_parts.append(f"\n\n=== ТЕКУЩИЙ ДОКУМЕНТ В РЕДАКТОРЕ ===\n{doc_preview}")
                if len(document_context) > 4000:
                    context_parts.append(f"\n[Документ обрезан, всего {len(document_context)} символов]")
            if selected_text:
                context_parts.append(f"\n\n=== ВЫДЕЛЕННЫЙ ТЕКСТ ===\n{selected_text}")
            
            # Добавляем инструкцию для режима редактора
            context_parts.append(f"\n\n=== ВАЖНО: РЕЖИМ РЕДАКТОРА ДОКУМЕНТА ===\n")
            context_parts.append(f"Ты работаешь в режиме редактирования документа. Пользователь может попросить тебя:\n")
            context_parts.append(f"- Изменить выделенный текст\n")
            context_parts.append(f"- Улучшить текст\n")
            context_parts.append(f"- Переписать часть документа\n")
            context_parts.append(f"- Добавить или удалить информацию\n\n")
            context_parts.append(f"Если пользователь просит изменить документ, ты ДОЛЖЕН:\n")
            context_parts.append(f"1. Дать текстовый ответ с объяснением изменений\n")
            context_parts.append(f"2. В конце ответа добавить блок с HTML кодом измененного документа в формате:\n")
            context_parts.append(f"```html\n<полный HTML код документа с изменениями>\n```\n")
            context_parts.append(f"ВАЖНО: HTML должен быть полным и валидным, включая все теги и структуру документа.\n")
            context_parts.append(f"Если пользователь выделил текст, изменения должны применяться к выделенному тексту.\n")
            context_parts.append(f"Ты имеешь доступ ко всему делу (case_id={case_id}) и можешь использовать информацию из всех документов дела для контекста.\n")
            
            enhanced_question = question + "".join(context_parts)
            logger.info(f"[ChatAgent] Enhanced question with document context (doc_len={len(document_context) if document_context else 0}, selected_len={len(selected_text) if selected_text else 0})")
        
        try:
            # Stream ответ от ChatAgent
            async for chunk in chat_agent.answer_stream(enhanced_question):
                if chunk:
                    full_response_text += chunk
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
            
            # Проставляем ссылки на документы ГАРАНТ в ответе (если включен legal_research)
            if legal_research and len(full_response_text) < 8000:
                try:
                    from app.services.external_sources.source_router import initialize_source_router
                    source_router = initialize_source_router(rag_service=rag_service, register_official_sources=True)
                    garant_source = source_router._sources.get("garant") if source_router else None
                    if garant_source:
                        logger.info(f"[ChatAgent] Attempting to insert Garant links (text length: {len(full_response_text)} chars)")
                        text_with_links = await garant_source.insert_links(full_response_text)
                        if text_with_links and text_with_links != full_response_text:
                            full_response_text = text_with_links
                            logger.info(f"[ChatAgent] Successfully inserted Garant links")
                except Exception as e:
                    logger.warning(f"[ChatAgent] Failed to insert Garant links: {e}", exc_info=True)
            
            # Для режима редактора документа: извлекаем edited_content из ответа
            if document_id and document_context:
                import re
                edited_content = None
                
                # Пытаемся извлечь HTML из code blocks
                html_match = re.search(r'```(?:html)?\s*\n(.*?)\n```', full_response_text, re.DOTALL)
                if html_match:
                    edited_content = html_match.group(1).strip()
                    logger.info(f"[ChatAgent] Extracted edited_content from code block (length: {len(edited_content)})")
                else:
                    # Пытаемся найти HTML теги в ответе
                    html_tag_match = re.search(r'<[^>]+>.*?</[^>]+>', full_response_text, re.DOTALL)
                    if html_tag_match:
                        edited_content = html_tag_match.group(0)
                        logger.info(f"[ChatAgent] Extracted edited_content from HTML tags (length: {len(edited_content)})")
                
                # Если нашли edited_content, отправляем его через SSE
                if edited_content:
                    yield f"data: {json.dumps({'type': 'edited_content', 'edited_content': edited_content}, ensure_ascii=False)}\n\n"
                    logger.info(f"[ChatAgent] Sent edited_content event (length: {len(edited_content)})")
            
            # Сохраняем ответ в БД
            try:
                assistant_message_placeholder.content = full_response_text
                db.commit()
                logger.info(f"[ChatAgent] Response saved to DB")
            except Exception as save_error:
                db.rollback()
                logger.warning(f"[ChatAgent] Failed to save response: {save_error}")
            
            return
            
        except Exception as agent_error:
            logger.error(f"[ChatAgent] Error using ChatAgent: {agent_error}", exc_info=True)
            yield f"data: {json.dumps({'error': 'Ошибка при обработке запроса. ChatAgent обязателен и не может быть использован.'})}\n\n"
            return
    
    except Exception as e:
        if assistant_message_id:
            try:
                assistant_message = db.query(ChatMessage).filter(
                    ChatMessage.id == assistant_message_id
                ).first()
                if assistant_message:
                    assistant_message.content = full_response_text
                    assistant_message.source_references = sources_list if sources_list else None
                    db.commit()
                    logger.info(f"Assistant message updated in DB for case {case_id}, id: {assistant_message_id}")
                else:
                    logger.warning(f"Assistant message placeholder {assistant_message_id} not found, creating new one")
                    # Fallback: создаём новое сообщение если placeholder не найден
                    assistant_message = ChatMessage(
                        case_id=case_id,
                        role="assistant",
                        content=full_response_text,
                        source_references=sources_list if sources_list else None,
                        session_id=session_id
                    )
                    db.add(assistant_message)
                    db.commit()
            except Exception as update_error:
                db.rollback()
                logger.error(f"Error updating assistant message in DB: {update_error}", exc_info=True)
                # Пытаемся создать новое сообщение как fallback
                try:
                    assistant_message = ChatMessage(
                        case_id=case_id,
                        role="assistant",
                        content=full_response_text,
                        source_references=sources_list if sources_list else None,
                        session_id=session_id
                    )
                    db.add(assistant_message)
                    db.commit()
                    logger.info(f"Assistant message created as fallback for case {case_id}")
                except Exception as fallback_error:
                    db.rollback()
                    logger.error(f"Error creating fallback assistant message: {fallback_error}", exc_info=True)
        
        logger.error(f"Error in stream_chat_response: {e}", exc_info=True)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


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
        
        # Use direct RAG stream_chat_response - no agents, simple question answering
        return StreamingResponse(
            stream_chat_response(
                case_id=case_id,
                question=question,
                db=db,
                current_user=current_user,
                background_tasks=background_tasks,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think,
                draft_mode=draft_mode,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                template_file_id=template_file_id,
                template_file_content=template_file_content,
                attached_file_ids=attached_file_ids
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


class HumanFeedbackResponseRequest(BaseModel):
    """Request model for submitting human feedback response"""
    request_id: str = Field(..., description="Идентификатор запроса обратной связи")
    response: str = Field(..., description="Ответ пользователя")
    case_id: Optional[str] = Field(None, description="Идентификатор дела (опционально, для валидации)")


@router.post("/api/assistant/chat/human-feedback")
async def submit_human_feedback(
    request: HumanFeedbackResponseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submit human feedback response for agent requests
    
    This endpoint receives user responses to agent feedback requests
    (e.g., approval requests, clarification questions, etc.)
    """
    try:
        from app.services.langchain_agents.human_feedback import get_feedback_service
        
        # Get feedback service
        feedback_service = get_feedback_service(db)
        
        # Submit response
        success = feedback_service.receive_response(
            request_id=request.request_id,
            response=request.response,
            run_id=None  # run_id can be extracted from state if needed
        )
        
        if not success:
            logger.warning(f"Failed to submit feedback response for request {request.request_id}: request not found or already answered")
            raise HTTPException(
                status_code=404,
                detail="Запрос обратной связи не найден или уже обработан"
            )
        
        # Log feedback submission
        if request.case_id:
            from app.services.langchain_agents.audit_logger import get_audit_logger
            audit_logger = get_audit_logger()
            audit_logger.log_human_feedback(
                request_id=request.request_id,
                question="",  # Question is stored in the request itself
                response=request.response,
                case_id=request.case_id,
                user_id=str(current_user.id),
                approved=None  # Can be determined from response if needed
            )
        
        logger.info(f"Human feedback response submitted successfully for request {request.request_id}")
        
        return {
            "status": "success",
            "request_id": request.request_id,
            "message": "Ответ успешно отправлен"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting human feedback response: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при отправке ответа: {str(e)}"
        )


class ResumeGraphRequest(BaseModel):
    """Request model for resuming graph execution after interrupt"""
    thread_id: str = Field(..., description="Thread ID для resume")
    case_id: str = Field(..., description="Идентификатор дела")
    answer: dict = Field(..., description="Ответ пользователя (например, {'doc_types': ['contract'], 'columns_clarification': '...'})")


@router.post("/api/assistant/chat/resume")
async def resume_graph_execution(
    request: ResumeGraphRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возобновить выполнение графа после interrupt
    
    Этот endpoint получает ответ пользователя на уточняющий вопрос от агента
    и возобновляет выполнение графа через Command(resume=...)
    """
    try:
        from app.services.langchain_agents.coordinator import AgentCoordinator
        from app.services.rag_service import RAGService
        from app.services.document_processor import DocumentProcessor
        
        # Проверяем, что дело принадлежит пользователю
        case = db.query(Case).filter(
            Case.id == request.case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(
                status_code=404,
                detail="Дело не найдено"
            )
        
        # Создаем coordinator для resume
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        coordinator = AgentCoordinator(db, rag_service, document_processor)
        
        # Создаем step_callback для streaming (если нужен)
        # В данном случае просто логируем
        def step_callback(event):
            logger.debug(f"[Resume] Stream event: {type(event)}")
        
        # Вызываем resume
        result = coordinator.resume_after_interrupt(
            thread_id=request.thread_id,
            case_id=request.case_id,
            answer=request.answer,
            step_callback=step_callback
        )
        
        logger.info(f"Graph execution resumed successfully for thread {request.thread_id}")
        
        return {
            "status": "resumed",
            "thread_id": request.thread_id,
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming graph execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при возобновлении выполнения: {str(e)}"
        )

