"""Playbook Check Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.playbook_checker import PlaybookChecker
import logging

logger = logging.getLogger(__name__)


class PlaybookCheckTool(BaseTool):
    """
    Tool for checking documents against playbooks.
    
    Validates contract compliance and generates redlines.
    """
    
    name = "playbook_check"
    display_name = "Playbook Check"
    description = "Проверка документа на соответствие правилам Playbook"
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("document_id") and not params.get("document_ids") and not params.get("file_ids"):
            errors.append("Требуется document_id, document_ids или file_ids")
        
        if not params.get("playbook_id"):
            errors.append("Требуется playbook_id")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute playbook check
        
        Params:
            document_id: Single document ID
            document_ids: List of document IDs (for batch)
            file_ids: List of file IDs (from workflow, alias for document_ids)
            playbook_id: Playbook ID to check against
            
        Context:
            user_id: User ID
            case_id: Case ID
        """
        try:
            checker = PlaybookChecker(self.db)
            
            user_id = context.get("user_id")
            case_id = context.get("case_id")
            playbook_id = params.get("playbook_id")
            
            # Single document or batch - support both document_ids and file_ids
            document_ids = params.get("document_ids", []) or params.get("file_ids", [])
            if params.get("document_id"):
                document_ids = [params.get("document_id")]
            
            results = []
            
            for doc_id in document_ids:
                try:
                    result = await checker.check_document(
                        document_id=doc_id,
                        playbook_id=playbook_id,
                        user_id=user_id,
                        case_id=case_id
                    )
                    results.append({
                        "document_id": doc_id,
                        "check_id": result.check_id,
                        "status": result.overall_status,
                        "compliance_score": result.compliance_score,
                        "violations": result.red_line_violations + result.no_go_violations,
                        "redlines_count": len(result.redlines)
                    })
                except Exception as e:
                    results.append({
                        "document_id": doc_id,
                        "status": "failed",
                        "error": str(e)
                    })
            
            # Aggregate statistics
            total_docs = len(results)
            compliant = sum(1 for r in results if r.get("status") == "compliant")
            non_compliant = sum(1 for r in results if r.get("status") == "non_compliant")
            needs_review = sum(1 for r in results if r.get("status") == "needs_review")
            
            return ToolResult(
                success=True,
                data={
                    "results": results,
                    "summary": {
                        "total_documents": total_docs,
                        "compliant": compliant,
                        "non_compliant": non_compliant,
                        "needs_review": needs_review
                    }
                },
                output_summary=f"Проверено {total_docs} документов: {compliant} соответствуют, {non_compliant} не соответствуют, {needs_review} требуют проверки",
                artifacts=[{
                    "type": "playbook_check",
                    "id": r.get("check_id"),
                    "document_id": r.get("document_id")
                } for r in results if r.get("check_id")]
            )
            
        except Exception as e:
            logger.error(f"PlaybookCheckTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

