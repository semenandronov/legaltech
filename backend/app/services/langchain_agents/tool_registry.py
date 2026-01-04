"""Tool Registry - Phase 5.3 Implementation

This module provides a centralized registry for tool management
with metadata, scoping, and governance.

Features:
- Tool registry with metadata
- Per-agent tool scoping
- Dynamic tool enabling
- Cost estimation
- Usage auditing
"""
from typing import Dict, Any, Optional, List, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ToolSensitivity(str, Enum):
    """Sensitivity level of a tool."""
    LOW = "low"  # Safe for all agents
    MEDIUM = "medium"  # Requires caution
    HIGH = "high"  # Restricted access
    CRITICAL = "critical"  # Supervisor only


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""
    
    name: str
    description: str
    sensitivity: ToolSensitivity = ToolSensitivity.LOW
    cost_estimate: float = 0.0  # Estimated cost per call
    allowed_agents: Set[str] = field(default_factory=set)  # Empty = all agents
    denied_agents: Set[str] = field(default_factory=set)  # Explicitly denied
    requires_approval: bool = False  # Requires human approval
    rate_limit: Optional[int] = None  # Max calls per minute
    schema: Optional[Dict[str, Any]] = None  # Input schema
    tags: List[str] = field(default_factory=list)
    
    # Usage tracking
    call_count: int = 0
    total_cost: float = 0.0
    
    def is_allowed_for(self, agent_name: str) -> bool:
        """Check if tool is allowed for agent."""
        if agent_name in self.denied_agents:
            return False
        if self.allowed_agents and agent_name not in self.allowed_agents:
            return False
        return True
    
    def record_usage(self, cost: float = 0.0):
        """Record tool usage."""
        self.call_count += 1
        self.total_cost += cost or self.cost_estimate
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "sensitivity": self.sensitivity.value,
            "cost_estimate": self.cost_estimate,
            "allowed_agents": list(self.allowed_agents),
            "denied_agents": list(self.denied_agents),
            "requires_approval": self.requires_approval,
            "rate_limit": self.rate_limit,
            "tags": self.tags,
            "call_count": self.call_count,
            "total_cost": self.total_cost
        }


