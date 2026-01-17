"""Web Search Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
import logging

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """
    Tool for web search.
    
    Searches the internet for relevant information.
    """
    
    name = "web_search"
    display_name = "Web Search"
    description = "Поиск информации в интернете"
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("query"):
            errors.append("Требуется query")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute web search
        
        Params:
            query: Search query
            num_results: Number of results (default 10)
            
        Context:
            user_id: User ID
        """
        try:
            # Try to import web research service
            try:
                from app.services.external_sources.web_research_service import WebResearchService
                
                service = WebResearchService()
                
                query = params.get("query", "")
                num_results = params.get("num_results", 10)
                
                results = await service.search(
                    query=query,
                    num_results=num_results
                )
                
                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "results": results[:num_results]
                    },
                    output_summary=f"Найдено {len(results)} результатов по запросу: {query}"
                )
                
            except ImportError:
                logger.warning("WebResearchService not available")
                return ToolResult(
                    success=False,
                    error="Web search service not available"
                )
            
        except Exception as e:
            logger.error(f"WebSearchTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

