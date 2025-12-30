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
    background_tasks: BackgroundTasks
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
        
        # Классифицируем запрос - задача или вопрос?
        classification_llm = create_llm(temperature=0.0)
        is_task = await classify_request(question, classification_llm)
        
        # #region agent log
        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
            import json as json_debug
            f.write(json_debug.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"assistant_chat.py:148","message":"Classification result","data":{"is_task":is_task,"asyncio_available":hasattr(__import__('asyncio'),'sleep')},"timestamp":int(__import__('time').time()*1000)})+"\n")
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
                
                logger.info(f"Planning completed: {len(analysis_types)} steps, confidence: {confidence:.2f}")
                
                # Формируем ответ с планом
                plan_text = f"""Я составил план анализа для вашей задачи:

**План:**
{reasoning}

**Типы анализов:** {', '.join(analysis_types)}
**Уверенность:** {confidence:.0%}

Запускаю выполнение анализа в фоновом режиме. Результаты будут доступны в разделе "Анализ"."""
                
                # Stream plan response
                # #region agent log
                with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                    import json as json_debug
                    try:
                        asyncio_test = asyncio
                        asyncio_available = True
                    except UnboundLocalError as e:
                        asyncio_available = False
                        asyncio_error = str(e)
                    f.write(json_debug.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"assistant_chat.py:207","message":"Before asyncio.sleep in task block","data":{"asyncio_available":asyncio_available,"error":asyncio_error if not asyncio_available else None},"timestamp":int(__import__('time').time()*1000)})+"\n")
                # #endregion
                for chunk in plan_text:
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)  # Small delay for streaming effect
                
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
                
                # Start analysis in background
                from app.utils.database import SessionLocal
                
                def run_planned_analysis():
                    """Run analysis in background based on plan"""
                    background_db = SessionLocal()
                    try:
                        analysis_service = AnalysisService(background_db)
                        
                        if analysis_service.use_agents:
                            # Map to agent format
                            agent_types = []
                            for at in analysis_types:
                                if at == "discrepancy":
                                    agent_types.append("discrepancy")
                                elif at == "risk":
                                    agent_types.append("risk")
                                else:
                                    agent_types.append(at)
                            
                            logger.info(f"Running planned analysis for case {case_id}: {agent_types}")
                            results = analysis_service.run_agent_analysis(case_id, agent_types)
                            logger.info(
                                f"Planned analysis completed for case {case_id}, "
                                f"execution time: {results.get('execution_time', 0):.2f}s"
                            )
                        else:
                            logger.warning(f"Agents not enabled, using legacy analysis")
                    except Exception as e:
                        logger.error(f"Error in background analysis: {e}", exc_info=True)
                    finally:
                        background_db.close()
                
                # Add background task
                background_tasks.add_task(run_planned_analysis)
                
            except Exception as e:
                logger.error(f"Error in task planning: {e}", exc_info=True)
                error_msg = f"Ошибка при планировании задачи: {str(e)}"
                yield f"data: {json.dumps({'textDelta': error_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        else:
            # Это вопрос - используем RAG + LLM
            # #region agent log
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                import json as json_debug
                f.write(json_debug.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"assistant_chat.py:256","message":"Before local asyncio import in else block","data":{"asyncio_in_globals":"asyncio" in __import__('sys').modules},"timestamp":int(__import__('time').time()*1000)})+"\n")
            # #endregion
            import asyncio
            # #region agent log
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                import json as json_debug
                f.write(json_debug.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"assistant_chat.py:258","message":"After local asyncio import","data":{},"timestamp":int(__import__('time').time()*1000)})+"\n")
            # #endregion
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
            
            # Create prompt
            prompt = f"""Ты - юридический AI-ассистент. Ты помогаешь анализировать документы дела.

Контекст из документов дела:
{context}

Вопрос пользователя: {question}

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

Ответь на вопрос, используя информацию из документов. Если информации недостаточно, укажи это.
Будь точным и профессиональным. ВСЕГДА используй Markdown форматирование."""

            # Initialize LLM
            llm = create_llm(temperature=0.7)
            
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
                background_tasks=background_tasks
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

