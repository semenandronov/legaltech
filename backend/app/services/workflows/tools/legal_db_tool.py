"""Legal Database Tool for Workflows - uploaded legal corpus search."""
from typing import Dict, Any, List, Optional
from app.services.workflows.tool_registry import BaseTool, ToolResult
import logging

logger = logging.getLogger(__name__)


class LegalDBTool(BaseTool):
    """
    Tool for searching uploaded legal corpus ("Справочник").
    Primary source is local legal corpus files uploaded by the team.
    """
    
    name = "legal_db"
    display_name = "Legal Database (Справочник)"
    description = "Поиск по загруженному правовому справочнику (кодексы, законы, практика)"
    
    def __init__(self, db):
        super().__init__(db)
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("query"):
            errors.append("Требуется query")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute search in uploaded legal corpus.
        
        Params:
            query: Search query (поисковый запрос)
            max_results: Maximum results (default: 10)
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            legal_research_enabled = bool(context.get("legal_research", False))
            if not legal_research_enabled:
                return ToolResult(
                    success=False,
                    error=(
                        "Инструмент legal_db отключен: включите тумблер СПРАВОЧНИК в чате, "
                        "чтобы использовать правовой справочник."
                    ),
                )

            query = params.get("query", "")
            max_results = params.get("max_results", 10)
            get_full_text = params.get("get_full_text", False)
            
            from app.services.legal_corpus_service import retrieve_legal_corpus_documents
            docs = retrieve_legal_corpus_documents(query=query, k=max_results)
            results = []
            for i, doc in enumerate(docs, start=1):
                meta = doc.metadata or {}
                results.append({
                    "title": meta.get("source_filename", f"Фрагмент {i}"),
                    "content": (doc.page_content or "")[:2000],
                    "source": "legal_corpus",
                    "corpus_file_id": meta.get("corpus_file_id"),
                    "chunk_index": meta.get("chunk_index"),
                    "source_page": meta.get("source_page"),
                })
            
            # Generate summary
            if results:
                summary = f"Найдено {len(results)} фрагментов в загруженном справочнике по запросу: '{query}'"
                if results[0].get("title"):
                    summary += f". Топ результат: {results[0]['title'][:100]}"
            else:
                summary = f"По запросу '{query}' в загруженном справочнике ничего не найдено"
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "total_found": len(results),
                    "source": "legal_corpus"
                },
                output_summary=summary,
                artifacts=[{
                    "type": "legal_search_results",
                    "source": "legal_corpus",
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
        return None

    async def get_document_info(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return None

    async def insert_links(self, text: str) -> Optional[str]:
        return None
