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
            
            if not case_id:
                return ToolResult(
                    success=False,
                    error="case_id is required for tabular review"
                )
            
            if not user_id:
                return ToolResult(
                    success=False,
                    error="user_id is required for tabular review"
                )
            
            # Create review (synchronous method)
            review = service.create_tabular_review(
                case_id=case_id,
                user_id=user_id,
                name=review_name,
                selected_file_ids=file_ids if file_ids else None
            )
            
            review_id = review.id
            
            # Add columns for each question (synchronous method)
            column_ids = []
            for question in questions:
                column = service.add_column(
                    review_id=review_id,
                    user_id=user_id,
                    column_label=question,
                    column_type="text",
                    prompt=f"Извлеки из документа: {question}"
                )
                column_ids.append(column.id)
            
            # Populate the table - use batch extraction
            try:
                service.extract_all_cells_batch(review_id, user_id)
            except Exception as e:
                logger.warning(f"Batch extraction failed: {e}, trying individual extraction")
                # Fallback to individual extraction
                for column_id in column_ids:
                    try:
                        service.extract_column_values(review_id, column_id, user_id)
                    except Exception as col_e:
                        logger.warning(f"Column extraction failed: {col_e}")
            
            # Get results
            review_data = service.get_tabular_review(review_id, user_id)
            
            # Count rows (documents)
            row_count = len(review_data.selected_file_ids) if review_data.selected_file_ids else 0
            
            return ToolResult(
                success=True,
                data={
                    "review_id": review_id,
                    "columns": column_ids,
                    "row_count": row_count,
                    "review_name": review_name
                },
                output_summary=f"Создана таблица '{review_name}' с {len(column_ids)} колонками и {row_count} строками",
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

