"""Assistant UI chat endpoint for streaming responses"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import AsyncGenerator, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_memory import MemoryService
from app.services.llm_factory import create_llm
from app.services.langchain_agents import PlanningAgent
from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
from app.services.analysis_service import AnalysisService
from app.services.external_sources.web_research_service import get_web_research_service
import json
import logging
import asyncio

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
        
        # #region agent log
        import json as json_module
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                f.write(json_module.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A",
                    "location": "assistant_chat.py:148",
                    "message": "Stream chat response started",
                    "data": {"case_id": case_id, "question": question[:100], "web_search": web_search, "web_search_type": str(type(web_search))},
                    "timestamp": int(__import__('time').time() * 1000)
                }, ensure_ascii=False) + '\n')
        except:
            pass
        # #endregion
        
        # Классифицируем запрос - задача или вопрос?
        classification_llm = create_llm(temperature=0.0)
        is_task = await classify_request(question, classification_llm)
        
        # #region agent log
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                f.write(json_module.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "C",
                    "location": "assistant_chat.py:152",
                    "message": "Request classified",
                    "data": {"is_task": is_task, "web_search": web_search},
                    "timestamp": int(__import__('time').time() * 1000)
                }, ensure_ascii=False) + '\n')
        except:
            pass
        # #endregion
        
        if is_task:
            # Это задача - используем Planning Agent и агентов
            logger.info(f"Detected task request for case {case_id}: {question[:100]}...")
            
            try:
                # Get case info
                case = db.query(Case).filter(Case.id == case_id).first()
                num_documents = case.num_documents if case else 0
                file_names = case.file_names if case and case.file_names else []
                
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
                        user_task=question,
                        case_id=case_id,
                        available_documents=file_names[:10] if file_names else None,
                        num_documents=num_documents
                    )
                else:
                    plan = planning_agent.plan_analysis(
                        user_task=question,
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
                
                # Stream plan response
                for chunk in plan_text:
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)  # Small delay for streaming effect
                
                # Отправляем план для одобрения через SSE
                yield f"data: {json.dumps({'type': 'plan_ready', 'planId': plan_id, 'plan': plan}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
                
            except Exception as e:
                logger.error(f"Error in task planning: {e}", exc_info=True)
                error_msg = f"Ошибка при планировании задачи: {str(e)}"
                yield f"data: {json.dumps({'textDelta': error_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        else:
            # Это вопрос - используем RAG + LLM
            # asyncio уже импортирован глобально, не нужно импортировать локально
            loop = asyncio.get_event_loop()
            
            # Get relevant documents using RAG
            documents = await loop.run_in_executor(
                None,
                lambda: rag_service.retrieve_context(
                    case_id=case_id,
                    query=question,
                    k=10,
                    db=db
                )
            )
            
            # Build context from documents
            context_parts = []
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
            
            # Web search integration
            # #region agent log
            try:
                with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                    f.write(json_module.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "assistant_chat.py:348",
                        "message": "Before web_search check",
                        "data": {
                            "web_search": web_search,
                            "web_search_type": str(type(web_search)),
                            "web_search_bool": bool(web_search),
                            "web_search_is_truthy": bool(web_search) if web_search else False,
                            "question": question[:100]
                        },
                        "timestamp": int(__import__('time').time() * 1000)
                    }, ensure_ascii=False) + '\n')
            except:
                pass
            # #endregion
            
            # #region agent log
            try:
                with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                    f.write(json_module.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "G",
                        "location": "assistant_chat.py:353",
                        "message": "Web search check result",
                        "data": {
                            "web_search": web_search,
                            "web_search_bool": bool(web_search),
                            "condition_result": bool(web_search),
                            "question": question[:100]
                        },
                        "timestamp": int(__import__('time').time() * 1000)
                    }, ensure_ascii=False) + '\n')
            except:
                pass
            # #endregion
            
            web_search_context = ""
            if web_search:
                # #region agent log
                try:
                    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                        f.write(json_module.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "C",
                            "location": "assistant_chat.py:348",
                            "message": "Web search condition TRUE - entering block",
                            "data": {"question": question[:100]},
                            "timestamp": int(__import__('time').time() * 1000)
                        }, ensure_ascii=False) + '\n')
                except:
                    pass
                # #endregion
                try:
                    # #region agent log
                    try:
                        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                            f.write(json_module.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "D",
                                "location": "assistant_chat.py:302",
                                "message": "Web search condition passed, starting research",
                                "data": {"query": question[:100]},
                                "timestamp": int(__import__('time').time() * 1000)
                            }, ensure_ascii=False) + '\n')
                    except:
                        pass
                    # #endregion
                    
                    logger.info(f"Web search enabled for query: {question[:100]}...")
                    web_research_service = get_web_research_service()
                    research_result = await web_research_service.research(
                        query=question,
                        max_results=5,
                        use_cache=True,
                        validate_sources=True
                    )
                    
                    # #region agent log
                    try:
                        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                            f.write(json_module.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "D",
                                "location": "assistant_chat.py:313",
                                "message": "Web research result received",
                                "data": {"sources_count": len(research_result.sources) if research_result.sources else 0, "has_summary": bool(research_result.summary)},
                                "timestamp": int(__import__('time').time() * 1000)
                            }, ensure_ascii=False) + '\n')
                    except:
                        pass
                    # #endregion
                    
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
                        logger.info(f"Web search completed: {len(research_result.sources)} sources found")
                    else:
                        logger.warning("Web search returned no results")
                        # #region agent log
                        try:
                            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                                f.write(json_module.dumps({
                                    "sessionId": "debug-session",
                                    "runId": "run1",
                                    "hypothesisId": "F",
                                    "location": "assistant_chat.py:450",
                                    "message": "Web search returned no results",
                                    "data": {"question": question[:100]},
                                    "timestamp": int(__import__('time').time() * 1000)
                                }, ensure_ascii=False) + '\n')
                        except:
                            pass
                        # #endregion
                except Exception as web_search_error:
                    # #region agent log
                    try:
                        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                            f.write(json_module.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "E",
                                "location": "assistant_chat.py:335",
                                "message": "Web search exception caught",
                                "data": {"error": str(web_search_error), "error_type": str(type(web_search_error).__name__)},
                                "timestamp": int(__import__('time').time() * 1000)
                            }, ensure_ascii=False) + '\n')
                    except:
                        pass
                    # #endregion
                    
                    logger.warning(f"Web search failed: {web_search_error}, continuing without web search")
                    # Continue without web search - не критичная ошибка
            else:
                # #region agent log
                try:
                    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                        f.write(json_module.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H",
                            "location": "assistant_chat.py:485",
                            "message": "Web search condition FALSE - skipping web search",
                            "data": {
                                "web_search": web_search,
                                "web_search_bool": bool(web_search),
                                "question": question[:100]
                            },
                            "timestamp": int(__import__('time').time() * 1000)
                        }, ensure_ascii=False) + '\n')
                except:
                    pass
                # #endregion
            
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

            prompt = f"""Ты - юридический AI-ассистент. Ты помогаешь анализировать документы дела.

