"""Chat route for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional, Dict, Any
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.utils.authorization import require_case_access, require_case_write
from app.models.case import Case, ChatMessage, File as FileModel
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_memory import MemoryService
from app.services.llm_factory import create_legal_llm
from app.services.external_sources.web_research_service import get_web_research_service
from app.services.external_sources.source_router import initialize_source_router
from app.core.container import get_rag_service, get_document_processor, get_memory_service
from app.config import config
from datetime import datetime
import re
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()

_TASK_COMMAND_RE = re.compile(
    r"\b(?:"
    r"проанализируй|анализируй|выполни|найди|извлеки|создай|сделай|запусти|проведи|провести|"
    r"analyze|extract|find|create|generate|run|perform|execute"
    r")\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX_RE = re.compile(r"^\s*(как|что|почему|зачем|когда|где|кто|какие?)\b", re.IGNORECASE)


def is_task_request(text: str) -> bool:
    """
    Быстро определить, является ли запрос "задачей" (task) для /api/chat/task,
    а не вопросом для обычного RAG-ответа.
    """

    q = (text or "").strip()
    if not q:
        return False
    # Явные вопросы — не task, даже если содержат "командное" слово
    if _QUESTION_PREFIX_RE.search(q) or "?" in q:
        return False
    return bool(_TASK_COMMAND_RE.search(q))


class ChatRequest(BaseModel):
    """Request model for chat"""
    case_id: str = Field(..., min_length=1, description="Case identifier")
    question: str = Field(..., min_length=1, max_length=5000, description="User question")
    web_search: bool = Field(False, description="Enable web search")
    legal_research: bool = Field(False, description="Enable legal research")
    deep_think: bool = Field(False, description="Enable deep thinking mode")
    
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


class ImprovePromptRequest(BaseModel):
    """Request model for prompt improvement"""
    prompt: str = Field(..., min_length=1, max_length=5000, description="Prompt to improve")
    context: Optional[Dict[str, Any]] = Field(None, description="Optional context for improvement")


class ImprovePromptResponse(BaseModel):
    """Response model for prompt improvement"""
    original: str
    improved: str
    suggestions: List[str] = []
    improvements_applied: List[str] = []


class TaskResponse(BaseModel):
    """Response model for task execution"""
    plan: Dict[str, Any]  # Analysis plan
    status: str  # "planned", "executing"
    message: str


def _format_plan_for_display(plan: Dict[str, Any], validation_result) -> str:
    """Форматирует план для отображения пользователю (поддерживает подзадачи)"""
    display = ""
    
    # Main task
    main_task = plan.get("main_task", "")
    if main_task:
        display += f"**Задача:** {main_task}\n\n"
    
    # Goals
    if "goals" in plan and plan["goals"]:
        display += "**Цели:**\n"
        for idx, goal in enumerate(plan["goals"], 1):
            display += f"{idx}. {goal.get('description', '')}\n"
        display += "\n"
    
    # Subtasks (приоритет над steps)
    subtasks = plan.get("subtasks", [])
    if subtasks:
        display += f"**Подзадачи ({len(subtasks)}):**\n"
        for idx, subtask in enumerate(subtasks, 1):
            subtask_id = subtask.get("subtask_id", f"subtask_{idx}")
            description = subtask.get("description", "")
            agent_type = subtask.get("agent_type", "")
            estimated_time = subtask.get("estimated_time", "")
            dependencies = subtask.get("dependencies", [])
            reasoning = subtask.get("reasoning", "")
            
            display += f"\n{idx}. **{description}**\n"
            if agent_type:
                display += f"   - Агент: {agent_type}\n"
            if estimated_time:
                display += f"   - Время: {estimated_time}\n"
            if dependencies:
                deps_str = ", ".join(dependencies)
                display += f"   - Зависимости: {deps_str}\n"
            if reasoning:
                display += f"   - Обоснование: {reasoning}\n"
        display += "\n"
    else:
        # Analysis types (fallback)
        analysis_types = plan.get("analysis_types", [])
        if analysis_types:
            display += f"**Планируемые анализы:** {', '.join(analysis_types)}\n\n"
        
        # Steps (fallback)
        if "steps" in plan and plan["steps"]:
            display += "**Детали плана:**\n"
            for idx, step in enumerate(plan["steps"][:5], 1):
                step_desc = step.get("description", step.get("agent_name", "unknown"))
                step_time = step.get("estimated_time", "")
                display += f"{idx}. {step_desc}"
                if step_time:
                    display += f" (~{step_time})"
                display += "\n"
            if len(plan["steps"]) > 5:
                display += f"... и еще {len(plan['steps']) - 5} шагов\n"
            display += "\n"
    
    # Tables to create
    tables_to_create = plan.get("tables_to_create", [])
    if tables_to_create:
        display += "**Таблицы для создания:**\n"
        for table in tables_to_create:
            display += f"- {table}\n"
        display += "\n"
    
    # Estimated time
    estimated_time = plan.get("estimated_time", plan.get("estimated_execution_time", ""))
    if not estimated_time and validation_result:
        estimated_time = validation_result.estimated_time
    if estimated_time:
        display += f"**Оценка времени:** {estimated_time}\n\n"
    
    # Reasoning
    reasoning = plan.get("reasoning", "")
    if reasoning:
        display += f"**Обоснование плана:**\n{reasoning}\n\n"
    
    return display


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




@router.post("/", response_model=ChatResponse, include_in_schema=True)
@router.post("", response_model=ChatResponse, include_in_schema=False)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Send question to ChatGPT based on case documents with optional web search, legal research, and deep thinking
    
    Returns: answer, sources, status
    """
    # Get case and verify ownership
    case = require_case_write(db, case_id, current_user.id)
    # Verify case has files uploaded
    file_count = db.query(FileModel).filter(FileModel.case_id == request.case_id).count()
    if file_count == 0:
        raise HTTPException(
            status_code=400,
            detail="В деле нет загруженных документов. Пожалуйста, сначала загрузите документы."
        )
    
    # REMOVED: Закомментированный код агентов (305 строк) - не используется
    # Process question with RAG and optional enhancements (web search, legal research, deep thinking)
    
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
            get_memory_service().load_history_into_memory(
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
        
        # Use RAG service to generate answer with sources
        # Support structured output with mandatory citations via config
        from app.config import config
        use_citation_first = config.CITATION_FIRST_ENABLED
        
        rag_service = get_rag_service()  # Lazy initialization
        if config.RAG_USE_STRUCTURED_OUTPUT:
            # Use structured output with mandatory citations
            structured_response, sources = rag_service.generate_with_sources_structured(
                case_id=request.case_id,
                query=request.question,
                k=5,  # Retrieve top 5 relevant chunks
                db=db,
                history=chat_history
            )
            # Extract answer from structured response
            answer = structured_response.answer
        else:
            # Fallback to regular generation
            answer, sources = rag_service.generate_with_sources(
                case_id=request.case_id,
                query=request.question,
                k=5,  # Retrieve top 5 relevant chunks
                db=db,  # Pass database session for Assistant API
                history=chat_history,  # Pass chat history for Assistant API
                use_citation_first=use_citation_first  # Phase 2: Citation-first generation
            )
        
        # Save context to memory (optional - don't fail if memory is not available)
        try:
            get_memory_service().save_context(
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
            # session_id is nullable - no need to create chat_sessions entry
            user_message = ChatMessage(
                case_id=request.case_id,
                role="user",
                content=request.question,
                session_id=None  # Nullable field, no foreign key constraint violation
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
                session_id=None  # Nullable field, no foreign key constraint violation
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
                detail="Ошибка аутентификации LLM API. Проверьте настройки GigaChat."
            )
        elif "rate limit" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(
                status_code=500,
                detail="Превышен лимит запросов к LLM API. Попробуйте позже."
            )
        elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышено время ожидания ответа от LLM API. "
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
    case = require_case_write(db, case_id, current_user.id)
    try:
        logger.info(f"Task execution request for case {request.case_id}: {request.task[:100]}...")
        
        # Create Planning Agent
        from app.services.langchain_agents.planning_agent import PlanningAgent
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


class ApprovePlanRequest(BaseModel):
    """Request model for plan approval"""
    plan_id: str = Field(..., description="Plan ID to approve")
    approved: bool = Field(True, description="Whether to approve the plan")


class ApprovePlanResponse(BaseModel):
    """Response model for plan approval"""
    success: bool
    message: str
    plan_id: str
    status: str


@router.post("/approve-plan", response_model=ApprovePlanResponse)
async def approve_plan(
    request: ApprovePlanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Approve or reject an analysis plan
    
    Args:
        request: Approval request with plan_id and approved flag
        db: Database session
        current_user: Current user
        
    Returns:
        Approval response with status
    """
    try:
        from app.models.analysis import AnalysisPlan
        from app.services.analysis_service import AnalysisService
        from app.utils.database import SessionLocal
        
        # Get plan from database
        plan = db.query(AnalysisPlan).filter(
            AnalysisPlan.id == request.plan_id,
            AnalysisPlan.user_id == current_user.id
        ).first()
        
        if not plan:
            raise HTTPException(
                status_code=404,
                detail=f"Plan {request.plan_id} not found"
            )
        
        if plan.status != "pending_approval":
            raise HTTPException(
                status_code=400,
                detail=f"Plan is already {plan.status}, cannot approve"
            )
        
        if request.approved:
            # Approve plan
            plan.status = "approved"
            plan.approved_at = datetime.utcnow()
            db.commit()
            
            # Start execution in background
            plan_id_for_execution = plan.id  # Capture plan_id before background execution
            def execute_approved_plan():
                """Execute approved plan in background"""
                background_db = SessionLocal()
                plan = None  # Initialize to avoid UnboundLocalError
                try:
                    # Re-query plan from DB to ensure it's attached to background_db session
                    plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                    if not plan:
                        logger.error(f"Plan {plan_id_for_execution} not found in database")
                        return
                    
                    # Get plan data - modify in place to ensure SQLAlchemy tracks changes
                    if not plan.plan_data:
                        plan.plan_data = {}
                    plan_data = plan.plan_data
                    if not isinstance(plan_data, dict):
                        plan_data = {}
                        plan.plan_data = plan_data
                    case_id = plan.case_id
                    
                    # Get analysis types from plan
                    analysis_types = plan_data.get("analysis_types", [])
                    subtasks = plan_data.get("subtasks", [])
                    
                    # If subtasks exist, use them
                    if subtasks:
                        analysis_types = [subtask.get("agent_type") for subtask in subtasks if subtask.get("agent_type")]
                    
                    # Map to API format
                    api_analysis_types = []
                    for at in analysis_types:
                        if at == "discrepancy":
                            api_analysis_types.append("discrepancies")
                        elif at == "risk":
                            api_analysis_types.append("risk_analysis")
                        else:
                            api_analysis_types.append(at)
                    
                    # Update plan status
                    plan.status = "executing"
                    plan.executed_at = datetime.utcnow()
                    background_db.commit()
                    # Re-query to ensure plan is attached to session
                    plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                    
                    # Execute analyses using agent system
                    # Verify background_db is not None before creating AnalysisService
                    if background_db is None:
                        raise ValueError("background_db is None, cannot create AnalysisService")
                    logger.info(f"Creating AnalysisService with background_db for case {case_id}")
                    try:
                        analysis_service = AnalysisService(background_db)
                        logger.info(f"AnalysisService created successfully for case {case_id}")
                    except TypeError as e:
                        logger.error(f"Error creating AnalysisService: {e}, background_db type: {type(background_db)}")
                        raise
                    
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
                        
                        # Create callback to save steps in real-time
                        def save_step_to_plan(step_info: dict):
                            """Save execution step to plan in real-time"""
                            try:
                                # Refresh plan from DB
                                plan_refresh = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                                if plan_refresh:
                                    # Modify in place for SQLAlchemy tracking
                                    if not plan_refresh.plan_data:
                                        plan_refresh.plan_data = {}
                                    plan_data = plan_refresh.plan_data
                                    if not isinstance(plan_data, dict):
                                        plan_data = {}
                                        plan_refresh.plan_data = plan_data
                                    execution_steps = plan_data.get("execution_steps", [])
                                    # Check if step already exists
                                    if not any(s.get("step_id") == step_info.get("step_id") for s in execution_steps):
                                        execution_steps.append(step_info)
                                        plan_data["execution_steps"] = execution_steps
                                        # plan_data is already a reference to plan_refresh.plan_data
                                        flag_modified(plan_refresh, "plan_data")
                                        background_db.flush()  # Ensure changes are processed before commit
                                        background_db.commit()
                            except Exception as e:
                                logger.warning(f"Error saving step to plan: {e}")
                        
                        logger.info(f"Running approved plan for case {case_id}: {agent_types}")
                        results = analysis_service.run_agent_analysis(
                            case_id, 
                            agent_types,
                            step_callback=save_step_to_plan
                        )
                        logger.info(
                            f"Approved plan execution completed for case {case_id}, "
                            f"execution_time: {results.get('execution_time', 0):.2f}s"
                        )
                        
                        # Re-query plan to ensure we have the latest data
                        plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                        if not plan:
                            logger.error(f"Plan {plan_id_for_execution} not found when saving results")
                            return
                        
                        # Final save of all execution steps (in case callback missed any)
                        execution_steps = results.get("execution_steps", [])
                        # Ensure plan_data exists and is a dict - modify in place for SQLAlchemy tracking
                        if not plan.plan_data:
                            plan.plan_data = {}
                        plan_data = plan.plan_data
                        if not isinstance(plan_data, dict):
                            plan_data = {}
                            plan.plan_data = plan_data
                        
                        if execution_steps:
                            plan_data["execution_steps"] = execution_steps
                        
                        # Save table_results and delivery_result for table_created events
                        # Extract tables from delivery_result if available
                        # Check both "delivery" key and direct delivery_result in results
                        delivery_result = results.get("delivery") or results.get("delivery_result", {})
                        if delivery_result and isinstance(delivery_result, dict):
                            plan_data["delivery_result"] = delivery_result
                            # Also save tables separately for easier access
                            if delivery_result.get("tables"):
                                plan_data["table_results"] = delivery_result.get("tables")
                                logger.info(f"Saved {len(delivery_result.get('tables', {}))} table results to plan_data")
                        elif results.get("tables"):
                            # Fallback: save tables directly if delivery_result not available
                            plan_data["table_results"] = results.get("tables")
                            logger.info(f"Saved {len(results.get('tables', {}))} table results to plan_data (fallback)")
                        
                        # CRITICAL: Explicitly reassign plan.plan_data to ensure SQLAlchemy tracks the change
                        # Even though plan_data is a reference, SQLAlchemy needs explicit reassignment for JSON fields
                        plan.plan_data = plan_data
                        flag_modified(plan, "plan_data")
                        background_db.flush()  # Ensure changes are processed before commit
                        background_db.commit()
                        # Re-query plan to ensure we have the latest data (refresh fails if plan is not in session)
                        plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                        # #endregion
                    else:
                        # Legacy approach
                        logger.warning(f"Agents not enabled, using legacy analysis")
                        for analysis_type in api_analysis_types:
                            try:
                                if analysis_type == "timeline":
                                    analysis_service.extract_timeline(case_id)
                                elif analysis_type == "discrepancies":
                                    analysis_service.find_discrepancies(case_id)
                                elif analysis_type == "key_facts":
                                    analysis_service.extract_key_facts(case_id)
                                elif analysis_type == "summary":
                                    analysis_service.generate_summary(case_id)
                                elif analysis_type == "risk_analysis":
                                    analysis_service.analyze_risks(case_id)
                                elif analysis_type == "entity_extraction":
                                    analysis_service.extract_entities(case_id)
                                elif analysis_type == "relationship":
                                    analysis_service.build_relationships(case_id)
                            except Exception as e:
                                logger.error(f"Error executing {analysis_type}: {e}", exc_info=True)
                    
                    # Mark plan as completed
                    plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                    if plan:
                        plan.status = "completed"
                        background_db.commit()
                    
                except Exception as e:
                    logger.error(f"Error in approved plan execution: {e}", exc_info=True)
                    plan = background_db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id_for_execution).first()
                    if plan:
                        plan.status = "failed"
                        background_db.commit()
                finally:
                    background_db.close()
            
            background_tasks.add_task(execute_approved_plan)
            
            return ApprovePlanResponse(
                success=True,
                message="Plan approved and execution started",
                plan_id=plan.id,
                status="executing"
            )
        else:
            # Reject plan
            plan.status = "rejected"
            db.commit()
            
            return ApprovePlanResponse(
                success=True,
                message="Plan rejected",
                plan_id=plan.id,
                status="rejected"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving plan: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при подтверждении плана: {str(e)}"
        )


@router.get("/sessions")
async def get_chat_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of chat sessions (grouped by case) for current user
    
    Returns: list of sessions with case_id, case_name, last_message, last_message_at, message_count
    """
    try:
        from sqlalchemy import func, desc
        
        # Get all accessible cases for current user
        from app.services.case_sharing_service import accessible_case_ids_subquery
        cases = db.query(Case).filter(
            Case.id.in_(accessible_case_ids_subquery(db, current_user.id))
        ).all()
        
        sessions = []
        for case in cases:
            # Get last message for this case
            last_message = db.query(ChatMessage).filter(
                ChatMessage.case_id == case.id
            ).order_by(desc(ChatMessage.created_at)).first()
            
            # Get message count
            message_count = db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.case_id == case.id
            ).scalar() or 0
            
            # Skip cases with no messages
            if message_count == 0:
                continue
            
            # Get last message preview (first 100 chars)
            last_message_preview = ""
            if last_message and last_message.content:
                last_message_preview = last_message.content[:100]
                if len(last_message.content) > 100:
                    last_message_preview += "..."
            
            sessions.append({
                "case_id": case.id,
                "case_name": case.title or f"Дело {case.id[:8]}",
                "last_message": last_message_preview,
                "last_message_at": last_message.created_at.isoformat() if last_message and last_message.created_at else None,
                "message_count": message_count
            })
        
        # Sort by last_message_at DESC
        sessions.sort(key=lambda x: x["last_message_at"] or "", reverse=True)
        
        return sessions
    except Exception as e:
        logger.error(f"Error getting chat sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get chat sessions")


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
    case = require_case_access(db, case_id, current_user.id)
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


@router.post("/{case_id}/export")
async def export_chat_history(
    case_id: str,
    format: str = "markdown",  # markdown or pdf
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export chat history for a case
    
    Returns: Markdown or PDF file with chat history
    """
    from fastapi.responses import Response
    
    # Check if case exists and verify ownership
    case = require_case_write(db, case_id, current_user.id)
    # Get messages
    messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == case_id
    ).order_by(ChatMessage.created_at.asc()).all()
    
    if format == "markdown":
        # Generate Markdown
        markdown_lines = []
        markdown_lines.append(f"# История чата - {case.title or 'Без названия'}")
        markdown_lines.append(f"**Дата экспорта:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        markdown_lines.append(f"**Количество сообщений:** {len(messages)}")
        markdown_lines.append("")
        markdown_lines.append("---")
        markdown_lines.append("")
        
        for i, msg in enumerate(messages, 1):
            timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S') if msg.created_at else 'Неизвестно'
            markdown_lines.append(f"## Сообщение {i}")
            markdown_lines.append(f"**Роль:** {msg.role}")
            markdown_lines.append(f"**Время:** {timestamp}")
            markdown_lines.append("")
            markdown_lines.append("**Содержание:**")
            markdown_lines.append("")
            markdown_lines.append(msg.content or "")
            markdown_lines.append("")
            
            if msg.source_references:
                markdown_lines.append("**Источники:**")
                for source in msg.source_references:
                    if isinstance(source, dict):
                        source_text = source.get('file') or source.get('title', 'Источник')
                        if source.get('page'):
                            source_text += f" (стр. {source['page']})"
                        markdown_lines.append(f"- {source_text}")
                    else:
                        markdown_lines.append(f"- {source}")
                markdown_lines.append("")
            
            markdown_lines.append("---")
            markdown_lines.append("")
        
        markdown_content = "\n".join(markdown_lines)
        
        return Response(
            content=markdown_content.encode('utf-8'),
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="chat-history-{case_id}-{datetime.utcnow().strftime("%Y%m%d")}.md"'
            }
        )
    else:
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат. Используйте 'markdown'")


@router.post("/improve-prompt", response_model=ImprovePromptResponse)
async def improve_prompt_endpoint(
    request: ImprovePromptRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Improve a user's prompt using Magic Prompt feature
    
    Returns: original prompt, improved prompt, and suggestions
    """
    try:
        from app.services.prompt_improver import improve_prompt
        
        result = await improve_prompt(request.prompt, request.context)
        
        return ImprovePromptResponse(
            original=result.get("original", request.prompt),
            improved=result.get("improved", request.prompt),
            suggestions=result.get("suggestions", []),
            improvements_applied=result.get("improvements_applied", [])
        )
    except Exception as e:
        logger.error(f"Error improving prompt: {e}", exc_info=True)
        # Return original prompt if improvement fails
        return ImprovePromptResponse(
            original=request.prompt,
            improved=request.prompt,
            suggestions=[],
            improvements_applied=[]
        )

