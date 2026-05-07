"""API routes for Agentic Workflows"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, AsyncIterator
from pydantic import BaseModel, Field
from app.models.workflow import (
    WorkflowDefinition, 
    WorkflowExecution, 
    WorkflowStep,
    WORKFLOW_CATEGORIES,
    WORKFLOW_TOOLS,
    SYSTEM_WORKFLOW_TEMPLATES,
    normalize_workflow_tool_name,
)
from app.models.case import File
from app.services.workflows.execution_engine import ExecutionEngine
from app.services.workflows.events import ExecutionEvent
from app.services.workflows.planning_agent import PlanningAgent
from app.services.workflows.deepagents_planning_service import DeepAgentsPlanningService
from app.services.workflows.tool_registry import ToolRegistry
from app.services.workflows.result_validator import ResultValidator
from app.utils.database import get_db, SessionLocal
from sqlalchemy.exc import OperationalError as SAOperationalError, TimeoutError as SATimeoutError
from app.utils.auth import get_current_user
from app.models.user import User
from datetime import datetime
import logging
import json
import asyncio
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow-agentic", tags=["workflow-agentic"])


def _normalize_tool_list(tool_names: Optional[List[str]]) -> List[str]:
    canonical = []
    seen = set()
    for name in tool_names or []:
        normalized = normalize_workflow_tool_name(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            canonical.append(normalized)
    return canonical


def _known_tools() -> set[str]:
    return {t["name"] for t in WORKFLOW_TOOLS}


def _validate_known_tools(
    available_tools: Optional[List[str]],
    default_plan: Optional[dict]
) -> None:
    known = _known_tools()
    unknown = set()

    for tool_name in available_tools or []:
        normalized = normalize_workflow_tool_name(tool_name)
        if normalized and normalized not in known:
            unknown.add(tool_name)

    if isinstance(default_plan, dict):
        for step in default_plan.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            tool_name = step.get("tool_name") or step.get("tool")
            if not tool_name:
                continue
            normalized = normalize_workflow_tool_name(tool_name)
            if normalized not in known:
                unknown.add(tool_name)

    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                "Unknown workflow tools: "
                + ", ".join(sorted(unknown))
                + f". Allowed tools: {', '.join(sorted(known))}"
            ),
        )


def _normalize_default_plan(default_plan: Optional[dict]) -> Optional[dict]:
    if not isinstance(default_plan, dict):
        return default_plan
    steps = default_plan.get("steps")
    if not isinstance(steps, list):
        return default_plan
    normalized_steps = []
    for step in steps:
        if not isinstance(step, dict):
            normalized_steps.append(step)
            continue
        tool_name = step.get("tool_name") or step.get("tool")
        normalized_tool = normalize_workflow_tool_name(tool_name) if tool_name else tool_name
        normalized_step = dict(step)
        if "tool" in normalized_step and normalized_tool:
            normalized_step["tool"] = normalized_tool
        if "tool_name" in normalized_step and normalized_tool:
            normalized_step["tool_name"] = normalized_tool
        normalized_steps.append(normalized_step)
    out = dict(default_plan)
    out["steps"] = normalized_steps
    return out


def _ensure_system_definitions(db: Session) -> None:
    """
    Upsert system workflow definitions from SYSTEM_WORKFLOW_TEMPLATES.
    Ensures new templates become available in existing databases.
    """
    all_system_rows = db.query(WorkflowDefinition).filter(WorkflowDefinition.is_system == True).all()
    existing = {row.name: row for row in all_system_rows}
    desired_names = {t["name"] for t in SYSTEM_WORKFLOW_TEMPLATES}
    changed = False
    for template in SYSTEM_WORKFLOW_TEMPLATES:
        normalized_tools = _normalize_tool_list(template.get("available_tools", []))
        normalized_plan = _normalize_default_plan(template.get("default_plan"))
        _validate_known_tools(normalized_tools, normalized_plan)
        row = existing.get(template["name"])
        if row:
            row.display_name = template["display_name"]
            row.description = template.get("description")
            row.category = template["category"]
            row.available_tools = normalized_tools
            row.default_plan = normalized_plan
            row.is_system = True
            row.is_public = True
            row.updated_at = datetime.utcnow()
            changed = True
            continue
        db.add(
            WorkflowDefinition(
                name=template["name"],
                display_name=template["display_name"],
                description=template.get("description"),
                category=template["category"],
                available_tools=normalized_tools,
                default_plan=normalized_plan,
                is_system=True,
                is_public=True,
            )
        )
        changed = True
    # Delete obsolete system templates that are no longer in SYSTEM_WORKFLOW_TEMPLATES.
    for row in all_system_rows:
        if row.name not in desired_names:
            db.delete(row)
            changed = True
    if changed:
        db.commit()


# ==================== PYDANTIC MODELS ====================

class WorkflowDefinitionCreate(BaseModel):
    """Request to create a workflow definition"""
    name: str = Field(..., description="Unique name")
    display_name: str = Field(..., description="Display name")
    description: Optional[str] = None
    category: str = Field(..., description="Workflow category")
    available_tools: List[str] = Field(default_factory=list, description="Available tools")
    default_plan: Optional[dict] = None
    output_schema: Optional[dict] = None
    planning_prompt: Optional[str] = None
    summary_prompt: Optional[str] = None
    max_steps: int = 50
    timeout_minutes: int = 60
    requires_approval: bool = False
    is_public: bool = False


class WorkflowDefinitionUpdate(BaseModel):
    """Request to update a workflow definition"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    available_tools: Optional[List[str]] = None
    default_plan: Optional[dict] = None
    output_schema: Optional[dict] = None
    planning_prompt: Optional[str] = None
    summary_prompt: Optional[str] = None
    max_steps: Optional[int] = None
    timeout_minutes: Optional[int] = None
    requires_approval: Optional[bool] = None
    is_public: Optional[bool] = None


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow"""
    definition_id: Optional[str] = Field(None, description="Workflow definition ID")
    user_task: str = Field(..., description="Task in natural language")
    case_id: Optional[str] = None
    file_ids: Optional[List[str]] = None
    input_config: Optional[dict] = None


class PlanWorkflowRequest(BaseModel):
    """Request to create a workflow plan without executing"""
    definition_id: Optional[str] = None
    user_task: str = Field(..., description="Task in natural language")
    case_id: Optional[str] = None
    file_ids: Optional[List[str]] = None


class ResumeWorkflowRequest(BaseModel):
    """Request to resume HITL-paused workflow."""
    answer: str = Field(..., description="Lawyer answer/comment")
    approved: Optional[bool] = Field(None, description="Explicit approve/reject action")


# ==================== METADATA ENDPOINTS ====================

@router.get("/metadata/categories")
async def get_workflow_categories(
    current_user: User = Depends(get_current_user)
):
    """Get available workflow categories"""
    return WORKFLOW_CATEGORIES


@router.get("/metadata/tools")
async def get_workflow_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available workflow tools"""
    return WORKFLOW_TOOLS


