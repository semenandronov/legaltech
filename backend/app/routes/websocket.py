"""WebSocket routes for streaming analysis"""
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/analysis/{case_id}")
async def stream_analysis(
    websocket: WebSocket,
    case_id: str
):
    """
    WebSocket endpoint for streaming LangGraph analysis progress
    
    Streams progress updates as analysis agents complete their tasks.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection opened for case {case_id}")
    
    # Get database session
    from app.utils.database import SessionLocal
    db = SessionLocal()
    
    try:
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
        from app.services.langchain_agents.state import AnalysisState
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
    case_id: str
):
    """
    WebSocket endpoint for streaming chat responses
    
    Streams RAG responses token by token (future enhancement).
    Currently sends complete response.
    """
    await websocket.accept()
    logger.info(f"WebSocket chat connection opened for case {case_id}")
    
    # Get database session
    from app.utils.database import SessionLocal
    db = SessionLocal()
    
    try:
        document_processor = DocumentProcessor()
        rag_service = RAGService(document_processor=document_processor)
        
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            query = data.get("query", "")
            history = data.get("history", [])
            pro_search = data.get("pro_search", False)
            
            if not query:
                await websocket.send_json({
                    "type": "error",
                    "message": "Query is required"
                })
                continue
            
            # Send acknowledgment
            if pro_search:
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
                # Pro Search uses more sources and deeper analysis
                k = 15 if pro_search else 5
                
                answer, sources = rag_service.generate_with_sources(
                    case_id=case_id,
                    query=query,
                    k=k,
                    db=db,
                    history=history
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

