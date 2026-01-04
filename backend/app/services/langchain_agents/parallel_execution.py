"""Parallel Execution Module - Phase 1.1 Implementation

This module provides LangGraph-native parallel execution patterns
to replace ThreadPoolExecutor-based parallelism.

Features:
- Fan-out/fan-in pattern using LangGraph Send
- Reducer for merging parallel agent results
- State-safe parallel execution
- Improved error handling
"""
from typing import Dict, Any, List, Optional, Callable, Sequence
from langgraph.types import Send
from app.services.langchain_agents.state import AnalysisState
from app.config import config
import logging
import time

logger = logging.getLogger(__name__)

# Agent timeout configuration (seconds)
AGENT_TIMEOUTS = {
    "document_classifier": 60,
    "timeline": 120,
    "key_facts": 120,
    "discrepancy": 180,
    "entity_extraction": 120,
    "risk": 180,
    "summary": 120,
}

# Default timeout
DEFAULT_AGENT_TIMEOUT = 120


def create_parallel_sends(
    state: AnalysisState,
    agent_names: List[str],
    target_node: str = "execute_agent"
) -> List[Send]:
    """
    Create Send objects for parallel agent execution using LangGraph fan-out.
    
    This replaces ThreadPoolExecutor with LangGraph's native Send API
    which handles parallelism at the graph level.
    
    Args:
        state: Current analysis state
        agent_names: List of agent names to execute
        target_node: Name of the node that executes agents
        
    Returns:
        List of Send objects for parallel execution
    """
    sends = []
    case_id = state.get("case_id", "unknown")
    
    for agent_name in agent_names:
        # Check if agent result already exists
        result_key = f"{agent_name}_result"
        if state.get(result_key) is not None:
            logger.debug(f"Skipping {agent_name} - result already exists")
            continue
        
        # Create state copy for this agent
        agent_state = dict(state)
        agent_state["current_agent"] = agent_name
        agent_state["agent_timeout"] = AGENT_TIMEOUTS.get(agent_name, DEFAULT_AGENT_TIMEOUT)
        
        # Create Send to target node
        send = Send(target_node, agent_state)
        sends.append(send)
        
        logger.debug(f"Created Send for {agent_name} agent (case {case_id})")
    
    logger.info(f"Created {len(sends)} parallel Sends for case {case_id}")
    return sends


def merge_parallel_results(
    states: Sequence[AnalysisState],
    base_state: Optional[AnalysisState] = None
) -> AnalysisState:
    """
    Reducer function to merge results from parallel agent executions.
    
    This is the fan-in part of the fan-out/fan-in pattern.
    
    Args:
        states: Sequence of states from parallel executions
        base_state: Optional base state to merge into
        
    Returns:
        Merged state with all agent results
    """
    if not states:
        return base_state or {}
    
    # Start with base state or first state
    if base_state:
        merged = dict(base_state)
    else:
        merged = dict(states[0])
    
    # Track what we've merged
    merged_agents = []
    all_errors = list(merged.get("errors", []))
    all_completed_steps = set(merged.get("completed_steps", []))
    merged_metadata = dict(merged.get("metadata", {}))
    
    # Process each state
    for state in states:
        if state is None:
            continue
        
        agent_name = state.get("current_agent")
        if agent_name:
            merged_agents.append(agent_name)
        
        # Merge agent result
        for key, value in state.items():
            if key.endswith("_result") and value is not None:
                merged[key] = value
        
        # Merge errors (deduplicate by agent name)
        if "errors" in state:
            existing_agents = {e.get("agent") for e in all_errors}
            for error in state["errors"]:
                if error.get("agent") not in existing_agents:
                    all_errors.append(error)
        
        # Merge completed steps
        if "completed_steps" in state:
            all_completed_steps.update(state["completed_steps"])
        
        # Merge metadata
        if "metadata" in state:
            merged_metadata.update(state["metadata"])
    
    # Apply merged collections
    merged["errors"] = all_errors
    merged["completed_steps"] = list(all_completed_steps)
    merged["metadata"] = merged_metadata
    
    logger.info(f"Merged results from {len(merged_agents)} parallel agents: {merged_agents}")
    return merged