class ToolRegistry:
    """
    Centralized registry for tool management.
    
    Provides:
    - Tool registration with metadata
    - Per-agent tool filtering
    - Usage tracking
    - Cost estimation
    """
    
    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, Callable] = {}
        self._metadata: Dict[str, ToolMetadata] = {}
        self._usage_log: List[Dict[str, Any]] = []
    
    def register(
        self,
        name: str,
        tool: Callable,
        description: str = "",
        sensitivity: ToolSensitivity = ToolSensitivity.LOW,
        cost_estimate: float = 0.0,
        allowed_agents: Optional[List[str]] = None,
        denied_agents: Optional[List[str]] = None,
        requires_approval: bool = False,
        rate_limit: Optional[int] = None,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ):
        """
        Register a tool with metadata.
        
        Args:
            name: Unique tool name
            tool: The tool callable
            description: Tool description
            sensitivity: Sensitivity level
            cost_estimate: Estimated cost per call
            allowed_agents: Agents allowed to use (None = all)
            denied_agents: Agents explicitly denied
            requires_approval: Whether human approval needed
            rate_limit: Max calls per minute
            schema: Input schema
            tags: Tags for categorization
        """
        self._tools[name] = tool
        self._metadata[name] = ToolMetadata(
            name=name,
            description=description,
            sensitivity=sensitivity,
            cost_estimate=cost_estimate,
            allowed_agents=set(allowed_agents) if allowed_agents else set(),
            denied_agents=set(denied_agents) if denied_agents else set(),
            requires_approval=requires_approval,
            rate_limit=rate_limit,
            schema=schema,
            tags=tags or []
        )
        
        logger.debug(f"Registered tool: {name} (sensitivity={sensitivity.value})")
    
    def unregister(self, name: str):
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            del self._metadata[name]
            logger.debug(f"Unregistered tool: {name}")
    
    def get_tool(self, name: str) -> Optional[Callable]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """Get tool metadata."""
        return self._metadata.get(name)
    
    def get_tools_for_agent(
        self,
        agent_name: str,
        max_sensitivity: ToolSensitivity = ToolSensitivity.HIGH,
        tags: Optional[List[str]] = None
    ) -> List[Callable]:
        """
        Get tools available for a specific agent.
        
        Args:
            agent_name: Name of the agent
            max_sensitivity: Maximum sensitivity level
            tags: Optional tag filter
            
        Returns:
            List of tools available to the agent
        """
        sensitivity_order = {
            ToolSensitivity.LOW: 0,
            ToolSensitivity.MEDIUM: 1,
            ToolSensitivity.HIGH: 2,
            ToolSensitivity.CRITICAL: 3
        }
        max_level = sensitivity_order.get(max_sensitivity, 2)
        
        tools = []
        for name, tool in self._tools.items():
            metadata = self._metadata.get(name)
            if not metadata:
                continue
            
            # Check agent permission
            if not metadata.is_allowed_for(agent_name):
                continue
            
            # Check sensitivity level
            tool_level = sensitivity_order.get(metadata.sensitivity, 0)
            if tool_level > max_level:
                continue
            
            # Check tags if specified
            if tags and not any(t in metadata.tags for t in tags):
                continue
            
            tools.append(tool)
        
        logger.debug(f"Agent {agent_name} has access to {len(tools)} tools")
        return tools
    
    def wrap_tool_call(
        self,
        tool_name: str,
        agent_name: str
    ) -> Callable:
        """
        Create a wrapped tool call with tracking and validation.
        
        Args:
            tool_name: Name of the tool
            agent_name: Name of the calling agent
            
        Returns:
            Wrapped tool callable
        """
        tool = self._tools.get(tool_name)
        metadata = self._metadata.get(tool_name)
        
        if not tool or not metadata:
            raise ValueError(f"Tool not found: {tool_name}")
        
        if not metadata.is_allowed_for(agent_name):
            raise PermissionError(f"Agent {agent_name} not allowed to use {tool_name}")
        
        def wrapped(*args, **kwargs):
            # Log usage
            self._usage_log.append({
                "tool": tool_name,
                "agent": agent_name,
                "timestamp": str(datetime.utcnow())
            })
            
            # Record usage
            metadata.record_usage()
            
            # Call tool
            return tool(*args, **kwargs)
        
        return wrapped
    
    def get_supervisor_tools(self) -> List[Callable]:
        """Get tools available only to supervisor."""
        return [
            tool for name, tool in self._tools.items()
            if self._metadata.get(name, ToolMetadata(name="")).sensitivity == ToolSensitivity.CRITICAL
        ]
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get tool usage statistics."""
        stats = {}
        for name, metadata in self._metadata.items():
            stats[name] = {
                "call_count": metadata.call_count,
                "total_cost": metadata.total_cost,
                "sensitivity": metadata.sensitivity.value
            }
        return stats
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with metadata."""
        return [
            metadata.to_dict()
            for metadata in self._metadata.values()
        ]


# Global registry instance
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        # Register default tools
        _register_default_tools(_registry)
    return _registry


def _register_default_tools(registry: ToolRegistry):
    """Register default tools in the registry."""
    from datetime import datetime
    
    # Import existing tools
    try:
        from app.services.langchain_agents.tools import (
            get_all_tools,
            search_documents,
            get_document_content,
            classify_document,
            validate_legal_reference,
        )
        
        # Register search tool
        if 'search_documents' in dir():
            registry.register(
                name="search_documents",
                tool=search_documents,
                description="Search documents in the case",
                sensitivity=ToolSensitivity.LOW,
                cost_estimate=0.01,
                tags=["search", "retrieval"]
            )
        
        # Register document tools
        if 'get_document_content' in dir():
            registry.register(
                name="get_document_content",
                tool=get_document_content,
                description="Get content of a specific document",
                sensitivity=ToolSensitivity.LOW,
                cost_estimate=0.01,
                tags=["document", "retrieval"]
            )
        
        # Register classification tool
        if 'classify_document' in dir():
            registry.register(
                name="classify_document",
                tool=classify_document,
                description="Classify document type",
                sensitivity=ToolSensitivity.LOW,
                cost_estimate=0.05,
                tags=["classification", "analysis"]
            )
        
        logger.info("Default tools registered in registry")
        
    except ImportError as e:
        logger.warning(f"Could not import default tools: {e}")


def scope_tools_for_agent(
    agent_name: str,
    max_sensitivity: ToolSensitivity = ToolSensitivity.MEDIUM
) -> List[Callable]:
    """
    Get scoped tools for a specific agent.
    
    Convenience function for tool scoping.
    
    Args:
        agent_name: Name of the agent
        max_sensitivity: Maximum allowed sensitivity
        
    Returns:
        List of tools available to the agent
    """
    registry = get_tool_registry()
    return registry.get_tools_for_agent(agent_name, max_sensitivity)

