"""Tool selector for dynamically choosing tools for agent tasks"""
from typing import Dict, Any, List, Optional
from app.services.langchain_agents.tools import get_all_tools
from app.services.external_sources.source_router import SourceRouter
import logging

logger = logging.getLogger(__name__)


class ToolSelector:
    """
    Selects optimal tools for agent tasks based on:
    - Task requirements
    - Available tools
    - Context
    - Performance considerations
    """
    
    # Tool capabilities mapping
    TOOL_CAPABILITIES = {
        "retrieve_documents": {
            "description": "Поиск документов в базе дела",
            "use_cases": ["document_search", "context_retrieval", "information_extraction"],
            "performance": "fast",
            "cost": "low"
        },
        "web_search": {
            "description": "Поиск в интернете (case law, прецеденты)",
            "use_cases": ["case_law_search", "citation_verification", "external_research"],
            "performance": "medium",
            "cost": "medium"
        },
        "save_timeline": {
            "description": "Сохранение результатов timeline",
            "use_cases": ["result_storage"],
            "performance": "fast",
            "cost": "low"
        },
        "save_key_facts": {
            "description": "Сохранение результатов key_facts",
            "use_cases": ["result_storage"],
            "performance": "fast",
            "cost": "low"
        },
        "save_discrepancy": {
            "description": "Сохранение результатов discrepancy",
            "use_cases": ["result_storage"],
            "performance": "fast",
            "cost": "low"
        },
        "save_risk": {
            "description": "Сохранение результатов risk",
            "use_cases": ["result_storage"],
            "performance": "fast",
            "cost": "low"
        },
        "save_summary": {
            "description": "Сохранение результатов summary",
            "use_cases": ["result_storage"],
            "performance": "fast",
            "cost": "low"
        }
    }
    
    # Agent-to-tools mapping
    AGENT_TOOLS = {
        "timeline": ["retrieve_documents", "save_timeline"],
        "key_facts": ["retrieve_documents", "save_key_facts"],
        "discrepancy": ["retrieve_documents", "web_search", "save_discrepancy"],
        "risk": ["retrieve_documents", "save_risk"],
        "summary": ["retrieve_documents", "save_summary"],
        "entity_extraction": ["retrieve_documents"],
        "document_classifier": ["retrieve_documents"],
        "privilege_check": ["retrieve_documents"],
        "relationship": ["retrieve_documents"]
    }
    
    def __init__(self, source_router: Optional[SourceRouter] = None):
        """Initialize tool selector"""
        self.source_router = source_router
    
    def select_tools(
        self,
        task: str,
        context: Dict[str, Any],
        available_tools: Optional[List[str]] = None
    ) -> List[str]:
        """
        Selects optimal tools for a task
        
        Args:
            task: Task description
            context: Context including agent_name, case_id, etc.
            available_tools: List of available tool names (optional)
        
        Returns:
            List of selected tool names
        """
        agent_name = context.get("agent_name", "unknown")
        case_id = context.get("case_id")
        task_lower = task.lower()
        
        # Start with agent-specific tools
        selected = list(self.AGENT_TOOLS.get(agent_name, []))
        
        # Add tools based on task requirements
        if "case law" in task_lower or "прецедент" in task_lower or "суд" in task_lower:
            if "web_search" not in selected:
                selected.append("web_search")
        
        if "verify" in task_lower or "верифицировать" in task_lower or "проверить" in task_lower:
            if "web_search" not in selected:
                selected.append("web_search")
        
        # Always include retrieve_documents for document-based agents
        if agent_name in ["timeline", "key_facts", "discrepancy", "risk", "summary"]:
            if "retrieve_documents" not in selected:
                selected.insert(0, "retrieve_documents")
        
        # Filter by available tools if provided
        if available_tools:
            selected = [t for t in selected if t in available_tools]
        
        # Remove duplicates while preserving order
        seen = set()
        unique_selected = []
        for tool in selected:
            if tool not in seen:
                seen.add(tool)
                unique_selected.append(tool)
        
        logger.debug(f"Selected tools for {agent_name}: {unique_selected}")
        return unique_selected
    
    def select_sources(
        self,
        task: str,
        context: Dict[str, Any]
    ) -> List[str]:
        """
        Selects data sources for a task
        
        Args:
            task: Task description
            context: Context including agent_name, case_id, etc.
        
        Returns:
            List of source names (vault, web, etc.)
        """
        if not self.source_router:
            return ["vault"]  # Default to vault only
        
        agent_name = context.get("agent_name", "unknown")
        task_lower = task.lower()
        
        sources = ["vault"]  # Always include vault
        
        # Add external sources based on task
        if any(keyword in task_lower for keyword in ["case law", "прецедент", "суд", "закон", "статья"]):
            available_sources = self.source_router.get_enabled_sources()
            if "web" in available_sources:
                sources.append("web")
        
        return sources
    
    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Gets information about a tool"""
        return self.TOOL_CAPABILITIES.get(tool_name, {
            "description": "Unknown tool",
            "use_cases": [],
            "performance": "unknown",
            "cost": "unknown"
        })
    
    def optimize_tool_usage(
        self,
        tools: List[str],
        context: Dict[str, Any]
    ) -> List[str]:
        """
        Optimizes tool usage by removing redundant tools
        
        Args:
            tools: List of tool names
            context: Context for optimization
        
        Returns:
            Optimized list of tools
        """
        optimized = []
        
        # Remove redundant save tools (only one needed per agent)
        save_tools = [t for t in tools if t.startswith("save_")]
        if save_tools:
            # Keep only the one matching the agent
            agent_name = context.get("agent_name", "")
            agent_save_tool = f"save_{agent_name}"
            if agent_save_tool in save_tools:
                optimized.append(agent_save_tool)
            elif save_tools:
                optimized.append(save_tools[0])  # Keep first one
        
        # Add non-save tools
        non_save_tools = [t for t in tools if not t.startswith("save_")]
        optimized.extend(non_save_tools)
        
        return optimized

