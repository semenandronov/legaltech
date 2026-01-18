"""Legal Database Tool for Workflows - Full Implementation"""
from typing import Dict, Any, List, Optional
from app.services.workflows.tool_registry import BaseTool, ToolResult
import logging
import asyncio

logger = logging.getLogger(__name__)


class LegalDBTool(BaseTool):
    """
    Tool for searching legal databases.
    
    Searches through multiple legal databases:
    - КонсультантПлюс
    - Гарант
    - КАД Арбитр (картотека арбитражных дел)
    - Право.гов.ру (официальное опубликование)
    - ВС РФ (судебная практика Верховного Суда)
    - ВАС РФ (практика арбитражных судов)
    """
    
    name = "legal_db"
    display_name = "Legal Database"
    description = "Поиск в юридических базах данных (законы, судебная практика, арбитражные дела)"
    
    # Available databases
    AVAILABLE_DATABASES = {
        "consultant": "КонсультантПлюс",
        "garant": "Гарант",
        "kad_arbitr": "КАД Арбитр",
        "pravo_gov": "Право.гов.ру",
        "vsrf": "ВС РФ",
        "vas": "ВАС РФ"
    }
    
    def __init__(self, db):
        super().__init__(db)
        self._source_router = None
        self._init_sources()
    
    def _init_sources(self):
        """Initialize legal sources"""
        try:
            from app.services.external_sources.source_router import SourceRouter
            from app.services.external_sources.consultant_source import ConsultantSource
            from app.services.external_sources.garant_source import GarantSource
            from app.services.external_sources.kad_arbitr_source import KadArbitrSource
            from app.services.external_sources.pravo_gov_source import PravoGovSource
            from app.services.external_sources.vsrf_source import VSRFSource
            from app.services.external_sources.vas_practice_source import VASPracticeSource
            
            self._source_router = SourceRouter()
            
            # Register all legal sources with priorities
            self._source_router.register_source(ConsultantSource(), priority=100)
            self._source_router.register_source(GarantSource(), priority=100)
            self._source_router.register_source(KadArbitrSource(), priority=90)
            self._source_router.register_source(PravoGovSource(), priority=95)
            self._source_router.register_source(VSRFSource(), priority=85)
            self._source_router.register_source(VASPracticeSource(), priority=85)
            
            logger.info("LegalDBTool: Initialized with all legal sources")
        except Exception as e:
            logger.warning(f"LegalDBTool: Failed to initialize sources: {e}")
            self._source_router = None
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("query"):
            errors.append("Требуется query")
        
        # Validate database names if provided
        databases = params.get("databases", [])
        if databases:
            invalid_dbs = [db for db in databases if db not in self.AVAILABLE_DATABASES]
            if invalid_dbs:
                errors.append(f"Неизвестные базы данных: {', '.join(invalid_dbs)}")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute legal database search
        
        Params:
            query: Search query
            databases: List of databases to search (optional, defaults to all)
            jurisdiction: Jurisdiction filter (optional, default: "RU")
            doc_type: Document type filter (optional): "law", "court_decision", "regulation"
            date_from: Start date filter (optional)
            date_to: End date filter (optional)
            max_results: Maximum results per database (default: 10)
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            query = params.get("query", "")
            databases = params.get("databases", list(self.AVAILABLE_DATABASES.keys()))
            max_results = params.get("max_results", 10)
            
            # Build filters
            filters = {}
            if params.get("jurisdiction"):
                filters["jurisdiction"] = params.get("jurisdiction")
            if params.get("doc_type"):
                filters["doc_type"] = params.get("doc_type")
            if params.get("date_from"):
                filters["date_from"] = params.get("date_from")
            if params.get("date_to"):
                filters["date_to"] = params.get("date_to")
            
            if not self._source_router:
                # Fallback: try to initialize again
                self._init_sources()
            
            if not self._source_router:
                return ToolResult(
                    success=False,
                    error="Legal database sources not available"
                )
            
            # Initialize sources
            await self._source_router.initialize_all()
            
            # Search across selected databases
            results_by_source = await self._source_router.search(
                query=query,
                source_names=databases,
                max_results_per_source=max_results,
                filters=filters,
                parallel=True
            )
            
            # Aggregate results
            all_results = []
            source_stats = {}
            
            for source_name, source_results in results_by_source.items():
                source_stats[source_name] = len(source_results)
                
                for result in source_results:
                    all_results.append({
                        "source": source_name,
                        "source_display": self.AVAILABLE_DATABASES.get(source_name, source_name),
                        "title": result.title,
                        "content": result.content[:1000] if result.content else "",
                        "url": result.url,
                        "metadata": result.metadata,
                        "relevance_score": result.relevance_score,
                        "document_type": result.metadata.get("doc_type", "unknown"),
                        "date": result.metadata.get("date")
                    })
            
            # Sort by relevance
            all_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            # Generate summary
            total_found = sum(source_stats.values())
            sources_searched = [self.AVAILABLE_DATABASES.get(s, s) for s in source_stats.keys()]
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": all_results,
                    "total_found": total_found,
                    "by_source": source_stats,
                    "databases_searched": databases,
                    "filters_applied": filters
                },
                output_summary=f"Найдено {total_found} результатов в базах: {', '.join(sources_searched)}. "
                              f"Топ результат: {all_results[0]['title'][:100] if all_results else 'нет результатов'}",
                artifacts=[{
                    "type": "legal_search_results",
                    "query": query,
                    "total_results": total_found
                }]
            )
            
        except Exception as e:
            logger.error(f"LegalDBTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )
