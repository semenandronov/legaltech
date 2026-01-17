"""Tabular Review Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.tabular_review_service import TabularReviewService
import logging

logger = logging.getLogger(__name__)


class TabularReviewTool(BaseTool):
    """
    Tool for creating and populating tabular reviews.
    
    Creates a table where each row is a document and columns are extracted data points.
    """
    
    name = "tabular_review"
    display_name = "Tabular Review"
    description = "Создание таблицы для массового анализа документов с извлечением данных"
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("file_ids") and not params.get("case_id"):
            errors.append("Требуется file_ids или case_id")
        
        if not params.get("questions") and not params.get("columns"):
            errors.append("Требуется questions или columns")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute tabular review
        
        Params:
            file_ids: List of file IDs to analyze
            case_id: Case ID (alternative to file_ids)
            questions: List of questions/columns to extract
            columns: Pre-defined column configurations
            review_name: Optional name for the review
            
        Context:
            user_id: User ID
            case_id: Case ID from workflow
        """
        try:
            service = TabularReviewService(self.db)
            
            user_id = context.get("user_id")
            case_id = params.get("case_id") or context.get("case_id")
            file_ids = params.get("file_ids", [])
            questions = params.get("questions", [])
            review_name = params.get("review_name", "Workflow Review")
            
            # Create review
            review = await service.create_review(
                case_id=case_id,
                user_id=user_id,
                name=review_name,
                file_ids=file_ids
            )
            
            review_id = review.get("id")
            
            # Add columns for each question
            column_ids = []
            for question in questions:
                column = await service.add_column(
                    review_id=review_id,
                    user_id=user_id,
                    name=question,
                    column_type="text",
                    prompt=f"Извлеки из документа: {question}"
                )
                column_ids.append(column.get("id"))
            
            # Populate the table (async population)
            await service.populate_all_cells(review_id, user_id)
            
            # Get results
            results = await service.get_review_data(review_id, user_id)
            
            return ToolResult(
                success=True,
                data={
                    "review_id": review_id,
                    "columns": column_ids,
                    "row_count": len(results.get("rows", [])),
                    "results": results
                },
                output_summary=f"Создана таблица с {len(column_ids)} колонками и {len(results.get('rows', []))} строками",
                artifacts=[{
                    "type": "tabular_review",
                    "id": review_id,
                    "name": review_name
                }]
            )
            
        except Exception as e:
            logger.error(f"TabularReviewTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

