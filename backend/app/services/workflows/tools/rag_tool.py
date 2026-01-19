"""RAG Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.rag_service import RAGService
import logging

logger = logging.getLogger(__name__)


class RAGTool(BaseTool):
    """
    Tool for semantic search using RAG.
    
    Searches through documents and answers questions based on content.
    """
    
    name = "rag"
    display_name = "RAG Search"
    description = "Семантический поиск по документам с ответами на вопросы"
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("query"):
            errors.append("Требуется query")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute RAG search
        
        Params:
            query: Search query or question
            file_ids: Optional list of file IDs to search in
            top_k: Number of results to return (default 10)
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            # RAGService doesn't take db in constructor
            rag_service = RAGService()
            
            query = params.get("query", "")
            file_ids = params.get("file_ids", [])
            top_k = params.get("top_k", 10)
            case_id = context.get("case_id")
            
            if not case_id:
                return ToolResult(
                    success=False,
                    error="case_id is required for RAG search"
                )
            
            # Use retrieve_context method which is synchronous
            from langchain_core.documents import Document
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=top_k,
                db=self.db,
                file_ids=file_ids if file_ids else None  # Filter by selected files
            )
            
            # Convert documents to serializable format
            chunks = []
            for doc in docs:
                chunks.append({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": doc.metadata.get("score", 0)
                })
            
            # Get answer if it's a question
            answer = None
            if "?" in query or any(q in query.lower() for q in ["что", "как", "где", "когда", "почему", "кто"]):
                try:
                    # Use generate_answer method
                    answer = rag_service.generate_answer(
                        query=query,
                        context_docs=docs,
                        case_id=case_id,
                        db=self.db
                    )
                except Exception as e:
                    logger.warning(f"Failed to generate answer: {e}")
                    answer = None
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": chunks[:top_k],
                    "answer": answer,
                    "total_found": len(chunks)
                },
                output_summary=f"Найдено {len(chunks)} релевантных фрагментов" + 
                              (f". Ответ: {answer[:200]}..." if answer else ""),
                llm_calls=1 if answer else 0
            )
            
        except Exception as e:
            logger.error(f"RAGTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

