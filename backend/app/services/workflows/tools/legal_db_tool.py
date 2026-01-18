"""Legal Database Tool for Workflows - ГАРАНТ Integration"""
from typing import Dict, Any, List, Optional
from app.services.workflows.tool_registry import BaseTool, ToolResult
import logging

logger = logging.getLogger(__name__)


class LegalDBTool(BaseTool):
    """
    Tool for searching ГАРАНТ legal database.
    
    ГАРАНТ - одна из крупнейших правовых информационных систем России.
    Содержит законы, нормативные акты, судебную практику, комментарии.
    
    API v2.1.0: https://api.garant.ru
    """
    
    name = "legal_db"
    display_name = "Legal Database (ГАРАНТ)"
    description = "Поиск в правовой базе ГАРАНТ (законы, судебная практика, нормативные акты)"
    
    def __init__(self, db):
        super().__init__(db)
        self._garant_source = None
        self._init_source()
    
    def _init_source(self):
        """Initialize ГАРАНТ source"""
        try:
            from app.services.external_sources.garant_source import GarantSource
            self._garant_source = GarantSource()
            logger.info("LegalDBTool: Initialized with ГАРАНТ API")
        except Exception as e:
            logger.warning(f"LegalDBTool: Failed to initialize ГАРАНТ: {e}")
            self._garant_source = None
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("query"):
            errors.append("Требуется query")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute legal database search in ГАРАНТ
        
        Params:
            query: Search query (поисковый запрос)
            max_results: Maximum results (default: 10)
            get_full_text: Get full document text (default: False)
            doc_type: Document type filter: "law", "court_decision", "article", "commentary"
            date_from: Start date filter (YYYY-MM-DD)
            date_to: End date filter (YYYY-MM-DD)
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            query = params.get("query", "")
            max_results = params.get("max_results", 10)
            get_full_text = params.get("get_full_text", False)
            
            if not self._garant_source:
                self._init_source()
            
            if not self._garant_source:
                return ToolResult(
                    success=False,
                    error="ГАРАНТ source not available"
                )
            
            # Initialize source
            await self._garant_source.initialize()
            
            if not self._garant_source.enabled:
                return ToolResult(
                    success=False,
                    error="ГАРАНТ API key not configured"
                )
            
            # Build filters
            filters: Dict[str, Any] = {}
            if params.get("doc_type"):
                filters["doc_type"] = params.get("doc_type")
            if params.get("date_from"):
                filters["date_from"] = params.get("date_from")
            if params.get("date_to"):
                filters["date_to"] = params.get("date_to")
            
            # Execute search
            source_results = await self._garant_source.search(
                query=query,
                max_results=max_results,
                filters=filters if filters else None,
                get_full_text=get_full_text
            )
            
            # Convert to serializable format
            results = []
            for result in source_results:
                results.append({
                    "title": result.title,
                    "content": result.content[:2000] if result.content else "",
                    "url": result.url,
                    "source": "ГАРАНТ",
                    "relevance_score": result.relevance_score,
                    "doc_id": result.metadata.get("doc_id"),
                    "doc_type": result.metadata.get("doc_type"),
                    "doc_date": result.metadata.get("doc_date"),
                    "doc_number": result.metadata.get("doc_number"),
                    "issuing_authority": result.metadata.get("issuing_authority")
                })
            
            # Generate summary
            if results:
                summary = f"Найдено {len(results)} документов в ГАРАНТ по запросу: '{query}'"
                if results[0].get("title"):
                    summary += f". Топ результат: {results[0]['title'][:100]}"
            else:
                summary = f"По запросу '{query}' документов не найдено в ГАРАНТ"
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "total_found": len(results),
                    "source": "ГАРАНТ",
                    "filters_applied": filters
                },
                output_summary=summary,
                artifacts=[{
                    "type": "legal_search_results",
                    "source": "garant",
                    "query": query,
                    "result_count": len(results)
                }]
            )
            
        except Exception as e:
            logger.error(f"LegalDBTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )
    
    async def get_document_full_text(self, doc_id: str, format: str = "html") -> Optional[str]:
        """
        Get full document text from ГАРАНТ
        
        Args:
            doc_id: Document ID (topic)
            format: Export format (html, rtf, pdf, odt)
            
        Returns:
            Full document text or None
        """
        if not self._garant_source:
            return None
        
        return await self._garant_source.get_document_full_text(doc_id, format)
    
    async def get_document_info(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get document metadata from ГАРАНТ
        
        Args:
            doc_id: Document ID (topic)
            
        Returns:
            Document info dict or None
        """
        if not self._garant_source:
            return None
        
        return await self._garant_source.get_document_info(doc_id)
    
    async def insert_links(self, text: str) -> Optional[str]:
        """
        Insert ГАРАНТ links into text
        
        Automatically finds document references in text and adds links.
        
        Args:
            text: Text to process (max 20MB)
            
        Returns:
            Text with inserted links or None
        """
        if not self._garant_source:
            return None
        
        return await self._garant_source.insert_links(text)
