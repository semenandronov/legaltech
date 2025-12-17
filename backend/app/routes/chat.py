"""Chat route for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, ChatMessage
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
    
    Args:
        question: Текст запроса пользователя
    
    Returns:
        True если это задача, False если вопрос
    """
    question_lower = question.lower().strip()
    
    # Ключевые слова для задач (команды выполнения)
    task_keywords = [
        "проанализируй", "анализируй", "выполни", "найди", "извлеки",
        "создай", "сделай", "запусти", "проведи", "провести",
        "проведу", "провести анализ", "сделать анализ",
        "analyze", "extract", "find", "create", "generate",
        "run", "perform", "execute"
    ]
    
    # Проверка на команды выполнения
    for keyword in task_keywords:
        if keyword in question_lower:
            return True
    
    # Проверка на конкретные типы анализов в запросе
    analysis_keywords = [
        "timeline", "хронология", "даты", "события",
        "key facts", "ключевые факты", "факты",
        "discrepancy", "противоречия", "несоответствия",
        "risk", "риски", "анализ рисков",
        "summary", "резюме", "краткое содержание"
    ]
    
    # Если есть упоминание типов анализов + команда или конструкция задачи
    has_analysis_keyword = any(keyword in question_lower for keyword in analysis_keywords)
    has_task_structure = any(word in question_lower for word in ["все", "всех", "всех", "какие", "какие-либо"])
    
    if has_analysis_keyword and (has_task_structure or any(cmd in question_lower for cmd in ["нужно", "требуется", "необходимо"])):
        return True
    
    return False


@router.post("/", response_model=ChatResponse)
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
            
            # Update case status
            case.status = "processing"
            if case.case_metadata is None:
                case.case_metadata = {}
            case.case_metadata["planned_task"] = request.question
            case.case_metadata["planned_analyses"] = api_analysis_types
            case.case_metadata["plan_confidence"] = confidence
            db.commit()
            
            # Create response message
            answer = f"""Я понял вашу задачу и запланировал следующие анализы:

**Планируемые анализы:**
{', '.join(api_analysis_types)}

**Объяснение:** {reasoning}

**Уверенность:** {confidence:.0%}

Анализ выполняется в фоне. Результаты будут доступны через несколько минут. Вы можете проверить статус анализа в разделе отчетов."""
            
            # Save user message
            user_message = ChatMessage(
                case_id=request.case_id,
                role="user",
                content=request.question
            )
            db.add(user_message)
            
            # Save assistant message
            assistant_message = ChatMessage(
                case_id=request.case_id,
                role="assistant",
                content=answer,
                source_references=[]
            )
            db.add(assistant_message)
            db.commit()
            
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
    
    # Load history into memory
    if chat_history:
        memory_service.load_history_into_memory(
            request.case_id,
            chat_history,
            memory_type="summary"
        )
    
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
        
        # Save context to memory
        memory_service.save_context(
            request.case_id,
            request.question,
            answer,
            memory_type="summary"
        )
        
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
        
        # Save user message
        user_message = ChatMessage(
            case_id=request.case_id,
            role="user",
            content=request.question
        )
        db.add(user_message)
        
        # Save assistant message
        # Extract source file names for backward compatibility
        source_file_names = [s.get("file", "") for s in sources]
        assistant_message = ChatMessage(
            case_id=request.case_id,
            role="assistant",
            content=answer,
            source_references=source_file_names
        )
        db.add(assistant_message)
        
        db.commit()
        
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
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при генерации ответа: {str(e)}"
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
                "content": msg.content,
                "sources": msg.source_references or [],
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }

