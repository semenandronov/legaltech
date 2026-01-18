"""Tool Registry - реестр инструментов для Workflow"""
from typing import Dict, Any, Optional, Callable, List, Type
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
import logging
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result of tool execution"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    output_summary: str = ""
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    tokens_used: int = 0


class BaseTool(ABC):
    """Base class for workflow tools"""
    
    name: str = "base_tool"
    display_name: str = "Base Tool"
    description: str = ""
    
    def __init__(self, db: Session):
        """Initialize tool with database session"""
        self.db = db
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute the tool with given parameters
        
        Args:
            params: Tool-specific parameters
            context: Execution context (user_id, case_id, previous_results, etc.)
            
        Returns:
            ToolResult with execution results
        """
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """
        Validate tool parameters
        
        Args:
            params: Parameters to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        return []


class ToolRegistry:
    """
    Registry for workflow tools.
    
    Manages available tools and provides tool lookup and execution.
    """
    
    def __init__(self, db: Session):
        """Initialize tool registry"""
        self.db = db
        self._tools: Dict[str, Type[BaseTool]] = {}
        self._tool_instances: Dict[str, BaseTool] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default tools"""
        from app.services.workflows.tools.tabular_review_tool import TabularReviewTool
        from app.services.workflows.tools.rag_tool import RAGTool
        from app.services.workflows.tools.web_search_tool import WebSearchTool
        from app.services.workflows.tools.playbook_tool import PlaybookCheckTool
        from app.services.workflows.tools.summarize_tool import SummarizeTool
        from app.services.workflows.tools.extract_entities_tool import ExtractEntitiesTool
        from app.services.workflows.tools.legal_db_tool import LegalDBTool
        from app.services.workflows.tools.document_draft_tool import DocumentDraftTool
        
        self.register(TabularReviewTool)
        self.register(RAGTool)
        self.register(WebSearchTool)
        self.register(PlaybookCheckTool)
        self.register(SummarizeTool)
        self.register(ExtractEntitiesTool)
        self.register(LegalDBTool)
        self.register(DocumentDraftTool)
        
        logger.info(f"ToolRegistry: Registered {len(self._tools)} tools")
    
    def register(self, tool_class: Type[BaseTool]):
        """
        Register a tool class
        
        Args:
            tool_class: Tool class to register
        """
        self._tools[tool_class.name] = tool_class
        logger.debug(f"Registered tool: {tool_class.name}")
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool instance by name
        
        Args:
            name: Tool name
            
        Returns:
            Tool instance or None
        """
        if name not in self._tool_instances:
            tool_class = self._tools.get(name)
            if tool_class:
                self._tool_instances[name] = tool_class(self.db)
        
        return self._tool_instances.get(name)
    
    def list_tools(self) -> List[Dict[str, str]]:
        """
        List all registered tools
        
        Returns:
            List of tool info dictionaries
        """
        result = []
        for name, tool_class in self._tools.items():
            result.append({
                "name": name,
                "display_name": tool_class.display_name,
                "description": tool_class.description
            })
        return result
    
    def is_available(self, name: str) -> bool:
        """Check if a tool is available"""
        return name in self._tools
    
    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ToolResult:
        """
        Execute a tool
        
        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            context: Execution context
            
        Returns:
            ToolResult
        """
        tool = self.get_tool(tool_name)
        
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found"
            )
        
        # Validate params
        errors = tool.validate_params(params)
        if errors:
            return ToolResult(
                success=False,
                error=f"Invalid parameters: {', '.join(errors)}"
            )
        
        try:
            logger.info(f"Executing tool: {tool_name}")
            result = await tool.execute(params, context)
            logger.info(f"Tool {tool_name} completed: success={result.success}")
            return result
            
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )


# Create __init__ for tools package
TOOLS_INIT = '''"""Workflow tools"""
from app.services.workflows.tools.tabular_review_tool import TabularReviewTool
from app.services.workflows.tools.rag_tool import RAGTool
from app.services.workflows.tools.web_search_tool import WebSearchTool
from app.services.workflows.tools.playbook_tool import PlaybookCheckTool
from app.services.workflows.tools.summarize_tool import SummarizeTool
from app.services.workflows.tools.extract_entities_tool import ExtractEntitiesTool

__all__ = [
    "TabularReviewTool",
    "RAGTool", 
    "WebSearchTool",
    "PlaybookCheckTool",
    "SummarizeTool",
    "ExtractEntitiesTool",
]
'''

