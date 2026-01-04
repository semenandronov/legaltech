"""Assistant UI chat endpoint for streaming responses"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import AsyncGenerator, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel, ChatMessage
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_memory import MemoryService
from app.services.llm_factory import create_llm
from app.services.langchain_agents import PlanningAgent
from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
from app.services.analysis_service import AnalysisService
from app.services.external_sources.web_research_service import get_web_research_service
from app.services.external_sources.source_router import get_source_router
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


class AssistantMessage(BaseModel):
    """Message model for assistant-ui"""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


# Note: Request body is parsed manually to support assistant-ui format
# Assistant-ui sends: { messages: [...], case_id: "..." }


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
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.messages import SystemMessage, HumanMessage
    
    # Получаем список доступных агентов для промпта
    from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
    
    agents_list = []
    for agent_name, agent_info in AVAILABLE_ANALYSES.items():
        description = agent_info["description"]
        keywords = ", ".join(agent_info["keywords"][:3])  # Первые 3 ключевых слова
        agents_list.append(f"- {agent_name}: {description} (ключевые слова: {keywords})")
    
    agents_text = "\n".join(agents_list)
    
    classification_prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=f"""Ты классификатор запросов пользователя в системе анализа юридических документов.

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
- Примеры: "Извлеки все даты из документов", "Найди противоречия", "Проанализируй риски", "Создай резюме дела", "составь таблицу с судьями и судами"

ВОПРОС (question) - если это обычный вопрос для RAG чата:
- Вопросы с "какие", "что", "где", "когда", "кто", "почему"
- Разговорные фразы: "как дела", "привет"
- Требует немедленного ответа на основе уже загруженных документов
- Примеры: "Какие ключевые сроки важны в этом деле?", "Что говорится в договоре о сроках?"

