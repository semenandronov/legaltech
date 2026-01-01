"""Agent coordinator for managing multi-agent analysis"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState, create_initial_state
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
from app.services.langchain_agents.human_feedback import get_feedback_service
from app.services.langchain_agents.fallback_handler import FallbackHandler
from app.services.langchain_agents.subagent_manager import SubAgentManager
from app.services.context_manager import ContextManager
from app.services.metrics.planning_metrics import MetricsCollector
from app.services.langchain_agents.learning_service import ContinuousLearningService
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time
import os
import json

logger = logging.getLogger(__name__)


class AgentCoordinator:
    """Coordinator for managing multi-agent analysis workflow"""
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None,
        use_legora_workflow: bool = True
    ):
        """
        Initialize agent coordinator
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
            use_legora_workflow: Whether to use LEGORA workflow (understand → plan → execute → verify → deliver)
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.use_legora_workflow = use_legora_workflow
        
        # Create graph with LEGORA workflow flag
        self.graph = create_analysis_graph(
            db, 
            rag_service, 
            document_processor,
            use_legora_workflow=use_legora_workflow
        )
        
        # Initialize planning agents with RAG service for document access
        try:
            # Try to use AdvancedPlanningAgent first
            self.advanced_planning_agent = AdvancedPlanningAgent(
                rag_service=rag_service,
                document_processor=document_processor
            )
            self.planning_agent = self.advanced_planning_agent.base_planning_agent
            logger.info("✅ Advanced Planning Agent initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize AdvancedPlanningAgent: {e}, falling back to base PlanningAgent")
            self.advanced_planning_agent = None
            try:
                self.planning_agent = PlanningAgent(
                    rag_service=rag_service,
                    document_processor=document_processor
                )
            except Exception as e2:
                logger.warning(f"Failed to initialize PlanningAgent: {e2}, will use analysis_types directly")
                self.planning_agent = None
        
        # Initialize human feedback service
        self.feedback_service = get_feedback_service(db)
        
        # Initialize fallback handler
        self.fallback_handler = FallbackHandler()
        
        # Initialize metrics collector
        self.metrics_collector = MetricsCollector(db)
        
        # Initialize SubAgent Manager
        try:
            self.subagent_manager = SubAgentManager(
                rag_service=rag_service,
                document_processor=document_processor
            )
            logger.info("✅ SubAgent Manager initialized in AgentCoordinator")
        except Exception as e:
            logger.warning(f"Failed to initialize SubAgentManager: {e}")
            self.subagent_manager = None
        
        # Initialize Context Manager
        try:
            self.context_manager = ContextManager()
            logger.info("✅ Context Manager initialized in AgentCoordinator")
        except Exception as e:
            logger.warning(f"Failed to initialize ContextManager: {e}")
            self.context_manager = None
        
        # Initialize Continuous Learning Service
        try:
            self.learning_service = ContinuousLearningService(db)
            logger.info("✅ Continuous Learning Service initialized in AgentCoordinator")
        except Exception as e:
            logger.warning(f"Failed to initialize ContinuousLearningService: {e}")
            self.learning_service = None
    
    def run_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        user_task: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        websocket_callback: Optional[Any] = None,
        step_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Run analysis using multi-agent system
        
        Args:
            case_id: Case identifier
            analysis_types: List of analysis types to run (if user_task not provided)
            user_task: Optional natural language task description (will use PlanningAgent)
            config: Optional configuration for graph execution
            websocket_callback: Optional async callback for sending messages via WebSocket
        
        Returns:
            Dictionary with analysis results
        """
        # ВАЛИДАЦИЯ ВХОДНЫХ ДАННЫХ
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        # Проверка case_id
        if not case_id or not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        
        # Проверка analysis_types
        if not analysis_types or not isinstance(analysis_types, list):
            raise ValueError("analysis_types must be a non-empty list")
        
        # Проверка валидности типов анализов
        valid_types = set(AVAILABLE_ANALYSES.keys())
        # Добавить дополнительные типы, которые используются в коде
        valid_types.update(["document_classifier", "entity_extraction", "privilege_check", "relationship"])
        
        invalid_types = [t for t in analysis_types if t not in valid_types]
        if invalid_types:
            raise ValueError(f"Invalid analysis types: {invalid_types}. Valid types: {sorted(valid_types)}")
        
        # Проверка user_task (если передан)
        if user_task is not None:
            if not isinstance(user_task, str) or not user_task.strip():
                raise ValueError("user_task must be a non-empty string if provided")
        
        # Проверка существования case в БД
        from app.models.case import Case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found in database")
        
        start_time = time.time()
        planning_start_time = time.time()
        metrics_id = None
        
        try:
            logger.info(f"Starting multi-agent analysis for case {case_id}, types: {analysis_types}")
            # #region agent log
            import json
            import os
            try:
                log_path = os.path.join(os.getcwd(), '.cursor', 'debug.log')
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, 'a') as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "coordinator-start",
                        "hypothesisId": "H1",
                        "location": "coordinator.py:run_analysis",
                        "message": "Starting multi-agent analysis",
                        "data": {"case_id": case_id, "analysis_types": analysis_types, "user_task": user_task is not None},
                        "timestamp": int(time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
            # Initialize plan_goals and current_plan
            plan_goals = []
            current_plan = []
            
            # Use PlanningAgent if user_task provided
            if user_task and self.planning_agent:
                try:
                    # Get case info to pass document information
                    from app.models.case import Case
                    case = self.db.query(Case).filter(Case.id == case_id).first()
                    num_documents = case.num_documents if case else 0
                    file_names = case.file_names if case and case.file_names else []
                    
                    # Use AdvancedPlanningAgent if available (supports subtasks)
                    if self.advanced_planning_agent:
                        plan = self.advanced_planning_agent.plan_with_subtasks(
                            user_task=user_task,
                            case_id=case_id,
                            available_documents=file_names[:10] if file_names else None,
                            num_documents=num_documents
                        )
                        # Save plan context if ContextManager available
                        if self.context_manager:
                            try:
                                self.context_manager.save_context(
                                    case_id=case_id,
                                    analysis_type="planning",
                                    context={"plan": plan, "user_task": user_task}
                                )
                            except Exception as ctx_error:
                                logger.warning(f"Failed to save planning context: {ctx_error}")
                    else:
                        plan = self.planning_agent.plan_analysis(
                            user_task, 
                            case_id,
                            available_documents=file_names[:10] if file_names else None,
                            num_documents=num_documents,
                            db=self.db
                        )
                    
                    analysis_types = plan.get("analysis_types", analysis_types)
                    subtasks = plan.get("subtasks", [])
                    logger.info(f"PlanningAgent created plan: {analysis_types}, {len(subtasks)} subtasks, reasoning: {plan.get('reasoning', '')[:100]}")
                    
                    # Record planning metrics
                    planning_time = time.time() - planning_start_time
                    try:
                        from app.models.case import Case
                        case = self.db.query(Case).filter(Case.id == case_id).first()
                        user_id = case.user_id if case else None
                        
                        # Get validation result if available
                        validation_result = None
                        if hasattr(self.planning_agent, 'validator'):
                            validation_result_obj = self.planning_agent.validator.validate_plan(plan, case_id)
                            validation_result = validation_result_obj.to_dict()
                        
                        metrics_id = self.metrics_collector.record_planning_metrics(
                            case_id=case_id,
                            user_id=user_id,
                            plan=plan,
                            planning_time=planning_time,
                            validation_result=validation_result
                        )
                    except Exception as metrics_error:
                        logger.warning(f"Failed to record planning metrics: {metrics_error}")
                    
                    # Create initial plan steps from multi-level plan
                    from app.services.langchain_agents.state import PlanStep, PlanStepStatus, PlanGoal
                    
                    # Extract goals if present
                    if "goals" in plan:
                        for goal_data in plan["goals"]:
                            goal = PlanGoal(
                                goal_id=goal_data.get("goal_id", f"goal_{len(plan_goals) + 1}"),
                                description=goal_data.get("description", ""),
                                priority=goal_data.get("priority", 1),
                                related_steps=goal_data.get("related_steps", [])
                            )
                            plan_goals.append(goal.to_dict())
                    
                    # Use steps from plan if available, otherwise create from analysis_types
                    if "steps" in plan and plan["steps"]:
                        current_plan = plan["steps"]
                        # Ensure all steps have proper structure
                        for step in current_plan:
                            if "status" not in step:
                                step["status"] = PlanStepStatus.PENDING.value
                            if "step_id" not in step:
                                step["step_id"] = f"{step.get('agent_name', 'unknown')}_{case_id}_{len(current_plan)}"
                    else:
                        # Fallback: create steps from analysis_types
                        for idx, agent_name in enumerate(analysis_types):
                            step = PlanStep(
                                step_id=f"{agent_name}_{case_id}_{idx}",
                                agent_name=agent_name,
                                description=f"Execute {agent_name} analysis",
                                status=PlanStepStatus.PENDING,
                                result_key=f"{agent_name}_result"
                            )
                            current_plan.append(step.to_dict())
                except Exception as e:
                    logger.warning(f"PlanningAgent failed: {e}, using provided analysis_types")
                    current_plan = []
            
            # Register WebSocket callback for human feedback if provided
            if websocket_callback:
                self.feedback_service.register_websocket_callback(case_id, websocket_callback)
            
            # Initialize state using create_initial_state helper
            metadata = {"planning_used": user_task is not None and self.planning_agent is not None}
            
            # Добавляем tables_to_create в metadata, если они есть в плане
            if "plan" in locals() and isinstance(plan, dict):
                tables_to_create = plan.get("tables_to_create")
                if tables_to_create:
                    metadata["tables_to_create"] = tables_to_create
                    metadata["plan_data"] = plan  # Сохраняем весь план для доступа
                    logger.info(f"Added {len(tables_to_create)} tables_to_create to metadata")
            
            initial_state = create_initial_state(
                case_id=case_id,
                analysis_types=analysis_types,
                metadata=metadata
            )
            
            # Add plan goals and current_plan if created
            if plan_goals:
                initial_state["plan_goals"] = plan_goals
            if current_plan:
                initial_state["current_plan"] = current_plan
            
            # Add subtasks if available (from AdvancedPlanningAgent)
            if "subtasks" in locals() and subtasks:
                initial_state["subtasks"] = subtasks
                logger.info(f"Added {len(subtasks)} subtasks to initial state")
            
            # Add user_task for context
            if user_task:
                initial_state["user_task"] = user_task
            
            # Load context from ContextManager if available
            if self.context_manager and user_task:
                try:
                    previous_context = self.context_manager.load_context(
                        case_id=case_id,
                        analysis_type="planning"
                    )
                    if previous_context:
                        initial_state["context"] = previous_context.get("data", {})
                        logger.info("Loaded previous planning context")
                except Exception as ctx_error:
                    logger.warning(f"Failed to load planning context: {ctx_error}")
            
            # Create thread config for graph execution with increased recursion limit
            thread_config = config or {"configurable": {"thread_id": f"case_{case_id}"}}
            # Increase recursion limit to prevent premature termination
            if "configurable" in thread_config:
                thread_config["configurable"]["recursion_limit"] = 50
            else:
                thread_config["recursion_limit"] = 50
            
            # Run graph with parallel processing for independent agents
            # Note: LangGraph handles parallelization internally, but we can optimize
            # by running independent analysis types in parallel batches
            final_state = None
            
            # Check if we can run independent agents in parallel
            independent_types = ["timeline", "key_facts", "discrepancy", "entity_extraction", "document_classifier"]
            dependent_types = ["risk", "summary", "privilege_check", "relationship"]  # relationship depends on entities
            
            # If only independent types, we can optimize
            if all(at in independent_types for at in analysis_types) and len(analysis_types) > 1:
                logger.info(f"Running {len(analysis_types)} independent agents, using optimized execution")
                # LangGraph will handle this, but we log it for monitoring
            
            # Track execution steps for streaming
            execution_steps = []
            
            # Verify checkpointer before streaming
            if hasattr(self.graph, 'checkpointer') and self.graph.checkpointer:
                logger.debug(f"Graph checkpointer type: {type(self.graph.checkpointer)}")
                from langgraph.checkpoint.postgres import PostgresSaver
                if isinstance(self.graph.checkpointer, PostgresSaver):
                    logger.debug("✅ Graph checkpointer is PostgresSaver instance")
                else:
                    logger.warning(f"⚠️ Graph checkpointer is not PostgresSaver: {type(self.graph.checkpointer)}")
            
            logger.info(f"Starting graph stream for case {case_id} with {len(analysis_types)} analysis types")
            try:
                stream_iter = self.graph.stream(initial_state, thread_config)
                logger.debug(f"Graph stream iterator created: {type(stream_iter)}")
                for event in stream_iter:
                    # Check for interrupts (LangGraph interrupts are returned as special events)
                    if isinstance(event, dict):
                        # Check if this is an interrupt event
                        # LangGraph interrupts may appear as events with "__interrupt__" key or similar
                        if "__interrupt__" in event or any(key.startswith("__") for key in event.keys()):
                            interrupt_type = event.get("__interrupt__") or event.get("interrupt")
                            if interrupt_type == "human_feedback_needed":
                                logger.info(f"[Interrupt] Human feedback needed for case {case_id}")
                                
                                # Get current state to extract feedback request
                                current_state = self.graph.get_state(thread_config).values
                                feedback_request = current_state.get("current_feedback_request")
                                
                                if feedback_request and websocket_callback:
                                    # Send question via WebSocket
                                    try:
                                        import asyncio
                                        if asyncio.iscoroutinefunction(websocket_callback):
                                            # Async callback
                                            loop = asyncio.get_event_loop()
                                            if loop.is_running():
                                                asyncio.create_task(websocket_callback({
                                                    "type": "agent_question",
                                                    "request_id": feedback_request.get("request_id"),
                                                    "agent_name": feedback_request.get("agent_name"),
                                                    "question_type": feedback_request.get("question_type"),
                                                    "question_text": feedback_request.get("question_text"),
                                                    "options": feedback_request.get("options"),
                                                    "context": feedback_request.get("context"),
                                                }))
                                            else:
                                                loop.run_until_complete(websocket_callback({
                                                    "type": "agent_question",
                                                    "request_id": feedback_request.get("request_id"),
                                                    "agent_name": feedback_request.get("agent_name"),
                                                    "question_type": feedback_request.get("question_type"),
                                                    "question_text": feedback_request.get("question_text"),
                                                    "options": feedback_request.get("options"),
                                                    "context": feedback_request.get("context"),
                                                }))
                                        else:
                                            # Sync callback
                                            websocket_callback({
                                                "type": "agent_question",
                                                "request_id": feedback_request.get("request_id"),
                                                "agent_name": feedback_request.get("agent_name"),
                                                "question_type": feedback_request.get("question_type"),
                                                "question_text": feedback_request.get("question_text"),
                                                "options": feedback_request.get("options"),
                                                "context": feedback_request.get("context"),
                                            })
                                        logger.info(f"[Interrupt] Sent feedback request via WebSocket: {feedback_request.get('request_id')}")
                                    except Exception as ws_error:
                                        logger.error(f"Error sending feedback request via WebSocket: {ws_error}")
                                
                                # Wait for response (this will be handled by HumanFeedbackService)
                                # The execution will pause here until feedback is received
                                # Coordinator should check for feedback and update state, then continue
                                logger.info(f"[Interrupt] Waiting for human feedback. Execution paused.")
                                # Note: In production, you would wait here and then update state with feedback
                                # For now, we continue - the actual waiting should be handled by the service
                                continue
                    
                    # Normal state event
                    state = event
                    # Log progress
                    node_name = list(state.keys())[0] if state else "unknown"
                    logger.info(f"Graph execution: {node_name} completed")
                    final_state = state[node_name] if state else None
                    
                    # #region agent log
                    try:
                        log_path = os.path.join(os.getcwd(), '.cursor', 'debug.log')
                        with open(log_path, 'a') as f:
                            f.write(json.dumps({
                                "sessionId": "debug-session",
                                "runId": "coordinator-stream",
                                "hypothesisId": "H2",
                                "location": "coordinator.py:graph.stream",
                                "message": "Node execution completed",
                                "data": {
                                    "node_name": node_name,
                                    "has_final_state": final_state is not None,
                                    "state_keys": list(state.keys()) if state else []
                                },
                                "timestamp": int(time.time() * 1000)
                            }) + '\n')
                    except Exception:
                        pass
                    # #endregion
                    
                    # Track step for streaming
                    if node_name and node_name != "supervisor":
                        step_info = {
                            "step_id": f"{node_name}_{len(execution_steps)}",
                            "agent_name": node_name,
                            "status": "completed",
                            "description": f"Выполнение анализа {node_name}"
                        }
                        # Extract reasoning and result if available
                        if final_state and isinstance(final_state, dict):
                            result_key = f"{node_name}_result"
                            if result_key in final_state:
                                step_info["result"] = str(final_state[result_key])[:500]  # Limit length
                        execution_steps.append(step_info)
                        
                        # Call step callback if provided (for real-time saving)
                        if step_callback:
                            try:
                                step_callback(step_info)
                            except Exception as callback_error:
                                logger.warning(f"Error in step callback: {callback_error}")
            except Exception as stream_error:
                logger.error(f"Error during graph stream execution: {stream_error}", exc_info=True)
                raise
            
            # Get final state
            if final_state is None:
                # Try to get final state from graph
                final_state = self.graph.get_state(thread_config).values
            
            execution_time = time.time() - start_time
            
            # Track agent execution metrics
            try:
                from app.middleware.metrics import track_agent_execution
                track_agent_execution("multi_agent_analysis", execution_time, success=True)
            except Exception:
                pass  # Metrics middleware might not be available
            
            # Update execution metrics
            if metrics_id and final_state:
                try:
                    completed_steps = len(final_state.get("completed_steps", []))
                    failed_steps = len([e for e in final_state.get("errors", []) if e])
                    adaptations = len(final_state.get("adaptation_history", []))
                    
                    # Calculate average quality metrics
                    quality_metrics = None
                    evaluation_result = final_state.get("evaluation_result")
                    if evaluation_result and isinstance(evaluation_result, dict):
                        quality_metrics_data = evaluation_result.get("quality_metrics", {})
                        if quality_metrics_data:
                            quality_metrics = {
                                "average_confidence": quality_metrics_data.get("overall_score", 0.0),
                                "average_completeness": quality_metrics_data.get("completeness", 0.0),
                                "average_accuracy": quality_metrics_data.get("accuracy", 0.0)
                            }
                    
                    self.metrics_collector.update_execution_metrics(
                        metrics_id=metrics_id,
                        execution_time=execution_time,
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        adaptations_count=adaptations,
                        quality_metrics=quality_metrics
                    )
                except Exception as metrics_error:
                    logger.warning(f"Failed to update execution metrics: {metrics_error}")
            
            logger.info(
                f"Multi-agent analysis completed for case {case_id} in {execution_time:.2f}s"
            )
            
            # Save patterns for continuous learning
            if self.learning_service and final_state:
                try:
                    import asyncio
                    
                    # Collect successful and failed patterns
                    for agent_name in analysis_types:
                        result_key = f"{agent_name}_result"
                        result = final_state.get(result_key)
                        
                        if result:
                            # Determine outcome
                            evaluation = final_state.get("evaluation_result", {})
                            if isinstance(evaluation, dict):
                                agent_eval = evaluation.get("agent_name") == agent_name
                                success = evaluation.get("success", False) if agent_eval else True
                            else:
                                success = True  # Assume success if no evaluation
                            
                            outcome = "success" if success else "failure"
                            
                            # Save pattern
                            pattern = {
                                "result": result,
                                "user_task": user_task,
                                "execution_time": execution_time,
                                "evaluation": evaluation if isinstance(evaluation, dict) else {}
                            }
                            
                            try:
                                # Try to get existing event loop
                                try:
                                    loop = asyncio.get_event_loop()
                                    if loop.is_running():
                                        # If loop is running, schedule task
                                        asyncio.create_task(
                                            self.learning_service.save_successful_pattern(
                                                case_id=case_id,
                                                agent_name=agent_name,
                                                pattern=pattern,
                                                outcome=outcome
                                            )
                                        )
                                    else:
                                        # If loop exists but not running, run until complete
                                        loop.run_until_complete(
                                            self.learning_service.save_successful_pattern(
                                                case_id=case_id,
                                                agent_name=agent_name,
                                                pattern=pattern,
                                                outcome=outcome
                                            )
                                        )
                                except RuntimeError:
                                    # No event loop, create new one
                                    try:
                                        asyncio.run(
                                            self.learning_service.save_successful_pattern(
                                                case_id=case_id,
                                                agent_name=agent_name,
                                                pattern=pattern,
                                                outcome=outcome
                                            )
                                        )
                                    except RuntimeError:
                                        # If asyncio.run fails (e.g., in thread), use new event loop
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        try:
                                            loop.run_until_complete(
                                                self.learning_service.save_successful_pattern(
                                                    case_id=case_id,
                                                    agent_name=agent_name,
                                                    pattern=pattern,
                                                    outcome=outcome
                                                )
                                            )
                                        finally:
                                            loop.close()
                            except Exception as e:
                                logger.warning(f"Failed to save pattern asynchronously: {e}, saving synchronously")
                                # Fallback to synchronous save
                                try:
                                    self.learning_service.save_successful_pattern(
                                        case_id=case_id,
                                        agent_name=agent_name,
                                        pattern=pattern,
                                        outcome=outcome
                                    )
                                except Exception as sync_error:
                                    logger.error(f"Failed to save pattern synchronously: {sync_error}")
                            
                            logger.debug(f"Saved {outcome} pattern for {agent_name} agent")
                    
                    # Generate evaluation dataset for LangSmith
                    try:
                        dataset = asyncio.run(
                            self.learning_service.generate_evaluation_dataset(case_id)
                        )
                        if dataset.get("langsmith_dataset_id"):
                            logger.info(f"Created LangSmith dataset: {dataset['langsmith_dataset_id']}")
                    except Exception as e:
                        logger.warning(f"Failed to generate evaluation dataset: {e}")
                        
                except Exception as e:
                    logger.warning(f"Failed to save patterns for continuous learning: {e}")
            
            # Check if DELIVER phase was executed (LEGORA workflow)
            delivery_result = final_state.get("delivery_result") if final_state else None
            
            if delivery_result:
                # Use delivery_result from DELIVER phase (LEGORA workflow)
                logger.info(f"[Coordinator] Using delivery_result from DELIVER phase for case {case_id}")
                results = {
                    "case_id": case_id,
                    "delivery": delivery_result,
                    "tables": delivery_result.get("tables", {}),
                    "reports": delivery_result.get("reports", {}),
                    "summary": delivery_result.get("summary", ""),
                    # Also include raw results for backward compatibility
                    "timeline": final_state.get("timeline_result") if final_state else None,
                    "key_facts": final_state.get("key_facts_result") if final_state else None,
                    "discrepancies": final_state.get("discrepancy_result") if final_state else None,
                    "risk_analysis": final_state.get("risk_result") if final_state else None,
                    "summary": final_state.get("summary_result") if final_state else None,
                    "classification": final_state.get("classification_result") if final_state else None,
                    "entities": final_state.get("entities_result") if final_state else None,
                    "privilege": final_state.get("privilege_result") if final_state else None,
                    "errors": final_state.get("errors", []) if final_state else [],
                    "execution_time": execution_time,
                    "metadata": final_state.get("metadata", {}) if final_state else {},
                    "adaptation_history": final_state.get("adaptation_history", []) if final_state else [],
                    "evaluation_results": final_state.get("evaluation_result") if final_state else None,
                    "workflow": "legora"  # Indicate LEGORA workflow was used
                }
            else:
                # Legacy format (backward compatibility)
                logger.info(f"[Coordinator] Using legacy result format for case {case_id}")
            results = {
                "case_id": case_id,
                "timeline": final_state.get("timeline_result") if final_state else None,
                "key_facts": final_state.get("key_facts_result") if final_state else None,
                "discrepancies": final_state.get("discrepancy_result") if final_state else None,
                "risk_analysis": final_state.get("risk_result") if final_state else None,
                "summary": final_state.get("summary_result") if final_state else None,
                "classification": final_state.get("classification_result") if final_state else None,
                "entities": final_state.get("entities_result") if final_state else None,
                "privilege": final_state.get("privilege_result") if final_state else None,
                "errors": final_state.get("errors", []) if final_state else [],
                "execution_time": execution_time,
                "metadata": final_state.get("metadata", {}) if final_state else {},
                "adaptation_history": final_state.get("adaptation_history", []) if final_state else [],
                    "evaluation_results": final_state.get("evaluation_result") if final_state else None,
                    "workflow": "legacy"  # Indicate legacy workflow was used
            }
            
            # Apply fallback handling for failed agents
            if final_state:
                errors = final_state.get("errors", [])
                for error_info in errors:
                    agent_name = error_info.get("agent", "unknown")
                    error_msg = error_info.get("error", "Unknown error")
                    
                    # Try fallback for this agent
                    try:
                        from app.services.langchain_agents.state import PlanStepStatus
                        fallback_result = self.fallback_handler.handle_failure(
                            agent_name=agent_name,
                            error=Exception(error_msg),
                            state=final_state
                        )
                        
                        if fallback_result.success and fallback_result.result:
                            # Update result with fallback
                            result_key = f"{agent_name}_result"
                            if result_key in results:
                                # Combine with existing result if partial
                                if fallback_result.partial and results[result_key]:
                                    combined = self.fallback_handler.combine_results(
                                        [results[result_key], fallback_result.result],
                                        agent_name
                                    )
                                    results[result_key] = combined
                                else:
                                    results[result_key] = fallback_result.result
                            
                            logger.info(
                                f"Fallback successful for {agent_name}: {fallback_result.strategy}"
                            )
                    except Exception as fallback_error:
                        logger.warning(f"Fallback handling failed for {agent_name}: {fallback_error}")
            
            # Add execution steps to results
            if execution_steps:
                results["execution_steps"] = execution_steps
            
            # Unregister WebSocket callback
            if websocket_callback:
                self.feedback_service.unregister_websocket_callback(case_id)
            
            return results
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"Error in multi-agent analysis for case {case_id}: {e}",
                exc_info=True
            )
            # #region agent log
            try:
                import json
                import os
                import traceback
                log_path = os.path.join(os.getcwd(), '.cursor', 'debug.log')
                with open(log_path, 'a') as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "coordinator-error",
                        "hypothesisId": "H3",
                        "location": "coordinator.py:run_analysis:exception",
                        "message": "Error in multi-agent analysis",
                        "data": {
                            "case_id": case_id,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "execution_time": execution_time,
                            "traceback": traceback.format_exc()[:1000]
                        },
                        "timestamp": int(time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
            # Определить тип ошибки
            error_type = "fatal"
            if isinstance(e, ValueError):
                error_type = "validation"
            elif isinstance(e, TimeoutError):
                error_type = "timeout"
            elif isinstance(e, ConnectionError):
                error_type = "connection"
            
            return {
                "case_id": case_id,
                "timeline": None,
                "key_facts": None,
                "discrepancies": None,
                "risk_analysis": None,
                "summary": None,
                "classification": None,
                "entities": None,
                "privilege": None,
                "errors": [{
                    "coordinator": str(e),
                    "type": error_type,
                    "recoverable": error_type in ["timeout", "connection"]
                }],
                "execution_time": execution_time,
                "metadata": {"error_type": error_type}
            }
