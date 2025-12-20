"""Chat route for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, ChatMessage, File as FileModel
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.langchain_memory import MemoryService
from app.services.langchain_agents import PlanningAgent
from app.services.analysis_service import AnalysisService
from app.config import config
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize RAG service
rag_service = RAGService()
memory_service = MemoryService()


class ChatRequest(BaseModel):
    """Request model for chat"""
    case_id: str = Field(..., min_length=1, description="Case identifier")
    question: str = Field(..., min_length=1, max_length=5000, description="User question")
    
    @field_validator('question')
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError('Question cannot be empty')
        if len(v) > 5000:
            raise ValueError('Question must be at most 5000 characters')
        return v


class ChatResponse(BaseModel):
    """Response model for chat"""
    answer: str
    sources: List[Dict[str, Any]]  # Changed to dict with detailed source info
    status: str


class TaskRequest(BaseModel):
    """Request model for natural language task"""
    case_id: str = Field(..., min_length=1, description="Case identifier")
    task: str = Field(..., min_length=1, max_length=5000, description="Task in natural language")
    
    @field_validator('task')
    @classmethod
    def validate_task(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError('Task cannot be empty')
        if len(v) > 5000:
            raise ValueError('Task must be at most 5000 characters')
        return v


class TaskResponse(BaseModel):
    """Response model for task execution"""
    plan: Dict[str, Any]  # Analysis plan
    status: str  # "planned", "executing"
    message: str


def format_source_reference(source: Dict[str, Any]) -> str:
    """Format source reference for display"""
    file = source.get("file", "unknown")
    page = source.get("page")
    start_line = source.get("start_line")
    
    ref = f"[Документ: {file}"
    if page:
        ref += f", стр. {page}"
    if start_line:
        ref += f", строки {start_line}"
        if source.get("end_line") and source.get("end_line") != start_line:
            ref += f"-{source.get('end_line')}"
    ref += "]"
    return ref


def is_task_request(question: str) -> bool:
    """
    Определяет, является ли запрос задачей для выполнения анализов
    или обычным вопросом
    
    Планировщик запускается ТОЛЬКО для явных команд типа:
    - "Проанализируй документы и найди все риски"
    - "Извлеки все даты из документов"
    - "Создай отчет по делу"
    
    Все остальные вопросы обрабатываются через RAG чат.
    
    Args:
        question: Текст запроса пользователя
    
    Returns:
        True если это задача, False если вопрос
    """
    question_lower = question.lower().strip()
    
    # ВСЕ вопросы с вопросительными словами - это обычные вопросы, не задачи
    question_words = [
        "какие", "что", "где", "когда", "почему", "зачем", "как", 
        "кто", "чей", "чему", "чем", "откуда", "куда",
        "who", "what", "where", "when", "why", "how", "which"
    ]
    
    # Если начинается с вопросительного слова - это обычный вопрос
    first_words = question_lower.split()[:3]
    if any(word in first_words for word in question_words):
        return False
    
    # Разговорные фразы - всегда обычные вопросы
    conversational_phrases = [
        "как дела", "как поживаешь", "привет", "здравствуй", "hello", "hi",
        "что нового", "расскажи", "объясни", "что такое", "кто такой",
        "помоги", "подскажи", "скажи"
    ]
    
    for phrase in conversational_phrases:
        if phrase in question_lower:
            return False
    
    # ЯВНЫЕ команды выполнения - только они запускают планировщик
    # Должны быть в начале предложения или с явным действием
    explicit_task_commands = [
        "проанализируй", "анализируй", "выполни", "извлеки",
        "создай", "сделай", "запусти", "проведи анализ", "провести анализ",
        "сделать анализ", "проанализируй все", "извлеки все",
        "analyze all", "extract all", "create", "generate report",
        "run analysis", "perform analysis", "execute analysis"
    ]
    
    # Проверяем, что команда в начале предложения
    for command in explicit_task_commands:
        if question_lower.startswith(command) or f" {command}" in question_lower:
            return True
    
    # Все остальное - обычные вопросы
    return False


@router.post("/", response_model=ChatResponse, include_in_schema=True)
@router.post("", response_model=ChatResponse, include_in_schema=False)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Send question to ChatGPT based on case documents OR execute task in natural language
    
    Returns: answer, sources, status
    """
    # Get case and verify ownership
    case = db.query(Case).filter(
        Case.id == request.case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Verify case has files uploaded
    file_count = db.query(FileModel).filter(FileModel.case_id == request.case_id).count()
    if file_count == 0:
        raise HTTPException(
            status_code=400,
            detail="В деле нет загруженных документов. Пожалуйста, сначала загрузите документы."
        )
    
    # Check if this is a task request
    if is_task_request(request.question):
        # This is a task - use Planning Agent
        try:
            logger.info(f"Detected task request for case {request.case_id}: {request.question[:100]}...")
            
            # Create Planning Agent
            planning_agent = PlanningAgent()
            
            # Create analysis plan
            plan = planning_agent.plan_analysis(
                user_task=request.question,
                case_id=request.case_id
            )
            
            analysis_types = plan["analysis_types"]
            reasoning = plan.get("reasoning", "План создан на основе задачи")
            confidence = plan.get("confidence", 0.8)
            
            logger.info(
                f"Planning completed for case {request.case_id}: {analysis_types}, "
                f"confidence: {confidence:.2f}"
            )
            
            # Map analysis types to API format (discrepancy -> discrepancies, risk -> risk_analysis)
            api_analysis_types = []
            for at in analysis_types:
                if at == "discrepancy":
                    api_analysis_types.append("discrepancies")
                elif at == "risk":
                    api_analysis_types.append("risk_analysis")
                else:
                    api_analysis_types.append(at)
            
            # Start analysis in background
            from app.utils.database import SessionLocal
            
            # Capture case_id for background task
            task_case_id = request.case_id
            
            def run_planned_analysis():
                """Run analysis in background based on plan"""
                background_db = SessionLocal()
                try:
                    analysis_service = AnalysisService(background_db)
                    
                    if analysis_service.use_agents:
                        # Map back to agent format
                        agent_types = []
                        for at in api_analysis_types:
                            if at == "discrepancies":
                                agent_types.append("discrepancy")
                            elif at == "risk_analysis":
                                agent_types.append("risk")
                            else:
                                agent_types.append(at)
                        
                        logger.info(f"Running planned analysis for case {task_case_id}: {agent_types}")
                        results = analysis_service.run_agent_analysis(task_case_id, agent_types)
                        logger.info(
                            f"Planned analysis completed for case {task_case_id}, "
                            f"execution time: {results.get('execution_time', 0):.2f}s"
                        )
                    else:
                        # Legacy approach
                        logger.info(f"Using legacy analysis for planned task, case {task_case_id}")
                        for analysis_type in api_analysis_types:
                            if analysis_type == "timeline":
                                analysis_service.extract_timeline(task_case_id)
                            elif analysis_type == "discrepancies":
                                analysis_service.find_discrepancies(task_case_id)
                            elif analysis_type == "key_facts":
                                analysis_service.extract_key_facts(task_case_id)
                            elif analysis_type == "summary":
                                analysis_service.generate_summary(task_case_id)
                            elif analysis_type == "risk_analysis":
                                analysis_service.analyze_risks(task_case_id)
                except Exception as e:
                    logger.error(f"Error in planned analysis background task: {e}", exc_info=True)
                finally:
                    background_db.close()
            
            background_tasks.add_task(run_planned_analysis)
            
            try:
                # Update case status
                case.status = "processing"
                if case.case_metadata is None:
                    case.case_metadata = {}
                case.case_metadata["planned_task"] = request.question
                case.case_metadata["planned_analyses"] = api_analysis_types
                case.case_metadata["plan_confidence"] = confidence
                db.commit()
            except Exception as commit_error:
                db.rollback()
                logger.error(f"Ошибка при обновлении статуса дела {request.case_id}: {commit_error}", exc_info=True)
                # Continue - analysis will still run in background
            
            # Create response message
            answer = f"""Я понял вашу задачу и запланировал следующие анализы:

**Планируемые анализы:**
{', '.join(api_analysis_types)}

**Объяснение:** {reasoning}

**Уверенность:** {confidence:.0%}

Анализ выполняется в фоне. Результаты будут доступны через несколько минут. Вы можете проверить статус анализа в разделе отчетов."""
            
            try:
                # Save user message
                user_message = ChatMessage(
                    case_id=request.case_id,
                    role="user",
                    content=request.question,
                    session_id=None  # session_id nullable, не используем внешний ключ
                )
                db.add(user_message)

                # Save assistant message
                assistant_message = ChatMessage(
                    case_id=request.case_id,
                    role="assistant",
                    content=answer,
                    source_references=[],
                    session_id=None  # session_id nullable, не используем внешний ключ
                )
                db.add(assistant_message)
                db.commit()
            except Exception as commit_error:
                db.rollback()
                logger.error(f"Ошибка при сохранении сообщений в БД для дела {request.case_id}: {commit_error}", exc_info=True)
                # Continue - message is already generated
            
            return ChatResponse(
                answer=answer,
                sources=[],
                status="task_planned"
            )
            
        except Exception as e:
            logger.error(f"Error in planning agent: {e}", exc_info=True)
            # Fallback to regular RAG if planning fails
            logger.info("Falling back to RAG for task request")
            # Continue to RAG processing below
    
    # Get chat history
    history_messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == request.case_id
    ).order_by(ChatMessage.created_at.asc()).all()

    # Format history for RAG
    chat_history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_messages[-10:]  # Last 10 messages
    ]
    
    # Load history into memory (optional - don't fail if memory is not available)
    if chat_history:
        try:
            memory_service.load_history_into_memory(
                request.case_id,
                chat_history,
                memory_type="summary"
            )
        except Exception as memory_error:
            logger.warning(
                f"Failed to load history into memory for case {request.case_id}: {memory_error}. "
                "Continuing without memory - chat will still work."
            )
            # Continue - memory is optional, chat works without it
    
    try:
        logger.info(
            f"Processing chat request for case {request.case_id}",
            extra={
                "case_id": request.case_id,
                "user_id": current_user.id,
                "question_length": len(request.question),
                "history_length": len(chat_history),
            }
        )
        
        # Use RAG service to generate answer with sources and memory
        answer, sources = rag_service.generate_answer(
            case_id=request.case_id,
            query=request.question,
            chat_history=chat_history,
            k=5,  # Retrieve top 5 relevant chunks
            retrieval_strategy="multi_query",  # Use improved retrieval
            use_memory=True  # Use memory for context
        )
        
        # Save context to memory (optional - don't fail if memory is not available)
        try:
            memory_service.save_context(
                request.case_id,
                request.question,
                answer,
                memory_type="summary"
            )
        except Exception as memory_error:
            logger.warning(
                f"Failed to save context to memory for case {request.case_id}: {memory_error}. "
                "Continuing without memory - chat will still work."
            )
            # Continue - memory is optional, chat works without it
        
        logger.info(
            f"Successfully generated answer for case {request.case_id}",
            extra={
                "case_id": request.case_id,
                "answer_length": len(answer),
                "num_sources": len(sources),
            }
        )
        
        # Ensure answer contains source references
        if sources:
            # Add source references to answer if not already present
            source_refs = "\n\n**Источники:**\n"
            for i, source in enumerate(sources, 1):
                source_ref = format_source_reference(source)
                source_refs += f"{i}. {source_ref}\n"
            answer += source_refs
        
        try:
            # Save user message
            user_message = ChatMessage(
                case_id=request.case_id,
                role="user",
                content=request.question,
                session_id=None  # session_id nullable, не используем внешний ключ
            )
            db.add(user_message)
            
            # Save assistant message
            # Extract source file names for backward compatibility
            source_file_names = [s.get("file", "") for s in (sources or []) if isinstance(s, dict)]
            assistant_message = ChatMessage(
                case_id=request.case_id,
                role="assistant",
                content=answer,
                source_references=source_file_names or [],
                session_id=None  # session_id nullable, не используем внешний ключ
            )
            db.add(assistant_message)
            
            db.commit()
        except Exception as commit_error:
            db.rollback()
            logger.error(f"Ошибка при сохранении сообщений в БД для дела {request.case_id}: {commit_error}", exc_info=True)
            # Continue - message is already generated, just log the error
        
        return ChatResponse(
            answer=answer,
            sources=sources,  # Return detailed source info
            status="success"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа через RAG: {e}")
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Ошибка аутентификации OpenRouter API. Проверьте API ключ."
            )
        elif "rate limit" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышен лимит запросов к OpenRouter API. Попробуйте позже."
            )
        elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышено время ожидания ответа от OpenRouter API. "
                "Попробуйте упростить запрос или повторить попытку позже."
            )
        else:
            logger.error(f"Ошибка при генерации ответа для дела {request.case_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Ошибка при генерации ответа. Попробуйте позже."
            )


