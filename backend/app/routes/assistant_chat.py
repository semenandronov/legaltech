"""Assistant UI chat endpoint for streaming responses"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import AsyncGenerator, Optional, Literal
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
    deep_think: bool = False
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
        
        # Verify case has files uploaded
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
        
        # Legal research integration - поиск в ГАРАНТ с анализом результатов
        legal_research_context = ""
        legal_research_successful = False
        
        if legal_research:
            try:
                logger.info(f"Legal research enabled for query: {question[:100]}...")
                # Инициализируем source_router с официальными источниками
                source_router = initialize_source_router(rag_service=rag_service, register_official_sources=True)
                
                # Определяем источники для поиска - только ГАРАНТ
                sources_to_search = ["garant"]
                
                # Выполняем поиск через source router
                search_results = await source_router.search(
                    query=question,
                    source_names=sources_to_search,
                    max_results_per_source=10,  # Увеличиваем для лучшего анализа
                    parallel=True
                )
                
                # Агрегируем результаты
                aggregated = source_router.aggregate_results(
                    search_results,
                    max_total=15,  # Больше результатов для анализа
                    dedup_threshold=0.9
                )
                
                if aggregated:
                    # Формируем контекст с акцентом на релевантность к вопросу пользователя
                    legal_research_parts = []
                    legal_research_parts.append(f"\n\n=== Результаты поиска в ГАРАНТ ===")
                    legal_research_parts.append(f"Вопрос пользователя: {question}")
                    legal_research_parts.append(f"Найдено документов: {len(aggregated)}")
                    legal_research_parts.append("\nВАЖНО: Проанализируй эти результаты в контексте вопроса пользователя и используй только релевантную информацию для ответа.")
                    
                    for i, result in enumerate(aggregated[:10], 1):
                        title = result.title or "Без названия"
                        url = result.url or ""
                        content = result.content[:800] if result.content else ""  # Увеличиваем длину для лучшего контекста
                        source_name = result.source_name or "garant"
                        relevance = getattr(result, 'relevance_score', 0.5)
                        
                        if content:
                            legal_research_parts.append(f"\n[Документ {i}: {title}]")
                            legal_research_parts.append(f"Релевантность: {relevance:.2f}")
                            if url:
                                legal_research_parts.append(f"URL: {url}")
                            legal_research_parts.append(f"Содержание: {content}")
                            legal_research_parts.append("---")
                    
                    legal_research_context = "\n".join(legal_research_parts)
                    legal_research_successful = True
                    
                    # Добавляем источники в sources_list
                    for result in aggregated[:10]:
                        source_info = {
                            "title": result.title or "ГАРАНТ",
                            "url": result.url or "",
                            "source": "garant"
                        }
                        if result.content:
                            source_info["text_preview"] = result.content[:200]
                        sources_list.append(source_info)
                    
                    logger.info(f"Legal research completed: {len(aggregated)} sources found from ГАРАНТ")
                else:
                    logger.warning("Legal research returned no results from ГАРАНТ")
            except Exception as legal_research_error:
                logger.warning(f"Legal research failed: {legal_research_error}, continuing without legal research", exc_info=True)
                # Continue without legal research - не критичная ошибка
        
        # Get relevant documents using RAG - ВСЕГДА выполняем RAG для получения контекста из документов дела
        # Веб-поиск и юридическое исследование дополняют, но не заменяют RAG
        context = ""
        try:
            # Используем аргумент по умолчанию для захвата rag_service в lambda
            documents = await loop.run_in_executor(
                None,
                lambda rs=rag_service: rs.retrieve_context(
                    case_id=case_id,
                    query=question,
                    k=10,
                    db=db
                )
            )
            
            # Build context from documents and collect sources using RAGService.format_sources
            context_parts = []
            if documents:
                # Use RAGService.format_sources for consistent source formatting
                formatted_sources = rag_service.format_sources(documents[:5])
                sources_list.extend(formatted_sources)
                
                # Build context from documents
                for i, doc in enumerate(documents[:5], 1):
                    if hasattr(doc, 'page_content'):
                        content = doc.page_content[:500] if doc.page_content else ""
                        source = doc.metadata.get("source_file", "unknown") if hasattr(doc, 'metadata') and doc.metadata else "unknown"
                    elif isinstance(doc, dict):
                        content = doc.get("content", "")[:500]
                        source = doc.get("file", "unknown")
                    else:
                        continue
                    
                    context_parts.append(f"[Документ {i}: {source}]\n{content}")
                
                context = "\n\n".join(context_parts)
                if context:
                    logger.info(f"RAG retrieved {len(documents)} documents for context, {len(sources_list)} sources formatted")
                else:
                    logger.warning(f"RAG retrieved {len(documents)} documents but context is empty")
        except Exception as rag_error:
            logger.warning(f"RAG retrieval failed: {rag_error}, continuing without RAG context", exc_info=True)
            # Continue without RAG context - не критичная ошибка, но важно для deep_think
        
        # Добавляем источники из веб-поиска
        if web_search_successful and 'research_result' in locals() and research_result.sources:
            for source in research_result.sources[:5]:
                source_info = {
                    "title": source.get("title", "Веб-источник"),
                    "url": source.get("url", ""),
                }
                if source.get("content"):
                    source_info["text_preview"] = source.get("content", "")[:200]
                sources_list.append(source_info)
        
        # Create prompt
        web_search_instructions = ""
        if web_search_context:
            web_search_instructions = """
ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ РЕЗУЛЬТАТОВ ВЕБ-ПОИСКА:
- Используй информацию из веб-поиска для дополнения ответа, когда информации из документов дела недостаточно
- При цитировании информации из веб-поиска указывай источник (название и URL если доступен)
- Предпочтительно использовать информацию из документов дела, веб-поиск - для дополнительного контекста
- Если информация из веб-поиска противоречит документам дела, укажи это и приоритизируй документы дела
"""

        legal_research_instructions = ""
        if legal_research_context:
            legal_research_instructions = """
ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ РЕЗУЛЬТАТОВ ПОИСКА В ГАРАНТ:
- ВАЖНО: Ты получил результаты поиска в ГАРАНТ по запросу пользователя. НЕ просто пересказывай эти результаты, а ПРОАНАЛИЗИРУЙ их в контексте вопроса пользователя.
- Используй информацию из ГАРАНТ для ПРЯМОГО ОТВЕТА на вопрос пользователя, а не просто перечисляй найденные документы.
- Если пользователь спрашивает о конкретной статье кодекса - найди её в результатах и приведи полный текст статьи.
- Если пользователь спрашивает о правовой норме - найди релевантные документы и объясни, как они отвечают на вопрос.
- Приоритизируй документы с высокой релевантностью (указана в результатах).
- При цитировании указывай источник (название документа и URL из ГАРАНТ).
- Если в результатах нет информации, отвечающей на вопрос - честно скажи об этом, не придумывай ответ.
- Структурируй ответ так, чтобы он был полезен пользователю: сначала краткий ответ, потом детали из документов.
"""

        # Формируем историю для промпта
        history_context = ""
        if chat_history:
            history_context = f"""
