"""Supervisor agent for LangGraph multi-agent system"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from app.services.langchain_agents.agent_factory import create_legal_agent
from langchain.tools import Tool
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.prompts import get_agent_prompt
import logging

logger = logging.getLogger(__name__)


def create_handoff_tool(agent_name: str) -> Tool:
    """Create a handoff tool for routing to a specific agent"""
    return Tool(
        name=f"handoff_to_{agent_name}",
        func=lambda x: f"Handing off to {agent_name} agent",
        description=f"Transfer control to the {agent_name} agent to handle this task"
    )


def create_supervisor_agent() -> Any:
    """
    Create supervisor agent that routes tasks to specialized agents
    
    Returns:
        Supervisor agent instance
    """
    # Create handoff tools for each agent
    handoff_tools = [
        create_handoff_tool("timeline"),
        create_handoff_tool("key_facts"),
        create_handoff_tool("discrepancy"),
        create_handoff_tool("risk"),
        create_handoff_tool("summary"),
    ]
    
    # Initialize LLM
    llm = ChatOpenAI(
        model=config.OPENROUTER_MODEL,
        openai_api_key=config.OPENROUTER_API_KEY,
        openai_api_base=config.OPENROUTER_BASE_URL,
        temperature=0.1,  # Low temperature for consistent routing decisions
        max_tokens=500
    )
    
    # Get supervisor prompt
    prompt = get_agent_prompt("supervisor")
    
    # Create supervisor agent
    supervisor = create_legal_agent(llm, handoff_tools, system_prompt=prompt)
    
    return supervisor


def route_to_agent(state: AnalysisState) -> str:
    """
    Route function that determines which agent should handle the next task
    
    Args:
        state: Current graph state
    
    Returns:
        Name of the next agent to execute, or "end" if done
    """
    analysis_types = state.get("analysis_types", [])
    requested_types = set(analysis_types)
    
    # Check what's already done
    completed = set()
    if state.get("timeline_result"):
        completed.add("timeline")
    if state.get("key_facts_result"):
        completed.add("key_facts")
    if state.get("discrepancy_result"):
        completed.add("discrepancy")
    if state.get("risk_result"):
        completed.add("risk")
    if state.get("summary_result"):
        completed.add("summary")
    
    # Check dependencies
    discrepancy_ready = state.get("discrepancy_result") is not None
    key_facts_ready = state.get("key_facts_result") is not None
    
    # Determine next agent
    # Independent agents can run in parallel
    if "timeline" in requested_types and "timeline" not in completed:
        return "timeline"
    if "key_facts" in requested_types and "key_facts" not in completed:
        return "key_facts"
    if "discrepancy" in requested_types and "discrepancy" not in completed:
        return "discrepancy"
    
    # Dependent agents
    if "risk" in requested_types and "risk" not in completed and discrepancy_ready:
        return "risk"
    if "summary" in requested_types and "summary" not in completed and key_facts_ready:
        return "summary"
    
    # All done
    if requested_types.issubset(completed):
        return "end"
    
    # If dependencies not ready, wait (return to supervisor)
    return "supervisor"