Отвечай ТОЛЬКО: task или question"""),
        HumanMessage(content=f"Запрос: {question}")
    ])
    
    try:
        formatted_messages = classification_prompt.format_messages()
        response = llm.invoke(formatted_messages)
        result = response.content.lower().strip()
        result_clean = result.replace(".", "").replace(",", "").strip()
        if "task" in result_clean:
            task_pos = result_clean.find("task")
            question_pos = result_clean.find("question")
            if question_pos == -1 or (task_pos != -1 and task_pos < question_pos):
                logger.info(f"LLM classified '{question[:50]}...' as TASK (result: {result_clean})")
                return True
        logger.info(f"LLM classified '{question[:50]}...' as QUESTION (result: {result_clean})")
        return False
    except Exception as e:
        logger.error(f"Error in LLM classification: {e}")
        logger.warning("LLM classification failed, defaulting to QUESTION")
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
    Stream chat response using RAG and LLM OR agents for tasks
    
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
        from datetime import datetime
        user_message_id = str(uuid.uuid4())
        try:
            user_message = ChatMessage(
                id=user_message_id,
                case_id=case_id,
                role="user",
                content=question,
                session_id=None
            )
            db.add(user_message)
            db.commit()
            logger.info(f"User message saved to DB with id: {user_message_id}")
        except Exception as save_error:
            db.rollback()
            logger.error(f"Error saving user message to DB: {save_error}", exc_info=True)
            # Продолжаем без сохранения - не критичная ошибка
        
        # Классифицируем запрос - задача или вопрос?
        classification_llm = create_llm(temperature=0.0)
        is_task = await classify_request(question, classification_llm)
        
        # Переменные для накопления ответа и источников
        full_response_text = ""
        sources_list = []
        
        if is_task:
            # Это задача - используем Planning Agent и агентов
            logger.info(f"Detected task request for case {case_id}: {question[:100]}...")
            
            # Legal research для TASK запросов (если включено)
            legal_research_context_for_task = ""
            if legal_research:
                try:
                    logger.info(f"Legal research enabled for TASK query: {question[:100]}...")
                    source_router = get_source_router()
                    
                    # Определяем источники для поиска
                    sources_to_search = ["pravo_gov", "vsrf", "web"]
                    
                    # Выполняем поиск через source router
                    search_results = await source_router.search(
                        query=question,
                        source_names=sources_to_search,
                        max_results_per_source=5,
                        parallel=True
                    )
                    
                    # Агрегируем результаты
                    aggregated = source_router.aggregate_results(
                        search_results,
                        max_total=10,
                        dedup_threshold=0.9
                    )
                    
                    if aggregated:
                        legal_research_parts = []
                        legal_research_parts.append(f"\n\n=== Результаты юридического исследования для планирования ===")
                        legal_research_parts.append(f"Найдено источников: {len(aggregated)}")
                        
                        for i, result in enumerate(aggregated[:5], 1):
                            title = result.title or "Без названия"
                            url = result.url or ""
                            content = result.content[:500] if result.content else ""
                            source_name = result.source_name or "unknown"
                            
                            if content:
                                legal_research_parts.append(f"\n[Источник {i}: {title}]")
                                legal_research_parts.append(f"Источник: {source_name}")
                                if url:
                                    legal_research_parts.append(f"URL: {url}")
                                legal_research_parts.append(f"Содержание: {content}...")
                        
                        legal_research_context_for_task = "\n".join(legal_research_parts)
                        
                        # Добавляем источники в sources_list
                        for result in aggregated[:5]:
                            source_info = {
                                "title": result.title or "Юридический источник",
                                "url": result.url or "",
                                "source": result.source_name or "legal"
                            }
                            if result.content:
                                source_info["text_preview"] = result.content[:200]
                            sources_list.append(source_info)
                        
                        logger.info(f"Legal research completed for TASK: {len(aggregated)} sources found")
                    else:
                        logger.warning("Legal research returned no results for TASK")
                except Exception as legal_research_error:
                    logger.warning(f"Legal research failed for TASK: {legal_research_error}, continuing without legal research", exc_info=True)
            
            try:
                # Get case info
                case = db.query(Case).filter(Case.id == case_id).first()
                num_documents = case.num_documents if case else 0
                file_names = case.file_names if case and case.file_names else []
                
                # Добавляем контекст юридического исследования к задаче пользователя для Planning Agent
                user_task_with_context = question
                if legal_research_context_for_task:
                    user_task_with_context = f"{question}\n\n{legal_research_context_for_task}"
                
                # Use Advanced Planning Agent
                try:
                    planning_agent = AdvancedPlanningAgent(
                        rag_service=rag_service,
                        document_processor=document_processor
                    )
                    logger.info("Using Advanced Planning Agent with subtask support")
                    use_subtasks = True
                except Exception as e:
                    logger.warning(f"Failed to initialize Advanced Planning Agent: {e}, using base PlanningAgent")
                    planning_agent = PlanningAgent(rag_service=rag_service, document_processor=document_processor)
                    use_subtasks = False
                
                # Create analysis plan
                if use_subtasks:
                    plan = planning_agent.plan_with_subtasks(
                        user_task=user_task_with_context,
                        case_id=case_id,
                        available_documents=file_names[:10] if file_names else None,
                        num_documents=num_documents
                    )
                else:
                    plan = planning_agent.plan_analysis(
                        user_task=user_task_with_context,
                        case_id=case_id,
                        available_documents=file_names[:10] if file_names else None,
                        num_documents=num_documents
                    )
                
                analysis_types = plan.get("analysis_types", [])
                reasoning = plan.get("reasoning", "План создан на основе задачи")
                confidence = plan.get("confidence", 0.8)
                
                # Очищаем reasoning от JSON, если он там есть
                import re
                if "План извлечен из текстового ответа:" in reasoning:
                    # Убираем префикс и извлекаем нормальный текст
                    reasoning = reasoning.replace("План извлечен из текстового ответа:", "").strip()
                    # Убираем JSON объекты из reasoning
                    reasoning = re.sub(r'\{[^}]*\}', '', reasoning)
                    reasoning = re.sub(r'\[[^\]]*\]', '', reasoning)
                    reasoning = reasoning.strip()
                    if not reasoning:
                        reasoning = f"Выполнить анализ: {', '.join(analysis_types)}"
                
                logger.info(f"Planning completed: {len(analysis_types)} steps, confidence: {confidence:.2f}")
                
                # Сохраняем план в БД для одобрения
                from app.models.analysis import AnalysisPlan
                from datetime import datetime
                import uuid
                
                plan_id = str(uuid.uuid4())
                try:
                    analysis_plan = AnalysisPlan(
                        id=plan_id,
                        case_id=case_id,
                        user_id=current_user.id,
                        user_task=question,
                        plan_data=plan,
                        status="pending_approval",
                        confidence=confidence,
                        validation_result={
                            "is_valid": True,
                            "issues": [],
                            "warnings": []
                        },
                        tables_to_create=plan.get("tables_to_create", [])
                    )
                    db.add(analysis_plan)
                    db.commit()
                    logger.info(f"Plan saved to DB with id: {plan_id}")
                except Exception as save_error:
                    db.rollback()
                    logger.error(f"Error saving plan to DB: {save_error}", exc_info=True)
                    # Продолжаем без сохранения в БД
                
                # Формируем ответ с планом (без сырого JSON)
                plan_text = f"""Я составил план анализа для вашей задачи:

**План:**
{reasoning}

**Типы анализов:** {', '.join(analysis_types)}
**Уверенность:** {confidence:.0%}

