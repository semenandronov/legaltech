"""Human feedback service for agent interactions"""
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.agent_interaction import AgentInteraction, AgentExecutionLog
from app.services.langchain_agents.state import AnalysisState, HumanFeedbackRequest
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


class HumanFeedbackService:
    """
    Service for managing human-in-the-loop interactions.
    Enables Harvey-like agent behavior where agents can ask users for input.
    """
    
    # Default timeout for waiting for human response (can be overridden via config)
    DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes (deprecated: use config.HUMAN_FEEDBACK_TIMEOUT)
    
    def __init__(self, db: Session = None):
        """
        Initialize human feedback service
        
        Args:
            db: Database session for persisting interactions
        """
        self.db = db
        self._websocket_callbacks: Dict[str, Callable] = {}
        self._pending_requests: Dict[str, asyncio.Event] = {}
        self._responses: Dict[str, str] = {}
    
    def register_websocket_callback(
        self,
        case_id: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """
        Register a WebSocket callback for sending questions to user
        
        Args:
            case_id: Case identifier
            callback: Async function to send message via WebSocket
        """
        self._websocket_callbacks[case_id] = callback
        logger.info(f"Registered WebSocket callback for case {case_id}")
    
    def unregister_websocket_callback(self, case_id: str) -> None:
        """Unregister WebSocket callback"""
        if case_id in self._websocket_callbacks:
            del self._websocket_callbacks[case_id]
    
    async def request_clarification(
        self,
        state: AnalysisState,
        agent_name: str,
        question: str,
        context: str = None,
        user_id: str = None
    ) -> Optional[str]:
        """
        Request clarification from user
        
        Args:
            state: Current analysis state
            agent_name: Name of the requesting agent
            question: Question to ask
            context: Additional context
            user_id: User ID
            
        Returns:
            User's response or None if timeout
        """
        request = HumanFeedbackRequest(
            request_id=str(uuid.uuid4()),
            agent_name=agent_name,
            question_type="clarification",
            question_text=question,
            context=context,
        )
        
        return await self._send_and_wait(state, request, user_id)
    
    async def request_confirmation(
        self,
        state: AnalysisState,
        agent_name: str,
        question: str,
        context: str = None,
        user_id: str = None
    ) -> Optional[bool]:
        """
        Request confirmation (yes/no) from user
        
        Args:
            state: Current analysis state
            agent_name: Name of the requesting agent
            question: Question to ask
            context: Additional context
            user_id: User ID
            
        Returns:
            True for yes, False for no, None for timeout
        """
        request = HumanFeedbackRequest(
            request_id=str(uuid.uuid4()),
            agent_name=agent_name,
            question_type="confirmation",
            question_text=question,
            options=[
                {"id": "yes", "label": "Да"},
                {"id": "no", "label": "Нет"},
            ],
            context=context,
        )
        
        response = await self._send_and_wait(state, request, user_id)
        
        if response is None:
            return None
        
        return response.lower() in ["yes", "да", "true", "1"]
    
    async def request_choice(
        self,
        state: AnalysisState,
        agent_name: str,
        question: str,
        options: List[Dict[str, str]],
        context: str = None,
        user_id: str = None
    ) -> Optional[str]:
        """
        Request user to choose from options
        
        Args:
            state: Current analysis state
            agent_name: Name of the requesting agent
            question: Question to ask
            options: List of options [{"id": "a", "label": "Option A"}, ...]
            context: Additional context
            user_id: User ID
            
        Returns:
            Selected option ID or None if timeout
        """
        request = HumanFeedbackRequest(
            request_id=str(uuid.uuid4()),
            agent_name=agent_name,
            question_type="choice",
            question_text=question,
            options=options,
            context=context,
        )
        
        return await self._send_and_wait(state, request, user_id)
    
    async def _send_and_wait(
        self,
        state: AnalysisState,
        request: HumanFeedbackRequest,
        user_id: str = None,
        timeout: int = None
    ) -> Optional[str]:
        """
        Send request and wait for response
        
        Args:
            state: Current analysis state
            request: Feedback request
            user_id: User ID for DB persistence
            timeout: Timeout in seconds
            
        Returns:
            User's response or None
        """
        case_id = state.get("case_id")
        timeout = timeout or self.DEFAULT_TIMEOUT_SECONDS
        
        # Persist to database if available
        if self.db and user_id:
            self._persist_request(case_id, user_id, request)
        
        # Create event for waiting
        event = asyncio.Event()
        self._pending_requests[request.request_id] = event
        
        # Send via WebSocket if callback registered
        callback = self._websocket_callbacks.get(case_id)
        if callback:
            try:
                await callback({
                    "type": "agent_question",
                    "request_id": request.request_id,
                    "agent_name": request.agent_name,
                    "question_type": request.question_type,
                    "question_text": request.question_text,
                    "options": request.options,
                    "context": request.context,
                })
                logger.info(f"Sent question via WebSocket: {request.request_id}")
            except Exception as e:
                logger.error(f"Error sending via WebSocket: {e}")
        
        # Wait for response with timeout
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            response = self._responses.get(request.request_id)
            
            # Update database (extract run_id from state if available)
            run_id = state.get("metadata", {}).get("langsmith_run_id")
            if self.db and user_id:
                self._update_response(request.request_id, response, run_id=run_id)
            
            return response
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response: {request.request_id}")
            
            if self.db and user_id:
                self._mark_timeout(request.request_id)
            
            return None
        finally:
            # Cleanup
            if request.request_id in self._pending_requests:
                del self._pending_requests[request.request_id]
            if request.request_id in self._responses:
                del self._responses[request.request_id]
    
    def receive_response(self, request_id: str, response: str, run_id: Optional[str] = None) -> bool:
        """
        Receive response from user (called by WebSocket handler)
        
        Args:
            request_id: Request ID
            response: User's response
            
        Returns:
            True if request was pending
        """
        if request_id not in self._pending_requests:
            logger.warning(f"Response for unknown request: {request_id}")
            return False
        
        self._responses[request_id] = response
        self._pending_requests[request_id].set()
        
        logger.info(f"Received response for request: {request_id}")
        return True
    
    def _persist_request(
        self,
        case_id: str,
        user_id: str,
        request: HumanFeedbackRequest
    ) -> None:
        """Persist request to database"""
        try:
            interaction = AgentInteraction(
                id=request.request_id,
                case_id=case_id,
                user_id=user_id,
                agent_name=request.agent_name,
                question_type=request.question_type,
                question_text=request.question_text,
                context=request.context,
                options=request.options,
                status="pending",
                timeout_at=datetime.utcnow() + timedelta(seconds=self.DEFAULT_TIMEOUT_SECONDS),
            )
            self.db.add(interaction)
            self.db.commit()
        except Exception as e:
            logger.error(f"Error persisting request: {e}")
            self.db.rollback()
    
    def _update_response(self, request_id: str, response: str, run_id: Optional[str] = None) -> None:
        """Update response in database and save feedback for learning"""
        try:
            interaction = self.db.query(AgentInteraction).filter(
                AgentInteraction.id == request_id
            ).first()
            
            if interaction:
                interaction.user_response = response
                interaction.status = "answered"
                interaction.answered_at = datetime.utcnow()
                self.db.commit()
                
                # Save feedback for continuous learning
                try:
                    from app.services.langchain_agents.learning_service import ContinuousLearningService
                    learning_service = ContinuousLearningService(self.db)
                    
                    # Save feedback with traces asynchronously
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # If loop is running, create task but don't await
                            asyncio.create_task(
                                learning_service.save_feedback_with_traces(
                                    case_id=interaction.case_id,
                                    agent_name=interaction.agent_name,
                                    feedback=response,
                                    traces=None,
                                    run_id=run_id
                                )
                            )
                        else:
                            loop.run_until_complete(
                                learning_service.save_feedback_with_traces(
                                    case_id=interaction.case_id,
                                    agent_name=interaction.agent_name,
                                    feedback=response,
                                    traces=None,
                                    run_id=run_id
                                )
                            )
                    except RuntimeError:
                        # No event loop, create new one
                        asyncio.run(
                            learning_service.save_feedback_with_traces(
                                case_id=interaction.case_id,
                                agent_name=interaction.agent_name,
                                feedback=response,
                                traces=None,
                                run_id=run_id
                            )
                        )
                    
                    logger.debug(f"Saved feedback for learning: {request_id}")
                except Exception as ls_error:
                    logger.warning(f"Failed to save feedback for learning: {ls_error}")
        except Exception as e:
            logger.error(f"Error updating response: {e}")
            self.db.rollback()
    
    def _mark_timeout(self, request_id: str) -> None:
        """Mark request as timed out in database"""
        try:
            interaction = self.db.query(AgentInteraction).filter(
                AgentInteraction.id == request_id
            ).first()
            
            if interaction:
                interaction.status = "timeout"
                self.db.commit()
        except Exception as e:
            logger.error(f"Error marking timeout: {e}")
            self.db.rollback()
    
    def get_pending_requests(self, case_id: str) -> List[Dict[str, Any]]:
        """Get all pending requests for a case"""
        if not self.db:
            return []
        
        try:
            interactions = self.db.query(AgentInteraction).filter(
                AgentInteraction.case_id == case_id,
                AgentInteraction.status == "pending"
            ).all()
            
            return [i.to_dict() for i in interactions]
        except Exception as e:
            logger.error(f"Error getting pending requests: {e}")
            return []


# Global instance
_feedback_service: Optional[HumanFeedbackService] = None


def get_feedback_service(db: Session = None) -> HumanFeedbackService:
    """Get the global feedback service instance"""
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = HumanFeedbackService(db)
    elif db and _feedback_service.db is None:
        _feedback_service.db = db
    return _feedback_service