Контекст из документов дела:
{context}{web_search_context}

Вопрос пользователя: {question}{web_search_instructions}

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

Ответь на вопрос, используя информацию из документов дела. {f"Если информации из документов недостаточно, используй результаты веб-поиска для дополнения ответа." if web_search_context else "Если информации недостаточно, укажи это."}
Будь точным и профессиональным. ВСЕГДА используй Markdown форматирование.
{f"При цитировании информации из веб-поиска указывай источник в формате: [Название источника](URL) или просто название источника, если URL недоступен." if web_search_context else ""}"""

            # Initialize LLM
            # Используем GigaChat SDK через create_llm()
            # При deep_think=True используем GigaChat-Pro, иначе модель по умолчанию (GigaChat)
            if deep_think:
                llm = create_llm(temperature=0.7, model="GigaChat-Pro")
                logger.info("Using GigaChat-Pro for deep thinking mode")
            else:
                llm = create_llm(temperature=0.7)  # Использует config.GIGACHAT_MODEL (обычно "GigaChat")
            
            # Stream response
            try:
                if hasattr(llm, 'astream'):
                    async for chunk in llm.astream(prompt):
                        if hasattr(chunk, 'content'):
                            content = chunk.content
                        elif isinstance(chunk, str):
                            content = chunk
                        else:
                            content = str(chunk)
                        
                        yield f"data: {json.dumps({'textDelta': content}, ensure_ascii=False)}\n\n"
                    
                    yield f"data: {json.dumps({'textDelta': ''})}\n\n"
                else:
                    # Fallback: get full response and chunk it
                    response = await loop.run_in_executor(None, lambda: llm.invoke(prompt))
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    chunk_size = 20
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i:i + chunk_size]
                        yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.05)
                    
                    yield f"data: {json.dumps({'textDelta': ''})}\n\n"
            except Exception as stream_error:
                logger.warning(f"Streaming failed, using fallback: {stream_error}")
                response = await loop.run_in_executor(None, lambda: llm.invoke(prompt))
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                chunk_size = 20
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)
                
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
    
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
        deep_think = body.get("deep_think", False)
        
        # #region agent log
        import json as json_module
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                f.write(json_module.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A",
                    "location": "assistant_chat.py:554",
                    "message": "Request body parsed",
                    "data": {
                        "web_search_raw": web_search_raw,
                        "web_search_raw_type": str(type(web_search_raw)),
                        "web_search": web_search,
                        "web_search_type": str(type(web_search)),
                        "web_search_bool": bool(web_search),
                        "body_keys": list(body.keys()),
                        "body_web_search_value": body.get("web_search")
                    },
                    "timestamp": int(__import__('time').time() * 1000)
                }, ensure_ascii=False) + '\n')
        except:
            pass
        # #endregion
        
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