Контекст предыдущих сообщений в этом чате:
{chr(10).join(chat_history)}

ВАЖНО: Учитывай контекст предыдущих сообщений при ответе. Если пользователь задает уточняющий вопрос (например, "подробнее"), используй информацию из предыдущих сообщений для более полного ответа.
"""

        prompt = f"""Ты - юридический AI-ассистент. Ты помогаешь анализировать документы дела.

Контекст из документов дела:
{context if context else "Контекст из документов дела не найден. Используй общие знания и информацию из других источников."}{web_search_context}{legal_research_context}{history_context}

Вопрос пользователя: {question}{web_search_instructions}{legal_research_instructions}

ВАЖНО - ФОРМАТИРОВАНИЕ ОТВЕТА:
1. ВСЕГДА используй Markdown форматирование для ответов:
   - **жирный текст** для важных терминов
   - *курсив* для акцентов
   - Заголовки (##, ###) для структуры
   - Списки (- или 1.) для перечислений

2. КРИТИЧЕСКИ ВАЖНО - ФОРМАТ ССЫЛОК НА ДОКУМЕНТЫ (ОБЯЗАТЕЛЬНО!):
   При цитировании информации из документов дела ВСЕГДА используй ТОЛЬКО формат [1], [2], [3] и т.д.
   - Первый документ в контексте = [1]
   - Второй документ в контексте = [2]
   - Третий документ в контексте = [3]
   - Запрещено использовать: [Document 1], [Документ 1], [Документ: filename.pdf], [Документ 1: ...]
   - Разрешен ТОЛЬКО формат: [1], [2], [3] - только число в квадратных скобках
   - Пример правильного ответа: "Согласно документам дела [1][2], стороны обязаны..."
   - Пример неправильного (запрещен): "Согласно [Document 1] и [Документ 2]..."
   ЗАПОМНИ: ТОЛЬКО [1], [2], [3] - никаких других форматов!

3. ЕСЛИ пользователь просит создать ТАБЛИЦУ:
   - ВСЕГДА используй Markdown таблицы в формате:
   | Колонка 1 | Колонка 2 | Колонка 3 |
   |-----------|-----------|-----------|
   | Данные 1  | Данные 2  | Данные 3  |
   
   - НЕ отправляй таблицы как простой текст со звездочками
   - НЕ используй формат "Дата | Судья | Документ" без markdown таблицы
   - Таблица должна быть правильно отформатирована в Markdown

4. Для структурированных данных (даты, судьи, документы, события):
   - ВСЕГДА используй Markdown таблицы
   - Заголовки таблицы должны быть четкими
   - Данные должны быть в строках таблицы

5. Пример правильного ответа с таблицей:
   ## Таблица судебных заседаний
   
   | Дата | Судья | Номер документа |
   |------|-------|-----------------|
   | 22.08.2016 | Не указан | A83-6426-2015 |
   | 15.03.2017 | Е.А. Остапов | A83-6426-2015 |

Ответь на вопрос, используя информацию из документов дела. {f"Если информации из документов недостаточно, используй результаты веб-поиска для дополнения ответа." if web_search_context else ""}{f" Используй результаты юридического исследования для ответа на вопросы о нормах права и законодательстве." if legal_research_context else ""}{" Если информации недостаточно, укажи это." if not web_search_context and not legal_research_context else ""}

ПОВТОРЯЮ КРИТИЧЕСКИ ВАЖНОЕ ПРАВИЛО: При цитировании документов дела используй ТОЛЬКО формат [1], [2], [3] - число в квадратных скобках. НЕ используй [Document 1], [Документ 1] или любой другой формат!

Будь точным и профессиональным. ВСЕГДА используй Markdown форматирование.
{f"При цитировании информации из веб-поиска указывай источник в формате: [Название источника](URL) или просто название источника, если URL недоступен." if web_search_context else ""}{f" При цитировании статей кодексов или норм права указывай источник: [Название статьи](URL) или просто название источника." if legal_research_context else ""}"""

        # Initialize LLM
        # Используем create_legal_llm() для детерминистических юридических ответов (temperature=0.0)
        # При deep_think=True используем GigaChat-Pro, иначе модель по умолчанию (GigaChat)
        if deep_think:
            llm = create_legal_llm(model="GigaChat-Pro")  # temperature=0.0 автоматически
            logger.info(f"Using GigaChat-Pro for deep thinking mode (temperature=0.0). Context length: {len(context)} chars, History messages: {len(chat_history)}, Web search: {web_search_successful}, Legal research: {legal_research_successful}")
        else:
            llm = create_legal_llm()  # temperature=0.0 автоматически, использует config.GIGACHAT_MODEL (обычно "GigaChat")
            logger.info(f"Using standard GigaChat (temperature=0.0). Context length: {len(context)} chars, History messages: {len(chat_history)}")
        
        # Stream response
        # Преобразуем строку prompt в список сообщений для GigaChat
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        
        try:
            if hasattr(llm, 'astream'):
                async for chunk in llm.astream(messages):
                    if hasattr(chunk, 'content'):
                        content = chunk.content
                    elif isinstance(chunk, str):
                        content = chunk
                    else:
                        content = str(chunk)
                    
                    full_response_text += content
                    yield f"data: {json.dumps({'textDelta': content}, ensure_ascii=False)}\n\n"
                
                # Отправляем источники через SSE
                if sources_list:
                    logger.info(f"Sending {len(sources_list)} sources via SSE (fallback) for case {case_id}")
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list}, ensure_ascii=False)}\n\n"
                else:
                    logger.warning(f"No sources to send (fallback) for case {case_id}, query: {question[:100]}")
                
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
            else:
                # Fallback: get full response and chunk it
                response = await loop.run_in_executor(None, lambda: llm.invoke(messages))
                response_text = response.content if hasattr(response, 'content') else str(response)
                full_response_text = response_text
                
                chunk_size = 20
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)
                
                # Отправляем источники через SSE
                if sources_list:
                    logger.info(f"Sending {len(sources_list)} sources via SSE (fallback) for case {case_id}")
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list}, ensure_ascii=False)}\n\n"
                else:
                    logger.warning(f"No sources to send (fallback) for case {case_id}, query: {question[:100]}")
                
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        except Exception as stream_error:
            logger.warning(f"Streaming failed, using fallback: {stream_error}")
            response = await loop.run_in_executor(None, lambda: llm.invoke(messages))
            response_text = response.content if hasattr(response, 'content') else str(response)
            full_response_text = response_text
            
            chunk_size = 20
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)
            
            # Отправляем источники через SSE
            if sources_list:
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list}, ensure_ascii=False)}\n\n"
            
            yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        
        # Обновляем существующее сообщение ассистента после завершения streaming
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
    
    except Exception as e:
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
                deep_think=deep_think
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

