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
        last_table_ids = set()  # Track sent table IDs to avoid duplicates
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
            
            # Check for new tables during execution (not just at completion)
            plan_data = plan.plan_data or {}
            table_results = plan_data.get("table_results") or plan_data.get("delivery_result", {}).get("tables", {})
            # #region agent log
            if poll_count % 5 == 0:  # Log every 5 polls to avoid spam
                logger.info(f"[DEBUG-HYP-B] plan_execution.py: checking table_results, "
                           f"plan_status={plan.status}, "
                           f"plan_data_keys={list(plan_data.keys())}, "
                           f"has_table_results={bool(plan_data.get('table_results'))}, "
                           f"table_results_keys={list(plan_data.get('table_results', {}).keys()) if plan_data.get('table_results') else None}, "
                           f"has_delivery_result={bool(plan_data.get('delivery_result'))}, "
                           f"delivery_result_tables_keys={list(plan_data.get('delivery_result', {}).get('tables', {}).keys()) if plan_data.get('delivery_result') and plan_data.get('delivery_result', {}).get('tables') else None}, "
                           f"final_table_results_keys={list(table_results.keys()) if table_results else None}, "
                           f"poll_count={poll_count}")
            # #endregion
            if table_results:
                try:
                    from app.models.tabular_review import TabularReview, TabularColumn
                    from app.models.case import Case
                    
                    case = db.query(Case).filter(Case.id == plan.case_id).first()
                    if case:
                        for table_key, table_info in table_results.items():
                            # #region agent log
                            logger.info(f"[DEBUG-HYP-C] plan_execution.py: processing table_info, "
                                       f"table_key={table_key}, "
                                       f"table_info_type={type(table_info).__name__}, "
                                       f"is_dict={isinstance(table_info, dict)}, "
                                       f"table_info={table_info if isinstance(table_info, dict) else str(table_info)}, "
                                       f"status={table_info.get('status') if isinstance(table_info, dict) else None}, "
                                       f"table_id={table_info.get('table_id') if isinstance(table_info, dict) else None}, "
                                       f"in_last_table_ids={table_info.get('table_id') in last_table_ids if isinstance(table_info, dict) and table_info.get('table_id') else False}")
                            # #endregion
                            if isinstance(table_info, dict) and table_info.get("status") == "created":
                                table_id = table_info.get("table_id")
                                if table_id and table_id not in last_table_ids:
                                    # Get table preview data
                                    review = db.query(TabularReview).filter(TabularReview.id == table_id).first()
                                    if review:
                                        columns = db.query(TabularColumn).filter(
                                            TabularColumn.tabular_review_id == table_id
                                        ).order_by(TabularColumn.order_index).all()
                                        
                                        preview_data = {
                                            "id": table_id,
                                            "name": review.name,
                                            "description": review.description,
                                            "columns_count": len(columns),
                                            "rows_count": len(review.selected_file_ids) if review.selected_file_ids and isinstance(review.selected_file_ids, list) else 0,
                                            "preview": {
                                                "columns": [col.column_label for col in columns[:4]],
                                                "rows": []
                                            }
                                        }
                                        
                                        # Send table_created event
                                        yield f"data: {json.dumps({
                                            'type': 'table_created',
                                            'table_id': table_id,
                                            'case_id': plan.case_id,
                                            'analysis_type': table_key,
                                            'table_data': preview_data
                                        }, ensure_ascii=False)}\n\n"
                                        last_table_ids.add(table_id)
                                        logger.info(f"[PlanExecutionStream] Sent table_created event for {table_key}: {table_id}")
                except Exception as table_error:
                    logger.warning(f"Error sending table_created events during execution: {table_error}", exc_info=True)
            
            # Check plan status
            if plan.status == "completed":
                # Send all remaining steps and completion
                plan_data = plan.plan_data or {}
                execution_steps = plan_data.get("execution_steps", [])
                
                # Send any new steps
                for step in execution_steps[last_step_count:]:
                    yield f"data: {json.dumps({'type': 'step_completed', 'step': step}, ensure_ascii=False)}\n\n"
                
                # Send any remaining table_created events that weren't sent during execution
                # (This is a fallback in case tables were created but events weren't sent)
                table_results = plan_data.get("table_results") or plan_data.get("delivery_result", {}).get("tables", {})
                logger.info(f"[PlanExecutionStream] Final check for table_results: found {len(table_results) if table_results else 0} tables")
                if table_results:
                    logger.info(f"[PlanExecutionStream] Table results keys: {list(table_results.keys())}")
                    try:
                        from app.models.tabular_review import TabularReview, TabularColumn
                        from app.models.case import Case
                        
                        case = db.query(Case).filter(Case.id == plan.case_id).first()
                        if case:
                            for table_key, table_info in table_results.items():
                                if isinstance(table_info, dict) and table_info.get("status") == "created":
                                    table_id = table_info.get("table_id")
                                    if table_id and table_id not in last_table_ids:
                                        # Get table preview data
                                        review = db.query(TabularReview).filter(TabularReview.id == table_id).first()
                                        if review:
                                            columns = db.query(TabularColumn).filter(
                                                TabularColumn.tabular_review_id == table_id
                                            ).order_by(TabularColumn.order_index).all()
                                            
                                            preview_data = {
                                                "id": table_id,
                                                "name": review.name,
                                                "description": review.description,
                                                "columns_count": len(columns),
                                                "rows_count": len(review.selected_file_ids) if review.selected_file_ids and isinstance(review.selected_file_ids, list) else 0,
                                                "preview": {
                                                    "columns": [col.column_label for col in columns[:4]],
                                                    "rows": []
                                                }
                                            }
                                            
                                            # Send table_created event
                                            yield f"data: {json.dumps({
                                                'type': 'table_created',
                                                'table_id': table_id,
                                                'case_id': plan.case_id,
                                                'analysis_type': table_key,
                                                'table_data': preview_data
                                            }, ensure_ascii=False)}\n\n"
                                            last_table_ids.add(table_id)
                                            logger.info(f"[PlanExecutionStream] Sent final table_created event for {table_key}: {table_id}")
                    except Exception as table_error:
                        logger.warning(f"Error sending final table_created events: {table_error}", exc_info=True)
                
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