@router.get("/metadata/system-templates")
async def get_system_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get system workflow templates"""
    _ensure_system_definitions(db)
    return SYSTEM_WORKFLOW_TEMPLATES


# ==================== DEFINITION CRUD ====================

@router.get("/definitions")
async def list_definitions(
    category: Optional[str] = Query(None),
    include_system: bool = Query(True),
    include_public: bool = Query(True),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List workflow definitions"""
    _ensure_system_definitions(db)
    query = db.query(WorkflowDefinition)
    
    # Visibility filter
    from sqlalchemy import or_
    visibility_filters = [WorkflowDefinition.user_id == current_user.id]
    if include_system:
        visibility_filters.append(WorkflowDefinition.is_system == True)
    if include_public:
        visibility_filters.append(WorkflowDefinition.is_public == True)
    
    query = query.filter(or_(*visibility_filters))
    
    if category:
        query = query.filter(WorkflowDefinition.category == category)
    
    query = query.order_by(
        WorkflowDefinition.is_system.desc(),
        WorkflowDefinition.usage_count.desc()
    )
    
    definitions = query.offset(offset).limit(limit).all()
    return [d.to_dict() for d in definitions]


@router.get("/definitions/{definition_id}")
async def get_definition(
    definition_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific workflow definition"""
    definition = db.query(WorkflowDefinition).filter(
        WorkflowDefinition.id == definition_id
    ).first()
    
    if not definition:
        raise HTTPException(status_code=404, detail="Definition not found")
    
    return definition.to_dict(include_details=True)


@router.post("/definitions")
async def create_definition(
    request: WorkflowDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new workflow definition"""
    # Check name uniqueness
    existing = db.query(WorkflowDefinition).filter(
        WorkflowDefinition.name == request.name
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Definition name already exists")
    
    normalized_tools = _normalize_tool_list(request.available_tools)
    normalized_plan = _normalize_default_plan(request.default_plan)
    _validate_known_tools(normalized_tools, normalized_plan)

    definition = WorkflowDefinition(
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        category=request.category,
        available_tools=normalized_tools,
        default_plan=normalized_plan,
        output_schema=request.output_schema,
        planning_prompt=request.planning_prompt,
        summary_prompt=request.summary_prompt,
        max_steps=request.max_steps,
        timeout_minutes=request.timeout_minutes,
        requires_approval=request.requires_approval,
        is_public=request.is_public,
        user_id=current_user.id,
        is_system=False
    )
    
    db.add(definition)
    db.commit()
    db.refresh(definition)
    
    return definition.to_dict(include_details=True)


@router.put("/definitions/{definition_id}")
async def update_definition(
    definition_id: str,
    request: WorkflowDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a workflow definition"""
    definition = db.query(WorkflowDefinition).filter(
        WorkflowDefinition.id == definition_id
    ).first()
    
    if not definition:
        raise HTTPException(status_code=404, detail="Definition not found")
    
    if definition.user_id != current_user.id or definition.is_system:
        raise HTTPException(status_code=403, detail="Cannot modify this definition")
    
    updates = request.model_dump(exclude_unset=True)
    if "available_tools" in updates:
        updates["available_tools"] = _normalize_tool_list(updates.get("available_tools"))
    if "default_plan" in updates:
        updates["default_plan"] = _normalize_default_plan(updates.get("default_plan"))
    _validate_known_tools(
        updates.get("available_tools", definition.available_tools),
        updates.get("default_plan", definition.default_plan),
    )
    for field, value in updates.items():
        setattr(definition, field, value)
    
    definition.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(definition)
    
    return definition.to_dict(include_details=True)


@router.delete("/definitions/{definition_id}")
async def delete_definition(
    definition_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a workflow definition"""
    definition = db.query(WorkflowDefinition).filter(
        WorkflowDefinition.id == definition_id
    ).first()
    
    if not definition:
        raise HTTPException(status_code=404, detail="Definition not found")
    
    if definition.user_id != current_user.id or definition.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete this definition")
    
    db.delete(definition)
    db.commit()
    
    return {"message": "Definition deleted"}


# ==================== PLANNING ====================

@router.post("/plan")
async def create_plan(
    request: PlanWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a workflow execution plan without executing"""
    try:
        # Get definition if specified
        definition = None
        if request.definition_id:
            definition = db.query(WorkflowDefinition).filter(
                WorkflowDefinition.id == request.definition_id
            ).first()
        
        # Get documents
        documents = []
        if request.file_ids:
            files = db.query(File).filter(File.id.in_(request.file_ids)).all()
            documents = [{"id": f.id, "filename": f.filename, "type": f.file_type} for f in files]
        elif request.case_id:
            files = db.query(File).filter(File.case_id == request.case_id).all()
            documents = [{"id": f.id, "filename": f.filename, "type": f.file_type} for f in files]
        
        # Available tools - use definition's tools or all tools if empty/not specified
        if definition and definition.available_tools:
            available_tools = definition.available_tools
        else:
            available_tools = [t["name"] for t in WORKFLOW_TOOLS]
        
        logger = logging.getLogger(__name__)
        logger.info(f"Planning with available_tools: {available_tools}")
        
        # Create plan
        planning_agent = PlanningAgent()
        deep_planner = DeepAgentsPlanningService()
        decision = await deep_planner.create_plan(
            user_task=request.user_task,
            available_documents=documents,
            available_tools=available_tools,
            workflow_definition=definition
        )
        if decision.clarification_required or not decision.plan:
            return {
                "plan": None,
                "validation_errors": [],
                "is_valid": False,
                "estimated_duration_seconds": 0,
                "clarification_required": True,
                "clarification_question": decision.clarification_question,
                "clarification_options": decision.clarification_options or [],
                "reason": decision.reason,
            }
        plan = decision.plan
        
        # Validate
        errors = planning_agent.validate_plan(plan)
        
        return {
            "plan": planning_agent.plan_to_dict(plan),
            "validation_errors": errors,
            "is_valid": len(errors) == 0,
            "estimated_duration_seconds": plan.estimated_total_duration_seconds,
            "used_fallback": decision.used_fallback,
        }
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error creating workflow plan: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка создания плана workflow: {str(e)}"
        )


# ==================== EXECUTION ====================

@router.post("/execute")
async def execute_workflow(
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start workflow execution (returns immediately with execution ID)"""
    # Get definition if specified
    definition = None
    if request.definition_id:
        definition = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == request.definition_id
        ).first()
        
        if not definition:
            raise HTTPException(status_code=404, detail="Definition not found")
    else:
        # Create a temporary custom definition
        definition = WorkflowDefinition(
            name=f"custom_{datetime.utcnow().timestamp()}",
            display_name="Custom Workflow",
            category="custom",
            available_tools=[t["name"] for t in WORKFLOW_TOOLS],
            user_id=current_user.id
        )
        db.add(definition)
        db.flush()
    
    # Create execution
    execution_engine = ExecutionEngine(db)
    execution = await execution_engine.start_workflow(
        definition=definition,
        user_task=request.user_task,
        user_id=current_user.id,
        case_id=request.case_id,
        file_ids=request.file_ids,
        input_config=request.input_config
    )
    
    # Update definition usage
    if request.definition_id:
        definition.usage_count = (definition.usage_count or 0) + 1
    
    db.commit()
    
    return {
        "execution_id": execution.id,
        "status": execution.status,
        "message": "Workflow execution started"
    }


@router.get("/executions/{execution_id}/stream")
async def stream_execution(
    execution_id: str,
    token: Optional[str] = Query(None, description="JWT token for SSE authentication (EventSource doesn't support headers)"),
    db: Session = Depends(get_db)
):
    """Stream execution events via SSE
    
    ВАЖНО: EventSource API не поддерживает кастомные headers,
    поэтому токен передаётся через query параметр ?token=...
    
    Args:
        execution_id: ID выполнения workflow
        token: JWT токен для аутентификации (обязателен для SSE)
        db: Database session
    """
    from sqlalchemy.orm import joinedload
    from app.utils.auth import get_user_from_token
    
    # Аутентификация через query параметр (для SSE)
    if not token:
        raise HTTPException(
            status_code=401, 
            detail="Token required. Pass it via ?token= query parameter for SSE"
        )
    
    current_user = await get_user_from_token(token, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Use joinedload to eagerly load the definition relationship
    execution = db.query(WorkflowExecution).options(
        joinedload(WorkflowExecution.definition)
    ).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Extract data from execution BEFORE the async generator
    # to avoid DetachedInstanceError
    execution_status = execution.status
    execution_progress = execution.progress_percent
    definition = execution.definition
    selected_file_ids = execution.selected_file_ids
    
    # Get documents while still in session
    documents = []
    if selected_file_ids:
        files = db.query(File).filter(File.id.in_(selected_file_ids)).all()
        documents = [{"id": f.id, "filename": f.filename, "type": f.file_type} for f in files]

    async def poll_execution_until_terminal(
        *,
        idle_seconds: float = 1.0,
    ) -> AsyncIterator[str]:
        """
        Пока основной runner в другом SSE держит plan_and_execute, гранулярные события
        туда не попадают — но прогресс и status_message пишутся в БД. Этот цикл
        отдаёт их второму/переподключившемуся клиенту до terminal-состояния.

        Корни проблем UX: (1) один процесс стримит live-события; поздний join = только poll;
        (2) раньше второй клиент получал одно сообщение и обрыв — исправлено ниже.

        Каждый poll — отдельная короткая сессия (не держим соединение пула на весь SSE-цикл).
        При OperationalError/TimeoutError — событие status + backoff, поток не рвём.
        """
        def _fetch_execution_poll_row():
            sess = SessionLocal()
            try:
                row = (
                    sess.query(WorkflowExecution)
                    .filter(
                        WorkflowExecution.id == execution_id,
                        WorkflowExecution.user_id == current_user.id,
                    )
                    .first()
                )
                if not row:
                    return None
                return {
                    "status": row.status,
                    "progress_percent": row.progress_percent,
                    "status_message": row.status_message or "",
                    "summary": row.summary,
                    "artifacts": row.artifacts,
                    "error_message": row.error_message,
                    "results": row.results,
                    "total_llm_calls": row.total_llm_calls,
                    "total_tokens_used": row.total_tokens_used,
                }
            finally:
                sess.close()

        terminal_statuses = {"completed", "failed", "cancelled", "completed_with_errors"}
        last_snapshot = None
        last_comment = 0.0
        consecutive_db_errors = 0
        while True:
            try:
                current = _fetch_execution_poll_row()
                consecutive_db_errors = 0
            except (SAOperationalError, SATimeoutError) as poll_err:
                consecutive_db_errors += 1
                logger.warning(
                    "workflow SSE poll DB error for %s: %s (consecutive=%s)",
                    execution_id,
                    poll_err,
                    consecutive_db_errors,
                )
                backoff = min(30.0, idle_seconds * (2 ** min(consecutive_db_errors, 5)))
                if last_snapshot is not None:
                    st_retry, pr_retry, _ = last_snapshot
                else:
                    st_retry, pr_retry = execution_status, execution_progress
                retry_payload = {
                    "type": "status",
                    "event_type": "status",
                    "execution_id": execution_id,
                    "status": st_retry,
                    "progress": pr_retry,
                    "progress_percent": pr_retry,
                    "message": "Временная ошибка подключения к базе, повторяю опрос…",
                }
                yield f"data: {json.dumps(retry_payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(backoff)
                continue

            if not current:
                break

            snapshot = (
                current["status"],
                current["progress_percent"],
                current["status_message"] or "",
            )
            if snapshot != last_snapshot:
                status_payload = {
                    "type": "status",
                    "event_type": "status",
                    "execution_id": execution_id,
                    "status": current["status"],
                    "progress": current["progress_percent"],
                    "progress_percent": current["progress_percent"],
                    "message": current["status_message"] or "Текущее состояние workflow обновлено.",
                }
                if current["status"] == "waiting_for_lawyer":
                    status_payload["required_action"] = "upload_documents"
                yield f"data: {json.dumps(status_payload, ensure_ascii=False)}\n\n"
                last_snapshot = snapshot

            if current["status"] in terminal_statuses:
                final_type = (
                    "completed"
                    if current["status"] in {"completed", "completed_with_errors"}
                    else current["status"]
                )
                final_payload = {
                    "type": final_type,
                    "event_type": final_type,
                    "execution_id": execution_id,
                    "status": current["status"],
                    "progress": current["progress_percent"],
                    "progress_percent": current["progress_percent"],
                    "message": current["status_message"]
                    or (
                        "Workflow завершён."
                        if final_type == "completed"
                        else "Workflow завершён с ошибкой."
                    ),
                    "data": {
                        "summary": current["summary"],
                        "artifacts": current["artifacts"],
                        "error": current["error_message"],
                        "results": current["results"],
                        "run_stats": {
                            "total_llm_calls": int(current["total_llm_calls"] or 0),
                            "total_tokens_used": int(current["total_tokens_used"] or 0),
                        },
                    },
                }
                yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
                break

            now = time.monotonic()
            if now - last_comment >= 20.0:
                yield ": keepalive\n\n"
                last_comment = now

            await asyncio.sleep(idle_seconds)
    
    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events"""
        # Комментарии (: ...) не вызывают EventSource.onmessage — без data: клиент минутами
        # «висит» на «Подключение к потоку», хотя соединение уже открыто.
        yield ": stream-open\n\n"
        connected_payload = {
            "type": "status",
            "event_type": "status",
            "execution_id": execution_id,
            "status": execution_status,
            "progress": execution_progress,
            "progress_percent": execution_progress,
            "message": (
                "Поток событий подключён, идёт подготовка плана и запуск workflow…"
                if execution_status == "planning"
                else "Поток событий подключён, передаю прогресс из выполнения…"
            ),
        }
        yield f"data: {json.dumps(connected_payload, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)
        # If execution is already planning, start execution
        if execution_status == "planning":
            # Idempotency guard: only one stream runner can own planning start.
            lock_marker = "__stream_lock__"
            owner_marker = f"{lock_marker}:{execution_id}"
            fresh = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution_id
            ).first()
            if fresh and fresh.status == "planning" and (fresh.status_message or "").startswith(lock_marker):
                # Another runner already started execution; live events go to the first SSE only.
                payload = {
                    "type": "status",
                    "event_type": "status",
                    "execution_id": execution_id,
                    "status": fresh.status,
                    "progress": fresh.progress_percent,
                    "progress_percent": fresh.progress_percent,
                    "message": "Workflow уже запущен в другом потоке стриминга.",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                async for chunk in poll_execution_until_terminal(idle_seconds=0.5):
                    yield chunk
                return
            if fresh and fresh.status == "planning":
                fresh.status_message = owner_marker
                db.commit()

            engine = ExecutionEngine(db)

            # DeepAgents: create_deep_agent via WorkflowDeepAgentsHarness + ToolRegistry (plan_and_execute)
            try:
                saw_terminal_event = False
                async for event in engine.plan_and_execute(execution, definition, documents):
                    # Defensive sync: if execution paused for lawyer input, persist explicit state
                    # in this route too so lock marker never stays as final status_message.
                    if event.event_type == "waiting_for_lawyer":
                        paused = db.query(WorkflowExecution).filter(
                            WorkflowExecution.id == execution_id
                        ).first()
                        if paused:
                            paused.status = "waiting_for_lawyer"
                            paused.status_message = event.message or "Ожидание действий юриста"
                            db.commit()
                    if event.event_type in {"completed", "failed", "cancelled", "completed_with_errors"}:
                        saw_terminal_event = True
                    yield f"data: {json.dumps(event_to_dict(event), ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)

                # Safety net: if generator stopped without explicit terminal event,
                # always emit a synthetic terminal event from DB state.
                current_after_run = db.query(WorkflowExecution).filter(
                    WorkflowExecution.id == execution_id
                ).first()
                if not saw_terminal_event and current_after_run:
                    terminal_statuses = {"completed", "failed", "cancelled", "completed_with_errors"}
                    if current_after_run.status not in terminal_statuses:
                        current_after_run.status = "failed"
                        current_after_run.error_message = (
                            "Workflow stream завершился без terminal-события. Выполнение остановлено safeguard-логикой."
                        )
                        current_after_run.status_message = current_after_run.error_message
                        current_after_run.completed_at = datetime.utcnow()
                        db.commit()
                    final_type = (
                        "completed"
                        if current_after_run.status in {"completed", "completed_with_errors"}
                        else "failed"
                    )
                    safeguard_terminal = ExecutionEvent(
                        event_type=final_type,
                        execution_id=execution_id,
                        data={
                            "summary": current_after_run.summary,
                            "artifacts": current_after_run.artifacts,
                            "error": current_after_run.error_message,
                            "results": current_after_run.results,
                            "run_stats": {
                                "total_llm_calls": int(current_after_run.total_llm_calls or 0),
                                "total_tokens_used": int(current_after_run.total_tokens_used or 0),
                                "forced_finalize": True,
                            },
                        },
                        message=current_after_run.status_message
                        or (
                            "Workflow завершён safeguard-терминатором."
                            if final_type == "completed"
                            else "Workflow остановлен safeguard-терминатором."
                        ),
                        progress_percent=(
                            100 if final_type == "completed" else (current_after_run.progress_percent or 0)
                        ),
                    )
                    yield f"data: {json.dumps(event_to_dict(safeguard_terminal), ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error(
                    "Workflow stream crashed for execution %s: %s",
                    execution_id,
                    exc,
                    exc_info=True,
                )
                crashed = db.query(WorkflowExecution).filter(
                    WorkflowExecution.id == execution_id
                ).first()
                if crashed:
                    crashed.status = "failed"
                    crashed.error_message = (
                        crashed.error_message
                        or f"Ошибка stream runtime: {str(exc)}"
                    )
                    crashed.status_message = crashed.error_message
                    crashed.completed_at = datetime.utcnow()
                    db.commit()
                crash_event = ExecutionEvent(
                    event_type="failed",
                    execution_id=execution_id,
                    data={
                        "error": str(exc),
                        "summary": crashed.summary if crashed else None,
                        "artifacts": crashed.artifacts if crashed else {},
                        "results": crashed.results if crashed else {},
                        "run_stats": {
                            "total_llm_calls": int((crashed.total_llm_calls if crashed else 0) or 0),
                            "total_tokens_used": int((crashed.total_tokens_used if crashed else 0) or 0),
                            "forced_finalize": True,
                        },
                    },
                    message=f"Workflow аварийно остановлен: {str(exc)}",
                    progress_percent=(crashed.progress_percent if crashed else 0) or 0,
                )
                yield f"data: {json.dumps(event_to_dict(crash_event), ensure_ascii=False)}\n\n"
            finally:
                # Always release stream lock marker if execution never left planning.
                current = db.query(WorkflowExecution).filter(
                    WorkflowExecution.id == execution_id
                ).first()
                if (
                    current
                    and current.status == "planning"
                    and (current.status_message or "").startswith(lock_marker)
                ):
                    current.status_message = "Ожидание продолжения выполнения workflow."
                    db.commit()
        else:
            # Уже executing / позднее подключение: только снимки из БД (гранулярные события — у первого SSE).
            async for chunk in poll_execution_until_terminal(idle_seconds=0.5):
                yield chunk
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def event_to_dict(event: ExecutionEvent) -> dict:
    """Convert ExecutionEvent to dict"""
    return {
        "type": event.event_type,  # For frontend compatibility
        "event_type": event.event_type,
        "execution_id": event.execution_id,
        "step_id": event.step_id,
        "data": event.data,
        "timestamp": event.timestamp.isoformat(),
        "progress": event.progress_percent,
        "progress_percent": event.progress_percent,
        "message": event.message
    }


# ==================== EXECUTION MANAGEMENT ====================

@router.get("/executions")
async def list_executions(
    status: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List workflow executions"""
    query = db.query(WorkflowExecution).filter(
        WorkflowExecution.user_id == current_user.id
    )
    
    if status:
        query = query.filter(WorkflowExecution.status == status)
    
    if case_id:
        query = query.filter(WorkflowExecution.case_id == case_id)
    
    query = query.order_by(WorkflowExecution.created_at.desc())
    
    executions = query.offset(offset).limit(limit).all()
    return [e.to_dict() for e in executions]


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution details"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return execution.to_dict(include_details=True)


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel a running execution"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    engine = ExecutionEngine(db)
    success = await engine.cancel_execution(execution_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel this execution")
    
    return {"message": "Execution cancelled"}


@router.post("/executions/{execution_id}/resume")
async def resume_execution(
    execution_id: str,
    request: ResumeWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resume execution paused for HITL."""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    engine = ExecutionEngine(db)
    try:
        event = await engine.resume_execution_with_human_input(
            execution,
            answer=request.answer,
            approved=request.approved,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "message": "Execution resumed",
        "event": event_to_dict(event),
        "status": execution.status,
    }


@router.get("/executions/{execution_id}/results")
async def get_execution_results(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution results"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return {
        "status": execution.status,
        "results": execution.results,
        "artifacts": execution.artifacts,
        "summary": execution.summary,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None
    }


@router.get("/executions/{execution_id}/steps")
async def get_execution_steps(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution steps"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    steps = db.query(WorkflowStep).filter(
        WorkflowStep.execution_id == execution_id
    ).order_by(WorkflowStep.sequence_number).all()
    
    return [s.to_dict() for s in steps]


# ==================== VALIDATION ====================

@router.post("/executions/{execution_id}/validate")
async def validate_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Validate execution results"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status != "completed":
        raise HTTPException(status_code=400, detail="Execution not completed")
    
    validator = ResultValidator()
    result = await validator.validate(
        user_task=execution.user_task,
        results=execution.results or {},
        expected_schema=execution.definition.output_schema if execution.definition else None
    )
    
    return {
        "is_valid": result.is_valid,
        "confidence_score": result.confidence_score,
        "issues": [
            {
                "severity": i.severity,
                "message": i.message,
                "step_id": i.step_id,
                "suggestion": i.suggestion
            }
            for i in result.issues
        ],
        "summary": result.summary
    }

