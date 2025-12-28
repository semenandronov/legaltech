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

logger = logging.getLogger(__name__)


class AgentCoordinator:
    """Coordinator for managing multi-agent analysis workflow"""
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Initialize agent coordinator
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Create graph
        self.graph = create_analysis_graph(db, rag_service, document_processor)
        
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
        websocket_callback: Optional[Any] = None
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
        start_time = time.time()
        planning_start_time = time.time()
        metrics_id = None
        
        try:
            logger.info(f"Starting multi-agent analysis for case {case_id}, types: {analysis_types}")
            
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
            initial_state = create_initial_state(
                case_id=case_id,
                analysis_types=analysis_types,
                metadata={"planning_used": user_task is not None and self.planning_agent is not None}
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
            
            for state in self.graph.stream(initial_state, thread_config):
                # Log progress
                node_name = list(state.keys())[0] if state else "unknown"
                logger.info(f"Graph execution: {node_name} completed")
                final_state = state[node_name] if state else None
            
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
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.create_task(
                                        self.learning_service.save_successful_pattern(
                                            case_id=case_id,
                                            agent_name=agent_name,
                                            pattern=pattern,
                                            outcome=outcome
                                        )
                                    )
                                else:
                                    loop.run_until_complete(
                                        self.learning_service.save_successful_pattern(
                                            case_id=case_id,
                                            agent_name=agent_name,
                                            pattern=pattern,
                                            outcome=outcome
                                        )
                                    )
                            except RuntimeError:
                                asyncio.run(
                                    self.learning_service.save_successful_pattern(
                                        case_id=case_id,
                                        agent_name=agent_name,
                                        pattern=pattern,
                                        outcome=outcome
                                    )
                                )
                            
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
            
            # Extract results and handle fallbacks for failed agents
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
                "evaluation_results": final_state.get("evaluation_result") if final_state else None
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
                "errors": [{"coordinator": str(e)}],
                "execution_time": execution_time,
                "metadata": {}
            }
