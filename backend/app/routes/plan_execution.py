"""SSE endpoint for streaming plan execution steps"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.analysis import AnalysisPlan
from app.services.analysis_service import AnalysisService
from app.services.langchain_agents import AgentCoordinator
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from typing import AsyncGenerator
import json
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()


async def stream_plan_execution(
    plan_id: str,
    db: Session
) -> AsyncGenerator[str, None]:
    """Stream execution steps for approved plan by polling plan status"""
    try:
        # Send start event
        yield f"data: {json.dumps({'type': 'execution_started', 'plan_id': plan_id}, ensure_ascii=False)}\n\n"
        
        # Poll plan status and stream steps
        last_step_count = 0
        max_polls = 300  # 5 minutes max (1 second per poll)
        poll_count = 0
        
        while poll_count < max_polls:
            await asyncio.sleep(1)  # Poll every second
            poll_count += 1
            
            # Get plan from database
            plan = db.query(AnalysisPlan).filter(AnalysisPlan.id == plan_id).first()
            if not plan:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Plan not found'}, ensure_ascii=False)}\n\n"
                return
            
            # Check plan status
            if plan.status == "completed":
                # Send all remaining steps and completion
                plan_data = plan.plan_data or {}
                execution_steps = plan_data.get("execution_steps", [])
                
                # Send any new steps
                for step in execution_steps[last_step_count:]:
                    yield f"data: {json.dumps({'type': 'step_completed', 'step': step}, ensure_ascii=False)}\n\n"
                
                yield f"data: {json.dumps({'type': 'execution_completed', 'steps': execution_steps}, ensure_ascii=False)}\n\n"
                return
            elif plan.status == "failed":
                yield f"data: {json.dumps({'type': 'execution_failed', 'message': 'Plan execution failed'}, ensure_ascii=False)}\n\n"
                return
            
            # Stream new steps if available
            plan_data = plan.plan_data or {}
            execution_steps = plan_data.get("execution_steps", [])
            
            if len(execution_steps) > last_step_count:
                # Send new steps
                for step in execution_steps[last_step_count:]:
                    # Mark as running if plan is still executing
                    if plan.status == "executing":
                        step["status"] = "running"
                    yield f"data: {json.dumps({'type': 'step_completed', 'step': step}, ensure_ascii=False)}\n\n"
                last_step_count = len(execution_steps)
        
        # Timeout
        yield f"data: {json.dumps({'type': 'timeout', 'message': 'Execution timeout'}, ensure_ascii=False)}\n\n"
        
    except Exception as e:
        logger.error(f"Error streaming plan execution: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"


@router.get("/{plan_id}/stream")
async def stream_plan_execution_endpoint(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """SSE endpoint for streaming plan execution steps"""
    try:
        # Get plan from database
        plan = db.query(AnalysisPlan).filter(
            AnalysisPlan.id == plan_id,
            AnalysisPlan.user_id == current_user.id
        ).first()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        if plan.status not in ["approved", "executing", "completed"]:
            raise HTTPException(status_code=400, detail=f"Plan is not approved, executing or completed (status: {plan.status})")
        
        return StreamingResponse(
            stream_plan_execution(plan_id, db),
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
        logger.error(f"Error in stream_plan_execution_endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

