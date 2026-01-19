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
    SYSTEM_WORKFLOW_TEMPLATES
)
from app.models.case import File
from app.services.workflows.execution_engine import ExecutionEngine, ExecutionEvent
from app.services.workflows.planning_agent import PlanningAgent
from app.services.workflows.tool_registry import ToolRegistry
from app.services.workflows.result_validator import ResultValidator
from app.routes.auth import get_current_user, get_db
from app.models.user import User
from datetime import datetime
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow-agentic", tags=["workflow-agentic"])


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
    current_user: User = Depends(get_current_user)
):
    """Get system workflow templates"""
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
    
    definition = WorkflowDefinition(
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        category=request.category,
        available_tools=request.available_tools,
        default_plan=request.default_plan,
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
        
        # Available tools
        available_tools = definition.available_tools if definition else [t["name"] for t in WORKFLOW_TOOLS]
        
        # Create plan
        planning_agent = PlanningAgent()
        plan = await planning_agent.create_plan(
            user_task=request.user_task,
            available_documents=documents,
            available_tools=available_tools,
            workflow_definition=definition
        )
        
        # Validate
        errors = planning_agent.validate_plan(plan)
        
        return {
            "plan": planning_agent.plan_to_dict(plan),
            "validation_errors": errors,
            "is_valid": len(errors) == 0,
            "estimated_duration_seconds": plan.estimated_total_duration_seconds
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
    
    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events"""
        # If execution is already planning, start execution
        if execution_status == "planning":
            engine = ExecutionEngine(db)
            
            async for event in engine.plan_and_execute(execution, definition, documents):
                yield f"data: {json.dumps(event_to_dict(event), ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.1)
        else:
            # Already running or completed - just return current status
            yield f"data: {json.dumps({'event_type': 'status', 'status': execution_status, 'progress': execution_progress}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


def event_to_dict(event: ExecutionEvent) -> dict:
    """Convert ExecutionEvent to dict"""
    return {
        "event_type": event.event_type,
        "execution_id": event.execution_id,
        "step_id": event.step_id,
        "data": event.data,
        "timestamp": event.timestamp.isoformat(),
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

