"""Web Search Tool for Workflows - Full Implementation"""
from typing import Dict, Any, List, Optional
from app.services.workflows.tool_registry import BaseTool, ToolResult
import logging

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """
    Tool for web search using Yandex Search API.
    
    Searches the internet for relevant information with legal context enhancement.
    """
    
    name = "web_search"
    display_name = "Web Search"
    description = "Поиск информации в интернете (Yandex Search API)"
    
    def __init__(self, db):
        super().__init__(db)
        self._web_source = None
        self._init_source()
    
    def _init_source(self):
        """Initialize web search source"""
        try:
            from app.services.external_sources.web_search import WebSearchSource
            self._web_source = WebSearchSource()
            logger.info("WebSearchTool: Initialized with Yandex Search API")
        except Exception as e:
            logger.warning(f"WebSearchTool: Failed to initialize: {e}")
            self._web_source = None
    
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
            site: Restrict search to specific site (optional)
            language: Language filter (default: "ru")
            search_type: Type of search - "general", "legal", "news" (default: "general")
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            query = params.get("query", "")
            num_results = params.get("num_results", 10)
            site = params.get("site")
            language = params.get("language", "ru")
            search_type = params.get("search_type", "general")
            
            if not self._web_source:
                self._init_source()
            
            if not self._web_source:
                return ToolResult(
                    success=False,
                    error="Web search source not available"
                )
            
            # Initialize source
            await self._web_source.initialize()
            
            # Build filters
            filters: Dict[str, Any] = {
                "language": language
            }
            if site:
                filters["site"] = site
            if search_type == "legal":
                filters["legal_context"] = True
            
            # Execute search
            source_results = await self._web_source.search(
                query=query,
                max_results=num_results,
                filters=filters
            )
            
            # Convert to serializable format
            results = []
            for result in source_results:
                results.append({
                    "title": result.title,
                    "url": result.url,
                    "snippet": result.content[:500] if result.content else "",
                    "source": result.source,
                    "relevance_score": result.relevance_score,
                    "metadata": result.metadata
                })
            
            # Generate summary
            if results:
                top_sources = list(set(r.get("source", "web") for r in results[:5]))
                summary = f"Найдено {len(results)} результатов. Источники: {', '.join(top_sources)}"
            else:
                summary = f"По запросу '{query}' результатов не найдено"
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "total_found": len(results),
                    "search_type": search_type,
                    "filters_applied": filters
                },
                output_summary=summary,
                artifacts=[{
                    "type": "web_search_results",
                    "query": query,
                    "result_count": len(results)
                }]
            )
            
        except Exception as e:
            logger.error(f"WebSearchTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

