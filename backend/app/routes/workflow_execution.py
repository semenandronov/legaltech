"""Workflow Execution API Routes"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel
import json
import logging

from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.workflow_service import WorkflowService
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow-execution", tags=["workflow-execution"])


class CreateWorkflowFromNLRequest(BaseModel):
    description: str
    display_name: Optional[str] = None
    category: str = "custom"


class ExecuteWorkflowRequest(BaseModel):
    case_id: str
    user_input: str


@router.post("/from-natural-language")
async def create_workflow_from_nl(
    request: CreateWorkflowFromNLRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Создать workflow из natural language описания
    
    Пример запроса:
    {
        "description": "Проведи due diligence: сначала классифицируй документы,
                       затем извлеки ключевые факты и риски, в конце создай отчет",
        "display_name": "Due Diligence Workflow",
        "category": "due_diligence"
    }
    """
    try:
        workflow_service = WorkflowService(db=db)
        
        workflow = workflow_service.create_workflow_from_nl(
            user_id=current_user.id,
            description=request.description,
            display_name=request.display_name,
            category=request.category
        )
        
        return {
            "success": True,
            "workflow": workflow,
            "message": "Workflow created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating workflow from NL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> StreamingResponse:
    """
    Выполняет workflow и возвращает streaming events
    
    Streaming format:
    data: {"event_type": "step_completed", "data": {...}, "step_id": "..."}\n\n
    data: {"event_type": "completed", "data": {...}}\n\n
    """
    try:
        # Initialize services
        workflow_service = WorkflowService(
            db=db,
            rag_service=RAGService(db),
            document_processor=DocumentProcessor()
        )
        
        # Check if workflow exists and user has access
        workflow = workflow_service.get_workflow(workflow_id, current_user.id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        async def generate_events():
            """Generator for streaming events"""
            try:
                async for event in workflow_service.execute_workflow(
                    workflow_id=workflow_id,
                    case_id=request.case_id,
                    user_input=request.user_input,
                    user_id=current_user.id
                ):
                    # Format as SSE (Server-Sent Events)
                    event_data = json.dumps(event.to_dict(), ensure_ascii=False)
                    yield f"data: {event_data}\n\n"
            except Exception as e:
                logger.error(f"Error in workflow execution stream: {e}", exc_info=True)
                error_event = {
                    "event_type": "error",
                    "data": {"error": str(e)},
                    "step_id": None
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            generate_events(),
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
        logger.error(f"Error executing workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/preview")
async def preview_workflow_graph(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Предпросмотр графа workflow
    
    Returns:
        Graph structure with nodes and edges
    """
    try:
        workflow_service = WorkflowService(db=db)
        
        workflow = workflow_service.get_workflow(workflow_id, current_user.id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Build graph preview from steps
        nodes = []
        edges = []
        
        for step in workflow.get("steps", []):
            nodes.append({
                "id": step.get("step_id"),
                "label": step.get("name"),
                "agent": step.get("agent"),
                "required": step.get("required", True)
            })
            
            # Add edge to next step
            step_index = workflow["steps"].index(step)
            if step_index < len(workflow["steps"]) - 1:
                edges.append({
                    "from": step.get("step_id"),
                    "to": workflow["steps"][step_index + 1].get("step_id")
                })
        
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.get("display_name"),
            "nodes": nodes,
            "edges": edges,
            "graph_config": workflow.get("graph_config", {}),
            "node_mapping": workflow.get("node_mapping", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing workflow graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

