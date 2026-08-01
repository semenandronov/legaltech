"""WebSocket routes for streaming analysis"""
from fastapi import WebSocket, WebSocketDisconnect, APIRouter, Depends, HTTPException, Query
from app.services.langchain_agents.legacy_stubs import AgentCoordinator
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.tabular_review_service import TabularReviewService
from app.services.presence_service import get_presence_service
from app.services.websocket_manager import websocket_manager
from app.utils.database import get_db
from app.utils.auth import decode_websocket_ticket
from app.utils.authorization import require_owned_case, require_owned_review
from app.models.user import User
from app.config import config as app_config
from sqlalchemy.orm import Session
from typing import Optional
import json
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()
tabular_router = APIRouter()


async def _reject_websocket(websocket: WebSocket, code: int = 4401) -> None:
    """Reject before application data is sent."""
    try:
        await websocket.close(code=code)
    except Exception:
        pass


def _ticket_user_id(ticket: str, *, resource_type: str, resource_id: str) -> Optional[str]:
    payload = decode_websocket_ticket(
        ticket,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if not payload:
        return None
    return str(payload["sub"])


def _active_user(db: Session, user_id: str) -> Optional[User]:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    if hasattr(user, "is_active") and not user.is_active:
        return None
    return user


@router.websocket("/ws/analysis/{case_id}")
async def stream_analysis(
    websocket: WebSocket,
    case_id: str,
    ticket: str = Query(...),
):
    """
    WebSocket endpoint for streaming LangGraph analysis progress
    
    Streams progress updates as analysis agents complete their tasks.
    """
    # Get database session
    from app.utils.database import SessionLocal
    db = SessionLocal()
    
    try:
        if app_config.TABULAR_ONLY_MODE:
            await _reject_websocket(websocket, code=4404)
            return
        user_id = _ticket_user_id(ticket, resource_type="case", resource_id=case_id)
        if not user_id or not _active_user(db, user_id):
            await _reject_websocket(websocket)
            return
        try:
            require_owned_case(db, case_id, user_id)
        except HTTPException:
            await _reject_websocket(websocket, code=4403)
            return
        await websocket.accept()
        logger.info("WebSocket analysis connection opened for case %s, user %s", case_id, user_id)
        # Initialize services
        document_processor = DocumentProcessor()
        rag_service = RAGService(document_processor=document_processor)
        coordinator = AgentCoordinator(
            db=db,
            rag_service=rag_service,
            document_processor=document_processor
        )
        
        # Define analysis types to run (can be made configurable via query params)
        analysis_types = [
            "timeline",
            "key_facts",
            "discrepancy",
            "risk",
            "summary",
            "entity_extraction",
            "privilege_check",
            "relationship"
        ]
        
        # Send initial message
        await websocket.send_json({
            "type": "start",
            "message": f"Starting analysis for case {case_id}",
            "analysis_types": analysis_types,
            "total_steps": len(analysis_types)
        })
        
        # Create thread config for LangGraph
        thread_config = {
            "configurable": {
                "thread_id": f"case_{case_id}",
                "recursion_limit": 50
            }
        }
        
        # Initialize state
        from app.services.langchain_agents.legacy_stubs import AnalysisState
        initial_state: AnalysisState = {
            "case_id": case_id,
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "classification_result": None,
            "entities_result": None,
            "privilege_result": None,
            "relationship_result": None,
            "analysis_types": analysis_types,
            "errors": [],
            "metadata": {}
        }
        
        # Stream analysis using LangGraph
        completed_nodes = set()
        total_nodes = len(analysis_types) + 1  # +1 for supervisor
        
        async def send_progress(node_name: str, percentage: int, message: str = None):
            """Helper to send progress updates"""
            await websocket.send_json({
                "type": "progress",
                "node": node_name,
                "percentage": percentage,
                "message": message or f"{node_name} завершен",
                "completed_nodes": list(completed_nodes)
            })
        
        # Stream graph execution (use sync stream for now, async astream requires async coordinator)
        try:
            for state_update in coordinator.graph.stream(initial_state, thread_config, stream_mode="updates"):
                # state_update is a dict with node names as keys
                for node_name, node_state in state_update.items():
                    if node_name not in completed_nodes:
                        completed_nodes.add(node_name)
                        percentage = int((len(completed_nodes) / total_nodes) * 100)
                        
                        await send_progress(
                            node_name=node_name,
                            percentage=percentage,
                            message=f"Агент {node_name} завершил анализ"
                        )
                        
                        # Send result if available
                        if isinstance(node_state, dict):
                            result_key = f"{node_name}_result"
                            if result_key in node_state and node_state[result_key]:
                                await websocket.send_json({
                                    "type": "agent_result",
                                    "node": node_name,
                                    "result": node_state[result_key]
                                })
            
            # Get final state
            final_state = coordinator.graph.get_state(thread_config).values
            
            # Send completion message
            await websocket.send_json({
                "type": "complete",
                "message": "Анализ завершен",
                "percentage": 100,
                "results": {
                    "timeline": final_state.get("timeline_result"),
                    "key_facts": final_state.get("key_facts_result"),
                    "discrepancy": final_state.get("discrepancy_result"),
                    "risk": final_state.get("risk_result"),
                    "summary": final_state.get("summary_result"),
                    "entities": final_state.get("entities_result"),
                    "privilege": final_state.get("privilege_result"),
                    "relationship": final_state.get("relationship_result"),
                }
            })
            
        except Exception as e:
            logger.error(f"Error during analysis streaming for case {case_id}: {e}", exc_info=True)
            await websocket.send_json({
                "type": "error",
                "message": f"Ошибка во время анализа: {str(e)}",
                "error": str(e)
            })
            raise
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for case {case_id}")
    except Exception as e:
        logger.error(f"WebSocket error for case {case_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Ошибка: {str(e)}",
                "error": str(e)
            })
        except:
            pass  # Connection may already be closed
    finally:
        db.close()
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/ws/chat/{case_id}")
async def stream_chat(
    websocket: WebSocket,
    case_id: str,
    ticket: str = Query(...),
):
    """
    WebSocket endpoint for streaming chat responses
    
    Streams RAG responses token by token (future enhancement).
    Currently sends complete response.
    """
    # Get database session
    from app.utils.database import SessionLocal
    db = SessionLocal()
    
    try:
        if app_config.TABULAR_ONLY_MODE:
            await _reject_websocket(websocket, code=4404)
            return
        user_id = _ticket_user_id(ticket, resource_type="case", resource_id=case_id)
        if not user_id or not _active_user(db, user_id):
            await _reject_websocket(websocket)
            return
        try:
            require_owned_case(db, case_id, user_id)
        except HTTPException:
            await _reject_websocket(websocket, code=4403)
            return
        await websocket.accept()
        logger.info("WebSocket chat connection opened for case %s, user %s", case_id, user_id)
        document_processor = DocumentProcessor()
        rag_service = RAGService(document_processor=document_processor)
        
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            query = data.get("query", "")
            history = data.get("history", [])
            pro_search = data.get("pro_search", False)
            deep_think = data.get("deep_think", False)
            
            
            if not query:
                await websocket.send_json({
                    "type": "error",
                    "message": "Query is required"
                })
                continue
            
            # Send acknowledgment
            if pro_search or deep_think:
                await websocket.send_json({
                    "type": "processing",
                    "message": "🔍 Deep Research activated..."
                })
            else:
                await websocket.send_json({
                    "type": "processing",
                    "message": "Обработка запроса..."
                })
            
            # Generate response with sources
            try:
                # Pro Search or Deep Think uses more sources and deeper analysis
                k = 15 if (pro_search or deep_think) else 5
                
                
                # Phase 2: Support citation-first generation via config
                from app.config import config
                use_citation_first = config.CITATION_FIRST_ENABLED
                
                answer, sources = rag_service.generate_with_sources(
                    case_id=case_id,
                    query=query,
                    k=k,
                    db=db,
                    history=history,
                    use_citation_first=use_citation_first  # Phase 2: Citation-first generation
                )
                
                
                # Stream tokens for Perplexity-style UX
                # Split answer into tokens (words) and send progressively
                words = answer.split(' ')
                accumulated = ''
                
                for i, word in enumerate(words):
                    accumulated += word
                    if i < len(words) - 1:
                        accumulated += ' '
                    
                    # Send token
                    await websocket.send_json({
                        "type": "token",
                        "content": word + (' ' if i < len(words) - 1 else ''),
                        "done": False
                    })
                    
                    # Small delay for smooth streaming effect
                    import asyncio
                    await asyncio.sleep(0.02)  # ~50 tokens per second
                
                # Send final response with sources
                await websocket.send_json({
                    "type": "response",
                    "answer": answer,
                    "sources": sources,
                    "done": True
                })
                
            except Exception as e:
                logger.error(f"Error generating chat response: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Ошибка при генерации ответа: {str(e)}"
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket chat disconnected for case {case_id}")
    except Exception as e:
        logger.error(f"WebSocket chat error for case {case_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Ошибка: {str(e)}"
            })
        except:
            pass
    finally:
        db.close()
        try:
            await websocket.close()
        except:
            pass


