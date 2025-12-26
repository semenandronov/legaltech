"""API routes for workflow templates"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.services.workflow_service import WorkflowService
from app.routes.auth import get_current_user, get_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


# Pydantic models
class WorkflowStepSchema(BaseModel):
    step_id: str
    name: str
    description: Optional[str] = None
    agent: str
    required: bool = True


class ReviewColumnSchema(BaseModel):
    name: str
    prompt: str
    type: str = "text"


class CreateWorkflowRequest(BaseModel):
    name: str
    display_name: str
    category: str
    steps: List[WorkflowStepSchema]
    description: Optional[str] = None
    review_columns: Optional[List[ReviewColumnSchema]] = None
    is_public: bool = False


class UpdateWorkflowRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    steps: Optional[List[WorkflowStepSchema]] = None
    review_columns: Optional[List[ReviewColumnSchema]] = None
    is_public: Optional[bool] = None


@router.get("/categories")
async def get_categories(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get workflow categories"""
    service = WorkflowService(db)
    return service.get_categories()


@router.get("/")
async def list_workflows(
    category: Optional[str] = Query(None, description="Filter by category"),
    include_system: bool = Query(True, description="Include system workflows"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List available workflows"""
    service = WorkflowService(db)
    return service.get_workflows(
        user_id=current_user.id,
        category=category,
        include_system=include_system,
        limit=limit
    )


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a specific workflow"""
    service = WorkflowService(db)
    workflow = service.get_workflow(workflow_id, current_user.id)
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    return workflow


@router.get("/by-name/{name}")
async def get_workflow_by_name(
    name: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a system workflow by name"""
    service = WorkflowService(db)
    workflow = service.get_workflow_by_name(name)
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    return workflow


@router.post("/")
async def create_workflow(
    request: CreateWorkflowRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a custom workflow"""
    service = WorkflowService(db)
    
    steps = [s.model_dump() for s in request.steps]
    review_columns = [c.model_dump() for c in request.review_columns] if request.review_columns else None
    
    return service.create_workflow(
        user_id=current_user.id,
        name=request.name,
        display_name=request.display_name,
        category=request.category,
        steps=steps,
        description=request.description,
        review_columns=review_columns,
        is_public=request.is_public
    )


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update a workflow"""
    service = WorkflowService(db)
    
    updates = request.model_dump(exclude_unset=True)
    if "steps" in updates and updates["steps"]:
        updates["steps"] = [s.model_dump() if hasattr(s, 'model_dump') else s for s in updates["steps"]]
    if "review_columns" in updates and updates["review_columns"]:
        updates["review_columns"] = [c.model_dump() if hasattr(c, 'model_dump') else c for c in updates["review_columns"]]
    
    result = service.update_workflow(workflow_id, current_user.id, updates)
    
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found or access denied")
    
    return result


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a workflow"""
    service = WorkflowService(db)
    
    if not service.delete_workflow(workflow_id, current_user.id):
        raise HTTPException(status_code=404, detail="Workflow not found or access denied")
    
    return {"message": "Workflow deleted successfully"}


@router.post("/{workflow_id}/use")
async def use_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Use a workflow - returns workflow and increments usage counter"""
    service = WorkflowService(db)
    
    result = service.use_workflow(workflow_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found or access denied")
    
    return result


@router.post("/{workflow_id}/duplicate")
async def duplicate_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Duplicate a workflow to your library"""
    service = WorkflowService(db)
    
    result = service.duplicate_workflow(workflow_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found or access denied")
    
    return result


@router.post("/init-system")
async def init_system_workflows(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Initialize system workflows (admin only)"""
    # TODO: Add admin check
    service = WorkflowService(db)
    service.init_system_workflows()
    return {"message": "System workflows initialized"}