@router.post("/task", response_model=TaskResponse)
async def execute_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Execute task in natural language using planning agent
    
    Example: "Проанализируй документы и найди все риски"
    
    Returns: plan, status, message
    """
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == request.case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        logger.info(f"Task execution request for case {request.case_id}: {request.task[:100]}...")
        
        # Create Planning Agent
        planning_agent = PlanningAgent()
        
        # Plan analysis
        plan = planning_agent.plan_analysis(
            user_task=request.task,
            case_id=request.case_id
        )
        
        analysis_types = plan["analysis_types"]
        reasoning = plan.get("reasoning", "План создан на основе задачи")
        confidence = plan.get("confidence", 0.8)
        
        # Map analysis types to API format
        api_analysis_types = []
        for at in analysis_types:
            if at == "discrepancy":
                api_analysis_types.append("discrepancies")
            elif at == "risk":
                api_analysis_types.append("risk_analysis")
            else:
                api_analysis_types.append(at)
        
        # Start analysis in background
        from app.utils.database import SessionLocal
        
        # Capture case_id for background task
        task_case_id = request.case_id
        
        def run_planned_analysis():
            """Run analysis in background based on plan"""
            background_db = SessionLocal()
            try:
                analysis_service = AnalysisService(background_db)
                
                if analysis_service.use_agents:
                    # Map back to agent format
                    agent_types = []
                    for at in api_analysis_types:
                        if at == "discrepancies":
                            agent_types.append("discrepancy")
                        elif at == "risk_analysis":
                            agent_types.append("risk")
                        else:
                            agent_types.append(at)
                    
                    logger.info(f"Running planned analysis for case {task_case_id}: {agent_types}")
                    results = analysis_service.run_agent_analysis(task_case_id, agent_types)
                    logger.info(
                        f"Planned analysis completed for case {task_case_id}, "
                        f"execution time: {results.get('execution_time', 0):.2f}s"
                    )
                else:
                    # Legacy approach
                    for analysis_type in api_analysis_types:
                        if analysis_type == "timeline":
                            analysis_service.extract_timeline(task_case_id)
                        elif analysis_type == "discrepancies":
                            analysis_service.find_discrepancies(task_case_id)
                        elif analysis_type == "key_facts":
                            analysis_service.extract_key_facts(task_case_id)
                        elif analysis_type == "summary":
                            analysis_service.generate_summary(task_case_id)
                        elif analysis_type == "risk_analysis":
                            analysis_service.analyze_risks(task_case_id)
            except Exception as e:
                logger.error(f"Error in planned analysis background task: {e}", exc_info=True)
            finally:
                background_db.close()
        
        background_tasks.add_task(run_planned_analysis)
        
        # Update case status
        case.status = "processing"
        if case.case_metadata is None:
            case.case_metadata = {}
        case.case_metadata["planned_task"] = request.task
        case.case_metadata["planned_analyses"] = api_analysis_types
        case.case_metadata["plan_confidence"] = confidence
        db.commit()
        
        return TaskResponse(
            plan={
                "analysis_types": api_analysis_types,
                "reasoning": reasoning,
                "confidence": confidence
            },
            status="executing",
            message=f"Задача запланирована: {reasoning}"
        )
        
    except Exception as e:
        logger.error(f"Error in task execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при планировании задачи: {str(e)}"
        )


@router.get("/{case_id}/history")
async def get_history(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get chat history for a case
    
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