Пожалуйста, проверьте план и подтвердите выполнение."""
                
                full_response_text = plan_text
                
                # Stream plan response
                for chunk in plan_text:
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)  # Small delay for streaming effect
                
                # Отправляем план для одобрения через SSE
                yield f"data: {json.dumps({'type': 'plan_ready', 'planId': plan_id, 'plan': plan}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
                
                # Сохраняем ответ ассистента в БД
                try:
                    assistant_message = ChatMessage(
                        case_id=case_id,
                        role="assistant",
                        content=full_response_text,
                        source_references=sources_list,
                        session_id=None
                    )
                    db.add(assistant_message)
                    db.commit()
                    logger.info(f"Assistant message (plan) saved to DB for case {case_id}")
                except Exception as save_error:
                    db.rollback()
                    logger.error(f"Error saving assistant message to DB: {save_error}", exc_info=True)
                
            except Exception as e:
                logger.error(f"Error in task planning: {e}", exc_info=True)
                error_msg = f"Ошибка при планировании задачи: {str(e)}"
                yield f"data: {json.dumps({'textDelta': error_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        else:
            # Это вопрос - используем RAG + LLM или веб-поиск
            # asyncio уже импортирован глобально, не нужно импортировать локально
            loop = asyncio.get_event_loop()
            
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
            
            # Legal research integration - поиск в юридических источниках
            legal_research_context = ""
            legal_research_successful = False
            
            if legal_research:
                try:
                    logger.info(f"Legal research enabled for query: {question[:100]}...")
                    source_router = get_source_router()
                    
                    # Определяем источники для поиска (приоритет pravo_gov для статей кодексов)
                    sources_to_search = ["pravo_gov", "vsrf", "web"]  # pravo_gov для законодательства, vsrf для позиций ВС
                    
                    # Выполняем поиск через source router
                    search_results = await source_router.search(
                        query=question,
                        source_names=sources_to_search,
                        max_results_per_source=5,
                        parallel=True
                    )
                    
                    # Агрегируем результаты
                    aggregated = source_router.aggregate_results(
                        search_results,
                        max_total=10,
                        dedup_threshold=0.9
                    )
                    
                    if aggregated:
                        legal_research_parts = []
                        legal_research_parts.append(f"\n\n=== Результаты юридического исследования ===")
                        legal_research_parts.append(f"Найдено источников: {len(aggregated)}")
                        
                        for i, result in enumerate(aggregated[:5], 1):
                            title = result.title or "Без названия"
                            url = result.url or ""
                            content = result.content[:500] if result.content else ""
                            source_name = result.source_name or "unknown"
                            
                            if content:
                                legal_research_parts.append(f"\n[Источник {i}: {title}]")
                                legal_research_parts.append(f"Источник: {source_name}")
                                if url:
                                    legal_research_parts.append(f"URL: {url}")
                                legal_research_parts.append(f"Содержание: {content}...")
                        
                        legal_research_context = "\n".join(legal_research_parts)
                        legal_research_successful = True
                        
                        # Добавляем источники в sources_list
                        for result in aggregated[:5]:
                            source_info = {
                                "title": result.title or "Юридический источник",
                                "url": result.url or "",
                                "source": result.source_name or "legal"
                            }
                            if result.content:
                                source_info["text_preview"] = result.content[:200]
                            sources_list.append(source_info)
                        
                        logger.info(f"Legal research completed: {len(aggregated)} sources found from {len(search_results)} sources")
                    else:
                        logger.warning("Legal research returned no results")
                except Exception as legal_research_error:
                    logger.warning(f"Legal research failed: {legal_research_error}, continuing without legal research", exc_info=True)
                    # Continue without legal research - не критичная ошибка
            
            # Get relevant documents using RAG - только если веб-поиск и юридическое исследование не дали результатов
            # или если они не включены
            context = ""
            if not web_search_successful and not legal_research_successful:
                # Выполняем RAG только если веб-поиск не дал результатов
                documents = await loop.run_in_executor(
                    None,
                    lambda: rag_service.retrieve_context(
                        case_id=case_id,
                        query=question,
                        k=10,
                        db=db
                    )
                )
                
                # Build context from documents and collect sources
                context_parts = []
                for i, doc in enumerate(documents[:5], 1):
                    if hasattr(doc, 'page_content'):
                        content = doc.page_content[:500] if doc.page_content else ""
                        source = doc.metadata.get("source_file", "unknown") if hasattr(doc, 'metadata') and doc.metadata else "unknown"
                        page = doc.metadata.get("page", None) if hasattr(doc, 'metadata') and doc.metadata else None
                    elif isinstance(doc, dict):
                        content = doc.get("content", "")[:500]
                        source = doc.get("file", "unknown")
                        page = doc.get("page", None)
                    else:
                        continue
                    
                    # Добавляем источник в список
                    source_info = {"file": source}
                    if page is not None:
                        source_info["page"] = page
                    if content:
                        source_info["text_preview"] = content[:200]
                    sources_list.append(source_info)
                        
                    context_parts.append(f"[Документ {i}: {source}]\n{content}")
                
                context = "\n\n".join(context_parts)
            
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
ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ РЕЗУЛЬТАТОВ ЮРИДИЧЕСКОГО ИССЛЕДОВАНИЯ:
- Используй информацию из юридических источников (pravo.gov.ru, vsrf.ru и др.) для ответа на вопросы о нормах права
- При цитировании статей кодексов или позиций ВС указывай источник (название и URL если доступен)
- Информация из официальных юридических источников имеет приоритет над информацией из документов дела при вопросах о законодательстве
- Если пользователь просит конкретную статью кодекса, приведи полный текст статьи из результатов юридического исследования
"""

            prompt = f"""Ты - юридический AI-ассистент. Ты помогаешь анализировать документы дела.

Контекст из документов дела:
{context}{web_search_context}{legal_research_context}

Вопрос пользователя: {question}{web_search_instructions}{legal_research_instructions}

ВАЖНО - ФОРМАТИРОВАНИЕ ОТВЕТА:
1. ВСЕГДА используй Markdown форматирование для ответов:
   - **жирный текст** для важных терминов
   - *курсив* для акцентов
   - Заголовки (##, ###) для структуры
   - Списки (- или 1.) для перечислений

2. ЕСЛИ пользователь просит создать ТАБЛИЦУ:
   - ВСЕГДА используй Markdown таблицы в формате:
   | Колонка 1 | Колонка 2 | Колонка 3 |
   |-----------|-----------|-----------|
   | Данные 1  | Данные 2  | Данные 3  |
   
   - НЕ отправляй таблицы как простой текст со звездочками
   - НЕ используй формат "Дата | Судья | Документ" без markdown таблицы
   - Таблица должна быть правильно отформатирована в Markdown

3. Для структурированных данных (даты, судьи, документы, события):
   - ВСЕГДА используй Markdown таблицы
   - Заголовки таблицы должны быть четкими
   - Данные должны быть в строках таблицы

4. Пример правильного ответа с таблицей:
   ## Таблица судебных заседаний
   
   | Дата | Судья | Номер документа |
   |------|-------|-----------------|
   | 22.08.2016 | Не указан | A83-6426-2015 |
   | 15.03.2017 | Е.А. Остапов | A83-6426-2015 |

Ответь на вопрос, используя информацию из документов дела. {f"Если информации из документов недостаточно, используй результаты веб-поиска для дополнения ответа." if web_search_context else ""}{f" Используй результаты юридического исследования для ответа на вопросы о нормах права и законодательстве." if legal_research_context else ""}{" Если информации недостаточно, укажи это." if not web_search_context and not legal_research_context else ""}
Будь точным и профессиональным. ВСЕГДА используй Markdown форматирование.
{f"При цитировании информации из веб-поиска указывай источник в формате: [Название источника](URL) или просто название источника, если URL недоступен." if web_search_context else ""}{f" При цитировании статей кодексов или норм права указывай источник: [Название статьи](URL) или просто название источника." if legal_research_context else ""}"""

            # Initialize LLM
            # Используем GigaChat SDK через create_llm()
            # При deep_think=True используем GigaChat-Pro, иначе модель по умолчанию (GigaChat)
            if deep_think:
                llm = create_llm(temperature=0.7, model="GigaChat-Pro")
                logger.info("Using GigaChat-Pro for deep thinking mode")
            else:
                llm = create_llm(temperature=0.7)  # Использует config.GIGACHAT_MODEL (обычно "GigaChat")
            
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
                        yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list}, ensure_ascii=False)}\n\n"
                    
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
                        yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list}, ensure_ascii=False)}\n\n"
                    
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
            
            # Сохраняем ответ ассистента в БД после завершения streaming
            try:
                assistant_message = ChatMessage(
                    case_id=case_id,
                    role="assistant",
                    content=full_response_text,
                    source_references=sources_list if sources_list else None,
                    session_id=None
                )
                db.add(assistant_message)
                db.commit()
                logger.info(f"Assistant message saved to DB for case {case_id}")
            except Exception as save_error:
                db.rollback()
                logger.error(f"Error saving assistant message to DB: {save_error}", exc_info=True)
    
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
    
    Uses agents for tasks, RAG for questions.
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
        
        # Create streaming response
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


@router.get("/api/assistant/chat/{case_id}/history")
async def get_assistant_chat_history(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get chat history for assistant chat
    
    Returns: list of messages with role, content, sources, created_at
    """
    # Check if case exists and verify ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get messages
    messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == case_id
    ).order_by(ChatMessage.created_at.asc()).all()
    
    return {
        "messages": [
            {
                "role": msg.role,
                "content": msg.content or "",
                "sources": msg.source_references if msg.source_references is not None else [],
                "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat()
            }
            for msg in messages
        ]
    }

