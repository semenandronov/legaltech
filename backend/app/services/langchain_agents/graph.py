"""LangGraph graph for multi-agent analysis system"""
from typing import List, Sequence
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send
from app.services.langchain_agents.state import AnalysisState
from app.config import config
# Runtime middleware для инжекции ToolRuntime в tools (см. runtime_middleware.py)
# TODO: Интегрировать runtime middleware в agent nodes при обновлении для использования state.context
from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent
from app.services.langchain_agents.timeline_node import timeline_agent_node
from app.services.langchain_agents.key_facts_node import key_facts_agent_node
from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
from app.services.langchain_agents.risk_node import risk_agent_node
from app.services.langchain_agents.summary_node import summary_agent_node
from app.services.langchain_agents.document_classifier_node import document_classifier_agent_node
from app.services.langchain_agents.entity_extraction_node import entity_extraction_agent_node
from app.services.langchain_agents.privilege_check_node import privilege_check_agent_node
from app.services.langchain_agents.relationship_node import relationship_agent_node
from app.services.langchain_agents.evaluation_node import evaluation_node
from app.services.langchain_agents.adaptation_engine import adaptation_node
from app.services.langchain_agents.human_feedback import get_feedback_service
from app.services.langchain_agents.subagent_manager import SubAgentManager
from app.services.langchain_agents.understand_node import understand_node
from app.services.langchain_agents.plan_node import plan_node
from app.services.langchain_agents.deliver_node import deliver_node
from app.services.langchain_agents.deep_analysis_node import deep_analysis_node
from app.services.langchain_agents.file_system_context import FileSystemContext
from app.services.langchain_agents.file_system_tools import initialize_file_system_tools, get_file_system_tools
from app.services.langchain_agents.graph_optimizer import optimize_route_function
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
# ThreadPoolExecutor removed - using LangGraph Send/Command instead
# threading removed - using LangGraph Send/Command instead
import logging
import os
import time

logger = logging.getLogger(__name__)