class ParallelAgentExecutor:
    """
    Executor for running agents in parallel using LangGraph patterns.
    
    This class provides a higher-level interface for parallel execution
    with built-in error handling and result merging.
    """
    
    def __init__(
        self,
        agent_registry: Dict[str, Callable],
        max_parallel: Optional[int] = None
    ):
        """
        Initialize the parallel executor.
        
        Args:
            agent_registry: Dictionary mapping agent names to functions
            max_parallel: Maximum number of parallel agents (default from config)
        """
        self.agent_registry = agent_registry
        self.max_parallel = max_parallel or config.AGENT_MAX_PARALLEL
    
    def prepare_sends(
        self,
        state: AnalysisState,
        requested_agents: List[str]
    ) -> List[Send]:
        """
        Prepare Send objects for requested agents.
        
        Args:
            state: Current state
            requested_agents: List of agent names to run
            
        Returns:
            List of Send objects
        """
        # Filter to available agents
        available = [
            name for name in requested_agents
            if name in self.agent_registry
        ]
        
        # Filter to not-yet-completed
        to_run = [
            name for name in available
            if state.get(f"{name}_result") is None
        ]
        
        # Limit to max_parallel
        if len(to_run) > self.max_parallel:
            logger.warning(
                f"Limiting parallel agents from {len(to_run)} to {self.max_parallel}"
            )
            to_run = to_run[:self.max_parallel]
        
        return create_parallel_sends(state, to_run, "execute_agent")
    
    def execute_agent(
        self,
        state: AnalysisState
    ) -> AnalysisState:
        """
        Execute a single agent (used as target for Send).
        
        Args:
            state: State with current_agent set
            
        Returns:
            Updated state with agent result
        """
        agent_name = state.get("current_agent")
        if not agent_name:
            logger.error("No current_agent in state")
            return state
        
        agent_func = self.agent_registry.get(agent_name)
        if not agent_func:
            logger.error(f"Agent function not found: {agent_name}")
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": f"Agent function not found: {agent_name}"
            })
            return new_state
        
        start_time = time.time()
        timeout = state.get("agent_timeout", DEFAULT_AGENT_TIMEOUT)
        
        try:
            logger.info(f"Executing {agent_name} agent (timeout={timeout}s)")
            result_state = agent_func(state)
            
            duration = time.time() - start_time
            logger.info(f"Completed {agent_name} agent in {duration:.2f}s")
            
            return result_state
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Error in {agent_name} agent after {duration:.2f}s: {e}",
                exc_info=True
            )
            
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": str(e),
                "duration": duration
            })
            return new_state


def create_fanout_node(
    agent_registry: Dict[str, Callable],
    independent_agents: List[str]
) -> Callable:
    """
    Create a fan-out node that dispatches to independent agents.
    
    This function creates a node that can be added to a LangGraph
    to dispatch multiple agents in parallel using Send.
    
    Args:
        agent_registry: Dictionary mapping agent names to functions
        independent_agents: List of agent names that can run in parallel
        
    Returns:
        Function that creates Send objects for parallel execution
    """
    def fanout_node(state: AnalysisState) -> List[Send]:
        """Dispatch independent agents in parallel."""
        analysis_types = state.get("analysis_types", [])
        
        # Filter to requested independent agents
        agents_to_run = [
            name for name in independent_agents
            if name in analysis_types and name in agent_registry
        ]
        
        # Filter to not-yet-completed
        agents_to_run = [
            name for name in agents_to_run
            if state.get(f"{name}_result") is None
        ]
        
        if not agents_to_run:
            # No agents to run - return empty list (no Sends)
            logger.info("No independent agents to dispatch")
            return []
        
        return create_parallel_sends(state, agents_to_run, "execute_single_agent")
    
    return fanout_node


def create_reducer_node() -> Callable:
    """
    Create a reducer node that merges parallel results.
    
    This function creates a node that collects results from
    parallel agent executions and merges them.
    
    Returns:
        Function that merges parallel states
    """
    def reducer_node(states: Sequence[AnalysisState]) -> AnalysisState:
        """Merge results from parallel agents."""
        return merge_parallel_results(states)
    
    return reducer_node


# Utility function for gradual migration
def should_use_langgraph_parallel() -> bool:
    """
    Check if LangGraph parallel execution should be used.
    
    This allows gradual migration from ThreadPoolExecutor.
    Controlled by environment variable.
    
    Returns:
        True if LangGraph parallel should be used
    """
    import os
    return os.getenv("USE_LANGGRAPH_PARALLEL", "true").lower() == "true"

