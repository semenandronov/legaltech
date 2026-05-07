"""Tool Registry - реестр инструментов для Workflow"""
from typing import Dict, Any, Optional, Callable, List, Type
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
import logging
import asyncio
from app.models.workflow import normalize_workflow_tool_name
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    normalize_observability_metadata,
    trace_contract_event,
    trace_span,
)

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ITEMS = 20


def _safe_preview(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= _MAX_PREVIEW_ITEMS:
                out["__truncated__"] = f"{len(value) - _MAX_PREVIEW_ITEMS} more"
                break
            out[str(k)] = _safe_preview(v, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [_safe_preview(v, depth + 1) for v in seq[:_MAX_PREVIEW_ITEMS]]
        if len(seq) > _MAX_PREVIEW_ITEMS:
            out.append(f"<truncated_items:{len(seq) - _MAX_PREVIEW_ITEMS}>")
        return out
    return str(value)


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
        from app.services.workflows.tools.playbook_tool import PlaybookCheckTool
        from app.services.workflows.tools.summarize_tool import SummarizeTool
        from app.services.workflows.tools.extract_entities_tool import ExtractEntitiesTool
        from app.services.workflows.tools.legal_db_tool import LegalDBTool
        from app.services.workflows.tools.document_draft_tool import DocumentDraftTool
        
        # Активные инструменты
        self.register(TabularReviewTool)      # Табличный анализ документов
        self.register(RAGTool)                 # Семантический поиск по документам
        self.register(PlaybookCheckTool)       # Проверка документов по Playbook
        self.register(SummarizeTool)           # Резюмирование текста
        self.register(ExtractEntitiesTool)     # Извлечение сущностей
        self.register(LegalDBTool)             # Поиск по загруженному справочнику
        self.register(DocumentDraftTool)       # Создание черновиков документов
        
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
        canonical_name = normalize_workflow_tool_name(name)
        if canonical_name not in self._tool_instances:
            tool_class = self._tools.get(canonical_name)
            if tool_class:
                self._tool_instances[canonical_name] = tool_class(self.db)
        
        return self._tool_instances.get(canonical_name)
    
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
        return normalize_workflow_tool_name(name) in self._tools
    
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
        canonical_name = normalize_workflow_tool_name(tool_name)
        tool = self.get_tool(canonical_name)
        active_ctx = get_active_trace_context()
        
        if not tool:
            trace_contract_event(
                active_ctx,
                name="tool_call_failed",
                level="ERROR",
                metadata=normalize_observability_metadata(
                    {"tool_name": canonical_name, "reason": "tool_not_found"},
                    step_name="workflow_tool_lookup",
                    status="error",
                    error=f"Tool '{tool_name}' not found",
                ),
            )
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found"
            )
        
        # Validate params
        errors = tool.validate_params(params)
        if errors:
            trace_contract_event(
                active_ctx,
                name="tool_call_failed",
                level="WARNING",
                metadata=normalize_observability_metadata(
                    {"tool_name": canonical_name, "reason": "validation_failed"},
                    step_name="workflow_tool_validate_params",
                    status="blocked",
                    error=", ".join(errors),
                ),
                input_payload={"params": _safe_preview(params)},
            )
            return ToolResult(
                success=False,
                error=f"Invalid parameters: {', '.join(errors)}"
            )
        
        span = trace_span(
            active_ctx,
            name=f"workflow_tool_{canonical_name}",
            metadata={"tool_name": canonical_name},
            input_payload={
                "params": _safe_preview(params),
                "context": _safe_preview(context),
            },
        )
        try:
            trace_contract_event(
                active_ctx,
                name="tool_call_started",
                metadata=normalize_observability_metadata(
                    {"tool_name": canonical_name},
                    step_name="workflow_tool_started",
                    status="running",
                ),
                input_payload={"params": _safe_preview(params)},
            )
            logger.info(f"Executing tool: {canonical_name}")
            result = await tool.execute(params, context)
            logger.info(f"Tool {canonical_name} completed: success={result.success}")
            trace_contract_event(
                active_ctx,
                name="tool_call_completed" if result.success else "tool_call_failed",
                level="DEFAULT" if result.success else "WARNING",
                metadata=normalize_observability_metadata(
                    {
                        "tool_name": canonical_name,
                        "llm_calls": int(result.llm_calls or 0),
                        "tokens_used": int(result.tokens_used or 0),
                    },
                    step_name="workflow_tool_completed",
                    status="success" if result.success else "error",
                    error=result.error if not result.success else None,
                ),
                output_payload={
                    "success": bool(result.success),
                    "summary": result.output_summary,
                    "error": result.error,
                    "artifacts_count": len(result.artifacts or []),
                    "data_preview": _safe_preview(result.data),
                },
            )
            if span:
                span.update(
                    output={
                        "success": bool(result.success),
                        "summary": result.output_summary,
                        "error": result.error,
                        "artifacts_count": len(result.artifacts or []),
                    }
                )
            return result
            
        except Exception as e:
            logger.error(f"Tool {canonical_name} failed: {e}", exc_info=True)
            trace_contract_event(
                active_ctx,
                name="tool_call_failed",
                level="ERROR",
                metadata=normalize_observability_metadata(
                    {"tool_name": canonical_name},
                    step_name="workflow_tool_exception",
                    status="error",
                    error=str(e),
                ),
                input_payload={"params": _safe_preview(params)},
            )
            return ToolResult(
                success=False,
                error=str(e)
            )
        finally:
            if span:
                try:
                    span.end()
                except Exception:
                    logger.debug("workflow tool span end failed", exc_info=True)


# Create __init__ for tools package
TOOLS_INIT = '''"""Workflow tools"""
from app.services.workflows.tools.tabular_review_tool import TabularReviewTool
from app.services.workflows.tools.rag_tool import RAGTool
from app.services.workflows.tools.playbook_tool import PlaybookCheckTool
from app.services.workflows.tools.summarize_tool import SummarizeTool
from app.services.workflows.tools.extract_entities_tool import ExtractEntitiesTool

__all__ = [
    "TabularReviewTool",
    "RAGTool", 
    "PlaybookCheckTool",
    "SummarizeTool",
    "ExtractEntitiesTool",
]
'''