@tabular_router.websocket("/ws/tabular-review/{review_id}")
async def stream_tabular_review_updates(
    websocket: WebSocket,
    review_id: str,
    ticket: str = Query(...),
):
    """
    WebSocket endpoint for streaming tabular review updates in real-time
    
    Streams updates when:
    - Cells are updated during extraction
    - Columns are added
    - Extraction progress changes
    - Presence updates
    """
    # Initialize presence service
    presence_service = get_presence_service(redis_url=app_config.REDIS_URL)
    
    # Get database session
    from app.utils.database import SessionLocal
    db = SessionLocal()
    user_id: Optional[str] = None
    connection_id: Optional[str] = None
    presence_task: Optional[asyncio.Task] = None
    message_task: Optional[asyncio.Task] = None
    
    try:
        user_id = _ticket_user_id(ticket, resource_type="tabular_review", resource_id=review_id)
        user = _active_user(db, user_id) if user_id else None
        if not user_id or not user:
            await _reject_websocket(websocket)
            return
        try:
            require_owned_review(db, review_id, user_id)
        except HTTPException:
            await _reject_websocket(websocket, code=4403)
            return

        # WebSocketManager accepts the connection only after auth and ownership checks.
        connection_id = await websocket_manager.connect(websocket, review_id, user_id)
        logger.info("WebSocket tabular review connection opened for review %s, user %s", review_id, user_id)
        user_name = user.full_name if user else None
        presence_service.update_presence(review_id, user_id, user_name)
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "review_id": review_id,
            "message": "Connected to tabular review updates"
        })
        
        # Send initial presence update
        if user_id:
            present_users = presence_service.get_present_users(review_id)
            await websocket_manager.broadcast_presence_update(review_id, {"users": present_users})
        
        # Send periodic presence updates
        async def send_presence_updates():
            while True:
                try:
                    await asyncio.sleep(30)  # Update every 30 seconds
                    if user_id:
                        user = db.query(User).filter(User.id == user_id).first()
                        user_name = user.full_name if user else None
                        presence_service.update_presence(review_id, user_id, user_name)
                        present_users = presence_service.get_present_users(review_id)
                        await websocket_manager.broadcast_presence_update(
                            review_id,
                            {"users": present_users},
                            exclude_connection_id=connection_id
                        )
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in presence updates: {e}", exc_info=True)
        
        if user_id:
            presence_task = asyncio.create_task(send_presence_updates())

        async def handle_messages():
            while True:
                try:
                    await websocket.receive_json()
                    # Reserved for future client commands (e.g. lock requests).
                except WebSocketDisconnect:
                    logger.info("WebSocket tabular review disconnected for review %s", review_id)
                    break
                except Exception as exc:
                    logger.debug("WebSocket tabular review receive ended for %s: %s", review_id, exc)
                    break

        message_task = asyncio.create_task(handle_messages())

        # Realtime updates are pushed via websocket_manager from tabular_review_service.
        # Keep this handler alive until the client disconnects.
        try:
            await message_task
        except asyncio.CancelledError:
            pass
                
    except Exception as e:
        logger.error(f"WebSocket tabular review error for review {review_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Ошибка: {str(e)}"
            })
        except:
            pass
    finally:
        # Clean up
        if presence_task:
            presence_task.cancel()
            try:
                await presence_task
            except asyncio.CancelledError:
                pass
        if message_task:
            message_task.cancel()
            try:
                await message_task
            except asyncio.CancelledError:
                pass
        
        if user_id and connection_id:
            presence_service.remove_presence(review_id, user_id)
            websocket_manager.disconnect(review_id, connection_id)
            # Broadcast updated presence
            present_users = presence_service.get_present_users(review_id)
            await websocket_manager.broadcast_presence_update(review_id, {"users": present_users})
        
        db.close()
        try:
            await websocket.close()
        except:
            pass