def create_analysis_graph(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    use_legora_workflow: bool = True
) -> StateGraph:
    """
    Create LangGraph for multi-agent analysis
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Compiled LangGraph graph
    """
    # Initialize File System Context (workspace base path)
    # Use UPLOAD_DIR as base or default to ./workspaces
    workspace_base_path = os.getenv("WORKSPACE_BASE_PATH", os.path.join(os.getcwd(), "workspaces"))
    os.makedirs(workspace_base_path, exist_ok=True)
    
    # FileSystemContext will be created per case in nodes
    # We pass base_path to nodes so they can create context when needed
    
    # Initialize SubAgent Manager for the graph (file_system_context will be set per case)
    subagent_manager = None
    try:
        subagent_manager = SubAgentManager(
            rag_service=rag_service,
            document_processor=document_processor,
            file_system_context=None  # Will be set per case in init_workspace_node
        )
        logger.info("✅ SubAgent Manager initialized in graph")
    except Exception as e:
        logger.warning(f"Failed to initialize SubAgentManager in graph: {e}")
    
    # Create wrapper functions that pass db and services
    def timeline_node(state: AnalysisState) -> AnalysisState:
        return timeline_agent_node(state, db, rag_service, document_processor)
    
    def key_facts_node(state: AnalysisState) -> AnalysisState:
        return key_facts_agent_node(state, db, rag_service, document_processor)
    
    def discrepancy_node(state: AnalysisState) -> AnalysisState:
        return discrepancy_agent_node(state, db, rag_service, document_processor)
    
    def risk_node(state: AnalysisState) -> AnalysisState:
        return risk_agent_node(state, db, rag_service, document_processor)
    
    def summary_node(state: AnalysisState) -> AnalysisState:
        return summary_agent_node(state, db, rag_service, document_processor)
    
    def document_classifier_node(state: AnalysisState) -> AnalysisState:
        return document_classifier_agent_node(state, db, rag_service, document_processor)
    
    def entity_extraction_node(state: AnalysisState) -> AnalysisState:
        return entity_extraction_agent_node(state, db, rag_service, document_processor)
    
    def privilege_check_node(state: AnalysisState) -> AnalysisState:
        return privilege_check_agent_node(state, db, rag_service, document_processor)
    
    def relationship_node(state: AnalysisState) -> AnalysisState:
        return relationship_agent_node(state, db, rag_service, document_processor)
    
    def understand_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for understand node with services"""
        return understand_node(state, db, rag_service, document_processor)
    
    def plan_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for plan node with services"""
        return plan_node(state, db, rag_service, document_processor)
    
    def deliver_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for deliver node with services"""
        return deliver_node(state, db, rag_service, document_processor)
    
    def deep_analysis_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for deep analysis node with services"""
        return deep_analysis_node(state, db, rag_service, document_processor)
    
    def supervisor_node(state: AnalysisState) -> AnalysisState:
        """Supervisor node - routes to appropriate agent"""
        # Supervisor doesn't modify state, just routes
        return state
    
    def evaluation_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for evaluation node with services"""
        return evaluation_node(state, db, rag_service, document_processor)
    
    def adaptation_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for adaptation node with services"""
        return adaptation_node(state, db, rag_service, document_processor)
    
    def init_workspace_node_wrapper(state: AnalysisState) -> AnalysisState:
        """
        Initialize workspace for file system context
        
        Creates FileSystemContext for the case and sets workspace_path in state
        """
        case_id = state.get("case_id", "unknown")
        new_state = dict(state)
        
        try:
            # Create FileSystemContext for this case
            file_system_context = FileSystemContext(workspace_base_path, case_id)
            workspace_path = file_system_context.get_workspace_path()
            
            # Set workspace_path in state
            new_state["workspace_path"] = workspace_path
            new_state["workspace_files"] = []
            
            # Initialize file system tools with context
            initialize_file_system_tools(file_system_context)
            
            # Update subagent_manager with file_system_context
            if subagent_manager:
                subagent_manager.file_system_context = file_system_context
            
            logger.info(f"[InitWorkspace] Workspace initialized: {workspace_path}")
        except Exception as e:
            logger.error(f"[InitWorkspace] Failed to initialize workspace: {e}", exc_info=True)
            # Continue without file system context
        
        return new_state
    
    def spawn_subagents_node(state: AnalysisState) -> AnalysisState:
        """
        Spawn subagents node - creates and executes subagents for subtasks
        
        This node handles execution of subtasks from AdvancedPlanningAgent
        using SubAgentManager.
        """
        if not subagent_manager:
            logger.warning("[SpawnSubagents] SubAgentManager not available, skipping")
            return state
        
        case_id = state.get("case_id", "unknown")
        logger.info(f"[SpawnSubagents] Starting subagent execution for case {case_id}")
        
        new_state = dict(state)
        
        # Initialize FileSystemContext if not already done
        if not subagent_manager.file_system_context:
            workspace_path = state.get("workspace_path")
            if workspace_path:
                # FileSystemContext already created in init_workspace_node
                try:
                    file_system_context = FileSystemContext(workspace_base_path, case_id)
                    subagent_manager.file_system_context = file_system_context
                    initialize_file_system_tools(file_system_context)
                except Exception as e:
                    logger.warning(f"[SpawnSubagents] Failed to create FileSystemContext: {e}")
        
        # Get subtasks from state (set by AdvancedPlanningAgent)
        subtasks = state.get("subtasks", [])
        if not subtasks:
            logger.info("[SpawnSubagents] No subtasks found, skipping")
            return new_state
        
        # Get context from state
        context = state.get("context", {})
        
        # Execute subagents
        subagent_results = []
        errors = list(state.get("errors", []))
        
        for subtask in subtasks:
            subtask_id = subtask.get("subtask_id")
            dependencies = subtask.get("dependencies", [])
            
            # Check if dependencies are satisfied
            if dependencies:
                # Check if all dependencies are completed
                all_deps_completed = True
                for dep_id in dependencies:
                    # Check if dependency result exists in state
                    dep_completed = False
                    for result in subagent_results:
                        if result.get("subtask_id") == dep_id:
                            dep_completed = True
                            break
                    
                    if not dep_completed:
                        all_deps_completed = False
                        break
                
                if not all_deps_completed:
                    logger.info(f"[SpawnSubagents] Subtask {subtask_id} waiting for dependencies: {dependencies}")
                    continue
            
            try:
                # Spawn subagent
                subagent = subagent_manager.spawn_subagent(
                    subtask=subtask,
                    context=context,
                    state=state
                )
                
                # Execute subagent with retry
                result = subagent.run(state, max_retries=2)
                
                # Store result
                subagent_results.append({
                    "subtask_id": subtask_id,
                    "agent_type": subtask.get("agent_type"),
                    "data": result,
                    "status": "completed"
                })
                
                logger.info(f"[SpawnSubagents] Subtask {subtask_id} completed successfully")
                
            except Exception as e:
                logger.error(f"[SpawnSubagents] Error executing subtask {subtask_id}: {e}", exc_info=True)
                errors.append({
                    "subtask_id": subtask_id,
                    "error": str(e)
                })
                subagent_results.append({
                    "subtask_id": subtask_id,
                    "agent_type": subtask.get("agent_type"),
                    "status": "failed",
                    "error": str(e)
                })
        
        # Reconcile results if we have multiple subagents
        if len(subagent_results) > 1:
            try:
                main_task = state.get("user_task", "Analysis task")
                reconciled = subagent_manager.reconcile_results(subagent_results, main_task)
                new_state["subagent_results"] = reconciled
                new_state["reconciled_summary"] = reconciled.get("summary", "")
                logger.info("[SpawnSubagents] Results reconciled successfully")
            except Exception as e:
                logger.error(f"[SpawnSubagents] Error reconciling results: {e}", exc_info=True)
                new_state["subagent_results"] = {"subtask_results": {r.get("subtask_id"): r for r in subagent_results}}
        else:
            new_state["subagent_results"] = {"subtask_results": {r.get("subtask_id"): r for r in subagent_results}}
        
        new_state["errors"] = errors
        new_state["subtasks_completed"] = len([r for r in subagent_results if r.get("status") == "completed"])
        
        logger.info(f"[SpawnSubagents] Completed {new_state['subtasks_completed']} subtasks for case {case_id}")
        return new_state
    
    def human_feedback_wait_node(state: AnalysisState) -> AnalysisState:
        """
        Human feedback wait node - checks if feedback has been received.
        If feedback received, integrates it into state for agent retry.
        If not, returns to supervisor to wait.
        Has timeout to prevent infinite loops.
        """
        case_id = state.get("case_id", "unknown")
        current_request = state.get("current_feedback_request")
        feedback_responses = state.get("feedback_responses", {})
        
        if not current_request:
            logger.warning(f"[HumanFeedback] No current feedback request for case {case_id}")
            new_state = dict(state)
            new_state["waiting_for_human"] = False
            return new_state
        
        request_id = current_request.get("request_id")
        
        # Check if response received
        if request_id in feedback_responses:
            response = feedback_responses[request_id]
            logger.info(f"[HumanFeedback] Response received for request {request_id}: {response[:100]}")
            
            # Update state with feedback
            new_state = dict(state)
            new_state["waiting_for_human"] = False
            new_state["current_feedback_request"] = None
            
            # Store feedback for agent to use in retry
            if "metadata" not in new_state:
                new_state["metadata"] = {}
            if "human_feedback" not in new_state["metadata"]:
                new_state["metadata"]["human_feedback"] = {}
            new_state["metadata"]["human_feedback"][request_id] = {
                "question": current_request.get("question_text"),
                "response": response,
                "agent_name": current_request.get("agent_name")
            }
            
            return new_state
        else:
            # Still waiting for response - but check timeout to prevent infinite loops
            # Track number of wait attempts
            from app.config import config
            human_feedback_attempts = state.get("human_feedback_attempts", 0)
            MAX_HUMAN_FEEDBACK_ATTEMPTS = config.HUMAN_FEEDBACK_MAX_ATTEMPTS
            FALLBACK_STRATEGY = config.HUMAN_FEEDBACK_FALLBACK_STRATEGY
            
            if human_feedback_attempts >= MAX_HUMAN_FEEDBACK_ATTEMPTS:
                logger.warning(
                    f"[HumanFeedback] Timeout waiting for response to request {request_id} "
                    f"after {human_feedback_attempts} attempts. Using fallback strategy: {FALLBACK_STRATEGY}"
                )
                # Apply fallback strategy
                new_state = dict(state)
                new_state["waiting_for_human"] = False
                new_state["current_feedback_request"] = None
                new_state["human_feedback_attempts"] = 0
                
                # Store fallback info in metadata
                if "metadata" not in new_state:
                    new_state["metadata"] = {}
                if "human_feedback_fallbacks" not in new_state["metadata"]:
                    new_state["metadata"]["human_feedback_fallbacks"] = []
                new_state["metadata"]["human_feedback_fallbacks"].append({
                    "request_id": request_id,
                    "attempts": human_feedback_attempts,
                    "strategy": FALLBACK_STRATEGY,
                    "timestamp": time.time()
                })
                
                # Note: "abort" strategy would require additional logic to stop execution
                # For now, "skip" and "retry" both continue execution
                return new_state
            else:
                # Increment attempt counter
                new_state = dict(state)
                new_state["human_feedback_attempts"] = human_feedback_attempts + 1
                logger.info(
                    f"[HumanFeedback] Still waiting for response to request {request_id} "
                    f"(attempt {new_state['human_feedback_attempts']}/{MAX_HUMAN_FEEDBACK_ATTEMPTS})"
                )
                return new_state
    
    def parallel_independent_agents_node(state: AnalysisState) -> List[Send]:
        """
        Execute independent agents in parallel using LangGraph Send/Command.
        
        Это заменяет ThreadPoolExecutor на нативный механизм LangGraph для параллельного выполнения.
        Independent agents: timeline, key_facts, discrepancy, entity_extraction, document_classifier
        
        Returns:
            List[Send] для параллельного выполнения агентов
        """
        from app.services.langchain_agents.parallel_execution_v2 import create_parallel_sends_v2
        
        case_id = state.get("case_id", "unknown")
        analysis_types = state.get("analysis_types", [])
        
        # Define independent agents that can run in parallel
        independent_agents = {
            "timeline": timeline_node,
            "key_facts": key_facts_node,
            "discrepancy": discrepancy_node,
            "entity_extraction": entity_extraction_node,
            "document_classifier": document_classifier_node,
        }
        
        # Filter to only agents that are requested and not yet completed
        agents_to_run = []
        for agent_name in independent_agents.keys():
            if agent_name in analysis_types:
                # Check if already completed (result or ref in Store)
                result_key = f"{agent_name}_result"
                ref_key = f"{agent_name}_ref"
                if state.get(result_key) is None and state.get(ref_key) is None:
                    agents_to_run.append(agent_name)
        
        if not agents_to_run:
            logger.info(f"[Parallel] No independent agents to run in parallel for case {case_id}")
            return []
        
        logger.info(f"[Parallel] Creating {len(agents_to_run)} parallel Sends for case {case_id}: {agents_to_run}")
        
        # Create Send objects for parallel execution
        sends = create_parallel_sends_v2(state, agents_to_run, independent_agents)
        
        return sends
    
    def execute_single_agent(state: AnalysisState) -> AnalysisState:
        """
        Execute a single agent (target for Send from parallel_independent_agents_node).
        
        Args:
            state: State with current_agent set
        
        Returns:
            Updated state with agent result
        """
        from app.services.langchain_agents.parallel_execution_v2 import AGENT_TIMEOUTS, DEFAULT_AGENT_TIMEOUT
        import time
        
        agent_name = state.get("current_agent")
        if not agent_name:
            logger.error("No current_agent in state for execute_single_agent")
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": "unknown",
                "error": "No current_agent specified"
            })
            return new_state
        
        case_id = state.get("case_id", "unknown")
        
        # Get agent function from registry
        agent_registry = {
            "timeline": timeline_node,
            "key_facts": key_facts_node,
            "discrepancy": discrepancy_node,
            "entity_extraction": entity_extraction_node,
            "document_classifier": document_classifier_node,
        }
        
        agent_func = agent_registry.get(agent_name)
        if not agent_func:
            logger.error(f"Agent function not found: {agent_name}")
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": f"Agent function not found: {agent_name}"
            })
            return new_state
        
        # Execute agent with timeout
        start_time = time.time()
        timeout = state.get("agent_timeout", AGENT_TIMEOUTS.get(agent_name, DEFAULT_AGENT_TIMEOUT))
        
        try:
            logger.info(f"[Parallel] Executing {agent_name} agent (timeout={timeout}s, case: {case_id})")
            result_state = agent_func(state)
            
            duration = time.time() - start_time
            logger.info(f"[Parallel] Completed {agent_name} agent in {duration:.2f}s (case: {case_id})")
            
            return result_state
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"[Parallel] Error in {agent_name} agent after {duration:.2f}s (case: {case_id}): {e}",
                exc_info=True
            )
            
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": str(e),
                "duration": duration
            })
            return new_state
    
    def merge_parallel_results_node(states: List[AnalysisState]) -> AnalysisState:
        """
        Reducer node для слияния результатов параллельных агентов.
        
        Args:
            states: Последовательность состояний из параллельных выполнений
        
        Returns:
            Объединенное состояние со всеми результатами агентов
        """
        from app.services.langchain_agents.parallel_execution_v2 import merge_parallel_results_v2
        
        if not states:
            logger.warning("merge_parallel_results_node called with empty states")
            return {}
        
        # Использовать первое состояние как базовое
        base_state = states[0] if states else {}
        
        # Объединить все состояния
        merged = merge_parallel_results_v2(states, base_state)
        
        case_id = merged.get("case_id", "unknown")
        logger.info(f"[Parallel] Merged {len(states)} parallel agent results for case {case_id}")
        
        return merged
    
    # ThreadPoolExecutor code removed - using LangGraph Send/Command instead
    
    # Create the graph
    graph = StateGraph(AnalysisState)
    
    # Add init_workspace node (always first to initialize file system context)
    graph.add_node("init_workspace", init_workspace_node_wrapper)
    
    # Add LEGORA workflow nodes if enabled
    if use_legora_workflow:
        graph.add_node("understand", understand_wrapper)
        graph.add_node("plan", plan_wrapper)
        graph.add_node("deliver", deliver_wrapper)
        graph.add_node("deep_analysis", deep_analysis_wrapper)
        logger.info("✅ LEGORA workflow nodes added (understand, plan, deliver, deep_analysis)")
    
    # Add nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("timeline", timeline_node)
    graph.add_node("key_facts", key_facts_node)
    graph.add_node("discrepancy", discrepancy_node)
    graph.add_node("risk", risk_node)
    graph.add_node("summary", summary_node)
    graph.add_node("document_classifier", document_classifier_node)
    graph.add_node("entity_extraction", entity_extraction_node)
    graph.add_node("privilege_check", privilege_check_node)
    graph.add_node("relationship", relationship_node)
    graph.add_node("evaluation", evaluation_wrapper)
    graph.add_node("adaptation", adaptation_wrapper)
    # Add parallel execution nodes (using LangGraph Send/Command)
    graph.add_node("parallel_independent", parallel_independent_agents_node)
    graph.add_node("execute_single_agent", execute_single_agent)
    graph.add_node("merge_parallel_results", merge_parallel_results_node)
    graph.add_node("spawn_subagents", spawn_subagents_node)
    # Note: human_feedback_wait_node removed - using LangGraph interrupts instead
    
    # Add edges from START
    # Always start with init_workspace
    graph.add_edge(START, "init_workspace")
    
    if use_legora_workflow:
        # LEGORA workflow: init_workspace → understand → plan → supervisor
        graph.add_edge("init_workspace", "understand")
        
        # Conditional routing from understand to plan (skip plan for simple tasks)
        def route_after_understand(state: AnalysisState) -> str:
            """Route after understand: plan or supervisor"""
            understanding_result = state.get("understanding_result", {})
            needs_planning = understanding_result.get("needs_planning", True)
            if needs_planning:
                return "plan"
            else:
                # For simple tasks, skip plan and go directly to supervisor
                logger.info("[Graph] Simple task detected, skipping plan phase")
                return "supervisor"
        
        # Optimize route_after_understand with caching
        optimized_route_after_understand = optimize_route_function(
            route_after_understand,
            enable_cache=True,
            enable_priorities=False  # This route doesn't need priorities
        )
        
        graph.add_conditional_edges(
            "understand",
            optimized_route_after_understand,
            {
                "plan": "plan",
                "supervisor": "supervisor"
            }
        )
        
        # Plan always goes to supervisor
        graph.add_edge("plan", "supervisor")
    else:
        # Legacy workflow: init_workspace → supervisor
        graph.add_edge("init_workspace", "supervisor")
    
    # Add conditional edges from supervisor
    supervisor_routes = {
            "timeline": "timeline",
            "key_facts": "key_facts",
            "discrepancy": "discrepancy",
            "risk": "risk",
            "summary": "summary",
            "document_classifier": "document_classifier",
            "entity_extraction": "entity_extraction",
            "privilege_check": "privilege_check",
            "relationship": "relationship",
            "parallel_independent": "parallel_independent",
            "spawn_subagents": "spawn_subagents",
            # Note: human_feedback_wait removed - using LangGraph interrupts instead
            "end": END,
            "supervisor": "supervisor"  # Wait if dependencies not ready
        }
    
    # Add deep_analysis route if LEGORA workflow is enabled
    if use_legora_workflow:
        supervisor_routes["deep_analysis"] = "deep_analysis"
    
    # Optimize route_to_agent function with caching and priorities
    # Note: route_to_agent now supports Command-based routing (LangGraph 1.0+)
    # If route_to_agent returns Command, LangGraph uses Command.goto for routing
    # and Command.update for state updates automatically
    optimized_route_to_agent = optimize_route_function(
        route_to_agent,
        enable_cache=True,
        enable_priorities=True
    )
    
    # add_conditional_edges supports both str and Command return types
    # If function returns Command, Command.goto must be a key in supervisor_routes
    graph.add_conditional_edges(
        "supervisor",
        optimized_route_to_agent,
        supervisor_routes
    )
    
    # All agent nodes go to evaluation first, then supervisor
    graph.add_edge("timeline", "evaluation")
    graph.add_edge("key_facts", "evaluation")
    graph.add_edge("discrepancy", "evaluation")
    graph.add_edge("risk", "evaluation")
    graph.add_edge("summary", "evaluation")
    graph.add_edge("document_classifier", "evaluation")
    graph.add_edge("entity_extraction", "evaluation")
    graph.add_edge("privilege_check", "evaluation")
    graph.add_edge("relationship", "evaluation")
    
    # Deep analysis node also goes to evaluation
    if use_legora_workflow:
        graph.add_edge("deep_analysis", "evaluation")
    
    # Parallel execution flow using LangGraph Send/Command:
    # parallel_independent returns List[Send] → automatically fans out to execute_single_agent
    # execute_single_agent results are automatically collected and passed to merge_parallel_results
    # Note: In LangGraph, when a node returns List[Send], the graph automatically:
    # 1. Executes all Sends in parallel
    # 2. Collects results
    # 3. Passes them to the next node as Sequence[AnalysisState]
    # So merge_parallel_results will receive Sequence[AnalysisState] from execute_single_agent
    graph.add_edge("execute_single_agent", "merge_parallel_results")
    graph.add_edge("merge_parallel_results", "evaluation")
    
    # Note: parallel_independent doesn't need explicit edge - it returns List[Send]
    # which automatically creates fan-out to execute_single_agent
    
    # Spawn subagents node goes to evaluation
    graph.add_edge("spawn_subagents", "evaluation")
    
    # Simplified evaluation routing
    def route_after_evaluation(state: AnalysisState) -> str:
        """Route after evaluation: adaptation, deliver, or supervisor"""
        needs_adaptation = state.get("needs_replanning", False) or \
                          state.get("evaluation_result", {}).get("needs_adaptation", False)
        
        if needs_adaptation:
            logger.info(f"[Graph] Routing to adaptation for case {state.get('case_id', 'unknown')}")
            return "adaptation"
        
        # If LEGORA workflow enabled and work complete, go to deliver
        if use_legora_workflow:
            # Check if supervisor finished (all requested types completed)
            analysis_types = set(state.get("analysis_types", []))
            completed = {
                "timeline" if state.get("timeline_result") else None,
                "key_facts" if state.get("key_facts_result") else None,
                "discrepancy" if state.get("discrepancy_result") else None,
                "risk" if state.get("risk_result") else None,
                "summary" if state.get("summary_result") else None,
                "document_classifier" if state.get("classification_result") else None,
                "entity_extraction" if state.get("entities_result") else None,
                "privilege_check" if state.get("privilege_result") else None,
                "relationship" if state.get("relationship_result") else None,
            }
            completed.discard(None)
            
            if analysis_types.issubset(completed):
                logger.info(f"[Graph] Routing to deliver for case {state.get('case_id', 'unknown')}")
                return "deliver"
        
        return "supervisor"
    
    if use_legora_workflow:
        graph.add_conditional_edges(
            "evaluation",
            route_after_evaluation,
            {
                "adaptation": "adaptation",
                "deliver": "deliver",
                "supervisor": "supervisor"
            }
        )
        
        # Deliver goes to END
        graph.add_edge("deliver", END)
    else:
        graph.add_conditional_edges(
            "evaluation",
            route_after_evaluation,
            {
                "adaptation": "adaptation",
                "supervisor": "supervisor"
            }
        )
    
    # Note: Human feedback is now handled via LangGraph interrupts
    # Interrupts pause execution automatically, coordinator handles resume
    
    # Adaptation node returns to supervisor for replanning
    graph.add_edge("adaptation", "supervisor")
    
    # Compile graph with checkpointer
    # Try PostgresSaver first (for production persistence), fallback to MemorySaver
    # Use optimized checkpointer with connection pooling
    checkpointer = None
    try:
        from app.utils.checkpointer_setup import get_checkpointer_instance
        
        # Get or create checkpointer instance (with connection pooling)
        checkpointer = get_checkpointer_instance()
        
        if checkpointer is None:
            # Fallback to direct initialization if get_checkpointer_instance failed
            from langgraph.checkpoint.postgres import PostgresSaver
            from app.config import config
            
            db_url = config.DATABASE_URL
            # Remove psycopg driver prefix if present (PostgresSaver expects standard postgresql://)
            if db_url.startswith("postgresql+psycopg://"):
                db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
            elif db_url.startswith("postgresql+psycopg2://"):
                db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
            
            # Use from_conn_string() which returns a context manager
            # CRITICAL: We MUST use 'with' statement to properly initialize PostgresSaver
            if hasattr(PostgresSaver, 'from_conn_string'):
                conn_manager = PostgresSaver.from_conn_string(db_url)
                
                # Check if it's a context manager by checking for __enter__ and __exit__
                is_context_manager = hasattr(conn_manager, "__enter__") and hasattr(conn_manager, "__exit__")
                
                if is_context_manager:
                    # CRITICAL: Use __enter__() to properly initialize PostgresSaver
                    # The context manager sets up the connection properly
                    checkpointer = conn_manager.__enter__()
                    
                    # Verify the checkpointer has a proper connection object, not a string
                    if hasattr(checkpointer, 'conn'):
                        if isinstance(checkpointer.conn, str):
                            logger.error(f"❌ PostgresSaver.conn is still a string after __enter__()")
                            raise ValueError("PostgresSaver.conn is a string, not a connection object")
                    
                    logger.info("✅ Created PostgresSaver using from_conn_string() context manager (fallback)")
                else:
                    # from_conn_string() returned PostgresSaver directly (older version)
                    checkpointer = conn_manager
                    logger.info("✅ Created PostgresSaver with from_conn_string (fallback, direct)")
            else:
                # Fallback: try direct constructor
                try:
                    checkpointer = PostgresSaver(db_url)
                    logger.info("✅ Created PostgresSaver using direct constructor (fallback)")
                except (TypeError, ValueError) as direct_error:
                    raise ValueError(f"PostgresSaver initialization failed: {direct_error}")
            
            # Setup tables if they don't exist (idempotent)
            try:
                if hasattr(checkpointer, 'setup') and callable(checkpointer.setup):
                    with checkpointer.setup():
                        pass  # Tables are created when entering the context
                    logger.debug("Checkpointer tables setup completed")
            except Exception as setup_error:
                logger.debug(f"Checkpointer setup note: {setup_error}")
            
            logger.info("✅ Using PostgreSQL checkpointer for state persistence")
        else:
            logger.info("✅ Using PostgreSQL checkpointer with connection pooling")
    except ImportError as e:
        logger.warning(f"PostgresSaver not available (langgraph-checkpoint-postgres not installed): {e}, using MemorySaver")
        checkpointer = MemorySaver()
    except Exception as e:
        logger.warning(f"Failed to initialize PostgresSaver ({e}), using MemorySaver as fallback")
        checkpointer = MemorySaver()
    
    # Create Store for long-term memory (optional, falls back gracefully if unavailable)
    store = None
    try:
        from app.services.langchain_agents.store_integration import create_store_instance
        store = create_store_instance()
        if store:
            logger.info("✅ LangGraph Store initialized for long-term memory")
        else:
            logger.debug("LangGraph Store not available, continuing without Store")
    except Exception as e:
        logger.debug(f"Store initialization skipped: {e}")
        store = None
    
    # Wrap PostgresSaver with async wrapper for astream_events support
    from app.utils.async_checkpointer_wrapper import wrap_postgres_saver_if_needed
    checkpointer = wrap_postgres_saver_if_needed(checkpointer)
    
    # Compile graph with checkpointer and optional store
    if store:
        compiled_graph = graph.compile(checkpointer=checkpointer, store=store)
    else:
        compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("Created LangGraph for multi-agent analysis")
    
    return compiled_graph
