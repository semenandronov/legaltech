"""Tabular Review routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional, List
from pydantic import BaseModel
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.tabular_review_service import TabularReviewService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tabular-review"])  # Prefix will be added in main.py


# Request/Response models
class TabularReviewCreateRequest(BaseModel):
    case_id: str
    name: str
    description: Optional[str] = None
    selected_file_ids: Optional[List[str]] = None


class ColumnCreateRequest(BaseModel):
    column_label: str
    column_type: str  # text, bulleted_list, number, currency, yes_no, date, tag, multiple_tags, verbatim, manual_input
    prompt: str
    column_config: Optional[dict] = None  # Конфигурация для tag/multiple_tags: {options: [{label, color}], allow_custom: bool}


class DocumentStatusUpdateRequest(BaseModel):
    file_id: str
    status: str  # not_reviewed, reviewed, flagged, pending_clarification


class CellUpdateRequest(BaseModel):
    cell_value: str
    is_manual_override: bool = True


class ColumnUpdateRequest(BaseModel):
    column_label: Optional[str] = None
    prompt: Optional[str] = None
    column_config: Optional[dict] = None


class ReorderColumnsRequest(BaseModel):
    column_ids: List[str]


class CommentCreateRequest(BaseModel):
    comment_text: str


class CommentUpdateRequest(BaseModel):
    comment_text: str


class BulkStatusRequest(BaseModel):
    file_ids: List[str]
    status: str  # not_reviewed, reviewed, flagged, pending_clarification


class BulkRunRequest(BaseModel):
    file_ids: List[str]
    column_ids: List[str]


class BulkDeleteRequest(BaseModel):
    file_ids: List[str]


class TemplateCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[dict]
    is_public: bool = False
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    is_featured: bool = False


class ColumnPromptGenerateRequest(BaseModel):
    column_label: str
    column_type: str  # text, bulleted_list, number, currency, yes_no, date, tag, multiple_tags, verbatim, manual_input


class ColumnDescriptionRequest(BaseModel):
    description: str


class ColumnExampleRequest(BaseModel):
    document_text: str
    expected_value: str
    context: Optional[str] = None


class ColumnExamplesRequest(BaseModel):
    examples: List[ColumnExampleRequest]


@router.post("/")
async def create_review(
    request: TabularReviewCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new tabular review"""
    try:
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS U] [API create_review] Called: case_id={request.case_id}, user_id={current_user.id}, name={request.name}, selected_file_ids={request.selected_file_ids}")
        # #endregion
        
        service = TabularReviewService(db)
        review = service.create_tabular_review(
            case_id=request.case_id,
            user_id=current_user.id,
            name=request.name,
            description=request.description,
            selected_file_ids=request.selected_file_ids
        )
        
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS V] [API create_review] Review created: review_id={review.id}, checking columns")
        from app.models.tabular_review import TabularColumn
        columns_after_create = db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review.id
        ).all()
        logger.error(f"[DEBUG HYPOTHESIS W] [API create_review] Columns after create: review_id={review.id}, columns_count={len(columns_after_create)}, column_labels={[c.column_label for c in columns_after_create]}")
        # #endregion
        
        return {
            "id": review.id,
            "case_id": review.case_id,
            "name": review.name,
            "description": review.description,
            "status": review.status,
            "created_at": review.created_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating tabular review: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create tabular review")


@router.get("/templates")
async def get_templates(
    category: Optional[str] = Query(None),
    featured: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available column templates with filtering"""
    try:
        from app.models.tabular_review import TabularColumnTemplate
        from sqlalchemy import inspect as sqlalchemy_inspect
        
        # Check if table exists, if not return empty list
        try:
            inspector = sqlalchemy_inspect(db.bind)
            if "tabular_column_templates" not in inspector.get_table_names():
                logger.warning("Table tabular_column_templates does not exist, returning empty list")
                return []
        except Exception as check_err:
            logger.error(f"Error checking table existence: {check_err}", exc_info=True)
            # Continue anyway, let the query fail if table doesn't exist
        
        query = db.query(TabularColumnTemplate).filter(
            or_(
                TabularColumnTemplate.user_id == current_user.id,
                TabularColumnTemplate.is_public == True,
                TabularColumnTemplate.is_system == True
            )
        )
        
        if category:
            query = query.filter(TabularColumnTemplate.category == category)
        
        if featured is not None:
            query = query.filter(TabularColumnTemplate.is_featured == featured)
        
        if search:
            query = query.filter(
                or_(
                    TabularColumnTemplate.name.ilike(f"%{search}%"),
                    TabularColumnTemplate.description.ilike(f"%{search}%")
                )
            )
        
        templates = query.all()
        
        result = []
        for t in templates:
            try:
                # columns is a JSON field, it should already be a list/dict
                columns_data = t.columns if t.columns else []
                # Ensure it's a list
                if not isinstance(columns_data, list):
                    columns_data = []
                
                result.append({
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "columns": columns_data,
                    "is_public": t.is_public,
                    "is_featured": t.is_featured,
                    "is_system": t.is_system,
                    "tags": t.tags if t.tags else [],
                    "usage_count": t.usage_count if hasattr(t, 'usage_count') else 0,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                })
            except Exception as e:
                logger.error(f"Error processing template {t.id if hasattr(t, 'id') else 'unknown'}: {e}", exc_info=True)
                logger.warning(f"Error processing template {t.id}: {e}")
                continue
        
        return result
    except Exception as e:
        logger.error(f"Error getting templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get templates: {str(e)}")


@router.get("/{review_id}")
async def get_review(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get tabular review details"""
    try:
        service = TabularReviewService(db)
        data = service.get_table_data(review_id, current_user.id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting tabular review: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get tabular review")


@router.post("/{review_id}/columns")
async def add_column(
    review_id: str,
    request: ColumnCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a column to tabular review"""
    try:
        # Check columns count before adding
        from app.models.tabular_review import TabularColumn
        columns_before = db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).count()
        logger.info(f"Adding column to review {review_id}. Columns before: {columns_before}, new column: {request.column_label} (type: {request.column_type})")
        
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS E] [API add_column] About to call service.add_column: review_id={review_id}, columns_before={columns_before}, new_column_label={request.column_label}, new_column_type={request.column_type}, user_id={current_user.id}")
        # #endregion
        
        service = TabularReviewService(db)
        column = service.add_column(
            review_id=review_id,
            column_label=request.column_label,
            column_type=request.column_type,
            prompt=request.prompt,
            user_id=current_user.id,
            column_config=request.column_config
        )
        
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS F] [API add_column] service.add_column returned: review_id={review_id}, column_id={column.id}, column_label={column.column_label}")
        # #endregion
        
        # Check columns count after adding
        columns_after = db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).count()
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS G] [API add_column] Columns count after service call: review_id={review_id}, columns_before={columns_before}, columns_after={columns_after}, expected={columns_before+1}")
        # #endregion
        logger.info(f"Column added. Columns after: {columns_after}")
        if columns_after > columns_before + 1:
            logger.error(f"ERROR: More than one column was added! Expected {columns_before + 1}, got {columns_after}")
        
        return {
            "id": column.id,
            "column_label": column.column_label,
            "column_type": column.column_type,
            "prompt": column.prompt,
            "column_config": column.column_config,
            "order_index": column.order_index,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding column: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add column")


@router.patch("/{review_id}/columns/{column_id}")
async def update_column(
    review_id: str,
    column_id: str,
    request: ColumnUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a column (rename, update prompt, config)"""
    try:
        service = TabularReviewService(db)
        column = service.update_column(
            review_id=review_id,
            column_id=column_id,
            user_id=current_user.id,
            column_label=request.column_label,
            prompt=request.prompt,
            column_config=request.column_config
        )
        return {
            "id": column.id,
            "column_label": column.column_label,
            "column_type": column.column_type,
            "prompt": column.prompt,
            "column_config": column.column_config,
            "order_index": column.order_index,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating column: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update column")


@router.delete("/{review_id}/columns/{column_id}")
async def delete_column(
    review_id: str,
    column_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a column (cascade deletes all cells)"""
    try:
        service = TabularReviewService(db)
        service.delete_column(
            review_id=review_id,
            column_id=column_id,
            user_id=current_user.id
        )
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting column: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete column")


@router.post("/{review_id}/columns/reorder")
async def reorder_columns(
    review_id: str,
    request: ReorderColumnsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reorder columns by providing ordered list of column IDs"""
    try:
        service = TabularReviewService(db)
        columns = service.reorder_columns(
            review_id=review_id,
            column_ids=request.column_ids,
            user_id=current_user.id
        )
        return {
            "columns": [
                {
                    "id": col.id,
                    "column_label": col.column_label,
                    "column_type": col.column_type,
                    "order_index": col.order_index,
                }
                for col in columns
            ]
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reordering columns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reorder columns")


@router.post("/{review_id}/run")
async def run_extraction(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Run extraction for all documents and columns"""
    try:
        service = TabularReviewService(db)
        result = await service.run_extraction(review_id, current_user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error running extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run extraction")


@router.post("/{review_id}/columns/{column_id}/run")
async def run_column_extraction(
    review_id: str,
    column_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Run extraction for a specific column across all documents"""
    try:
        service = TabularReviewService(db)
        result = await service.run_column_extraction(review_id, column_id, current_user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error running column extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run column extraction")


@router.get("/{review_id}/table-data")
async def get_table_data(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get table data for tabular review"""
    try:
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS N] [API get_table_data] Called: review_id={review_id}, user_id={current_user.id}")
        # #endregion
        
        # Log columns before getting data
        from app.models.tabular_review import TabularColumn
        columns_before = db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).all()
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS O] [API get_table_data] Before service call: review_id={review_id}, columns_count={len(columns_before)}, column_labels={[c.column_label for c in columns_before]}")
        # #endregion
        logger.info(f"[get_table_data] Review {review_id} has {len(columns_before)} columns: {[c.column_label for c in columns_before]}")
        
        service = TabularReviewService(db)
        data = service.get_table_data(review_id, current_user.id)
        
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS P] [API get_table_data] After service call: review_id={review_id}, columns_count={len(data['columns'])}, column_labels={[c['column_label'] for c in data['columns']]}")
        # #endregion
        
        # Log columns after getting data
        logger.info(f"[get_table_data] Returned {len(data['columns'])} columns: {[c['column_label'] for c in data['columns']]}")
        
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting table data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get table data")


@router.get("/{review_id}/cell/{file_id}/{column_id}")
async def get_cell_details(
    review_id: str,
    file_id: str,
    column_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get cell details with verbatim extract and reasoning"""
    try:
        from app.models.tabular_review import TabularCell, TabularColumn
        
        cell = db.query(TabularCell).filter(
            TabularCell.tabular_review_id == review_id,
            TabularCell.file_id == file_id,
            TabularCell.column_id == column_id
        ).first()
        
        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")
        
        # Get column to determine column_type
        column = db.query(TabularColumn).filter(TabularColumn.id == column_id).first()
        column_type = column.column_type if column else None
        
        # Determine highlight mode
        has_verbatim = bool(cell.verbatim_extract)
        if has_verbatim:
            highlight_mode = 'verbatim'
        elif cell.source_page or cell.source_section:
            highlight_mode = 'page'
        else:
            highlight_mode = 'none'
        
        return {
            "id": cell.id,
            "cell_value": cell.cell_value,
            "normalized_value": cell.normalized_value,
            "verbatim_extract": cell.verbatim_extract,
            "reasoning": cell.reasoning,
            "source_references": cell.source_references or [],
            "confidence_score": float(cell.confidence_score) if cell.confidence_score else None,
            "source_page": cell.source_page,
            "source_section": cell.source_section,
            "status": cell.status,
            "column_type": column_type,
            "has_verbatim": has_verbatim,
            "highlight_mode": highlight_mode,
            "candidates": cell.candidates if cell.candidates else None,
            "conflict_resolution": cell.conflict_resolution if cell.conflict_resolution else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cell details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get cell details")


@router.patch("/{review_id}/cells/{file_id}/{column_id}")
async def update_cell(
    review_id: str,
    file_id: str,
    column_id: str,
    request: CellUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a cell value (manual edit) by file_id and column_id"""
    try:
        service = TabularReviewService(db)
        cell = service.update_cell(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            cell_value=request.cell_value,
            user_id=current_user.id,
            is_manual_override=request.is_manual_override
        )
        return {
            "id": cell.id,
            "cell_value": cell.cell_value,
            "status": cell.status,
            "updated_at": cell.updated_at.isoformat() if cell.updated_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating cell: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update cell")


@router.post("/{review_id}/document-status")
async def update_document_status(
    review_id: str,
    request: DocumentStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update document review status"""
    try:
        service = TabularReviewService(db)
        status = service.mark_as_reviewed(
            review_id=review_id,
            file_id=request.file_id,
            user_id=current_user.id,
            status=request.status
        )
        return {
            "id": status.id,
            "file_id": status.file_id,
            "status": status.status,
            "locked": status.locked,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating document status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update document status")


@router.post("/{review_id}/bulk/status")
async def bulk_update_status(
    review_id: str,
    request: BulkStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk update document status for multiple files"""
    try:
        service = TabularReviewService(db)
        updated_count = service.bulk_update_status(
            review_id=review_id,
            file_ids=request.file_ids,
            status=request.status,
            user_id=current_user.id
        )
        return {
            "success": True,
            "updated_count": updated_count
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error bulk updating status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to bulk update status")


@router.post("/{review_id}/bulk/run")
async def bulk_run_extraction(
    review_id: str,
    request: BulkRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk run extraction for specific files and columns"""
    try:
        service = TabularReviewService(db)
        result = await service.bulk_run_extraction(
            review_id=review_id,
            file_ids=request.file_ids,
            column_ids=request.column_ids,
            user_id=current_user.id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error bulk running extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to bulk run extraction")


@router.delete("/{review_id}/bulk/rows")
async def bulk_delete_rows(
    review_id: str,
    request: BulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk delete rows (remove files from review)"""
    try:
        service = TabularReviewService(db)
        deleted_count = service.bulk_delete_rows(
            review_id=review_id,
            file_ids=request.file_ids,
            user_id=current_user.id
        )
        return {
            "success": True,
            "deleted_count": deleted_count
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error bulk deleting rows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to bulk delete rows")


@router.get("/{review_id}/cells/{file_id}/{column_id}/history")
async def get_cell_history(
    review_id: str,
    file_id: str,
    column_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get history for a specific cell"""
    try:
        from app.services.cell_history_service import CellHistoryService
        history_service = CellHistoryService(db)
        history = history_service.get_cell_history(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            limit=limit
        )
        return [
            {
                "id": record.id,
                "cell_value": record.cell_value,
                "verbatim_extract": record.verbatim_extract,
                "reasoning": record.reasoning,
                "source_references": record.source_references,
                "confidence_score": float(record.confidence_score) if record.confidence_score else None,
                "source_page": record.source_page,
                "source_section": record.source_section,
                "status": record.status,
                "changed_by": record.changed_by,
                "change_type": record.change_type,
                "previous_cell_value": record.previous_cell_value,
                "change_reason": record.change_reason,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
            for record in history
        ]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting cell history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get cell history")


@router.post("/{review_id}/cells/{file_id}/{column_id}/revert")
async def revert_cell(
    review_id: str,
    file_id: str,
    column_id: str,
    request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Revert a cell to a previous version"""
    try:
        from app.services.cell_history_service import CellHistoryService
        from app.services.tabular_review_service import TabularReviewService
        
        history_service = CellHistoryService(db)
        review_service = TabularReviewService(db)
        
        history_id = request.get("history_id")
        change_reason = request.get("change_reason")
        
        if not history_id:
            raise ValueError("history_id is required")
        
        # Get current cell
        cell = db.query(TabularCell).filter(
            and_(
                TabularCell.tabular_review_id == review_id,
                TabularCell.file_id == file_id,
                TabularCell.column_id == column_id
            )
        ).first()
        
        if not cell:
            raise ValueError(f"Cell not found for file {file_id}, column {column_id}")
        
        # Revert to version
        reverted_cell = history_service.revert_to_version(
            history_id=history_id,
            current_cell=cell,
            user_id=current_user.id,
            change_reason=change_reason
        )
        
        return {
            "id": reverted_cell.id,
            "cell_value": reverted_cell.cell_value,
            "status": reverted_cell.status,
            "updated_at": reverted_cell.updated_at.isoformat() if reverted_cell.updated_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reverting cell: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revert cell")


@router.get("/{review_id}/cells/{file_id}/{column_id}/diff")
async def get_cell_diff(
    review_id: str,
    file_id: str,
    column_id: str,
    history_id_1: str,
    history_id_2: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get diff between two cell history versions"""
    try:
        from app.services.cell_history_service import CellHistoryService
        history_service = CellHistoryService(db)
        diff = history_service.get_diff(
            history_id_1=history_id_1,
            history_id_2=history_id_2
        )
        return diff
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting cell diff: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get cell diff")


@router.post("/{review_id}/cells/{file_id}/{column_id}/lock")
async def lock_cell(
    review_id: str,
    file_id: str,
    column_id: str,
    request: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lock a cell for editing"""
    try:
        service = TabularReviewService(db)
        lock_duration = request.get("lock_duration_seconds", 300) if request else 300
        cell = service.lock_cell(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            user_id=current_user.id,
            lock_duration_seconds=lock_duration
        )
        return {
            "id": cell.id,
            "locked_by": cell.locked_by,
            "locked_at": cell.locked_at.isoformat() if cell.locked_at else None,
            "lock_expires_at": cell.lock_expires_at.isoformat() if cell.lock_expires_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error locking cell: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to lock cell")


@router.post("/{review_id}/cells/{file_id}/{column_id}/unlock")
async def unlock_cell(
    review_id: str,
    file_id: str,
    column_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unlock a cell"""
    try:
        service = TabularReviewService(db)
        cell = service.unlock_cell(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            user_id=current_user.id
        )
        return {
            "id": cell.id,
            "locked_by": None,
            "locked_at": None,
            "lock_expires_at": None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error unlocking cell: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unlock cell")


@router.post("/{review_id}/cells/{file_id}/{column_id}/comments")
async def create_comment(
    review_id: str,
    file_id: str,
    column_id: str,
    request: CommentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a comment on a cell"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comment = comment_service.create_comment(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            comment_text=request.comment_text,
            user_id=current_user.id
        )
        # Broadcast comment via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "comment_added",
                "file_id": file_id,
                "column_id": column_id,
                "comment": {
                    "id": comment.id,
                    "comment_text": comment.comment_text,
                    "created_by": current_user.full_name,
                    "created_by_id": current_user.id,
                    "created_at": comment.created_at.isoformat() if comment.created_at else None,
                }
            }
        )
        return {
            "id": comment.id,
            "comment_text": comment.comment_text,
            "created_by": current_user.full_name,
            "created_by_id": current_user.id,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "is_resolved": comment.is_resolved,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create comment")


@router.get("/{review_id}/cells/{file_id}/{column_id}/comments")
async def get_comments(
    review_id: str,
    file_id: str,
    column_id: str,
    include_resolved: bool = Query(False, description="Include resolved comments"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all comments for a cell"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comments = comment_service.get_comments(
            review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            user_id=current_user.id,
            include_resolved=include_resolved
        )
        return comments
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting comments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get comments")


@router.patch("/{review_id}/comments/{comment_id}")
async def update_comment(
    review_id: str,
    comment_id: str,
    request: CommentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a comment"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comment = comment_service.update_comment(
            comment_id=comment_id,
            comment_text=request.comment_text,
            user_id=current_user.id
        )
        # Broadcast update via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "comment_updated",
                "comment_id": comment_id,
                "comment": {
                    "id": comment.id,
                    "comment_text": comment.comment_text,
                    "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
                }
            }
        )
        return {
            "id": comment.id,
            "comment_text": comment.comment_text,
            "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update comment")


@router.delete("/{review_id}/comments/{comment_id}")
async def delete_comment(
    review_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a comment"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comment_service.delete_comment(
            comment_id=comment_id,
            user_id=current_user.id
        )
        # Broadcast deletion via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "comment_deleted",
                "comment_id": comment_id,
            }
        )
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete comment")


@router.post("/{review_id}/comments/{comment_id}/resolve")
async def resolve_comment(
    review_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark a comment as resolved"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comment = comment_service.resolve_comment(
            comment_id=comment_id,
            user_id=current_user.id
        )
        # Broadcast resolution via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "comment_resolved",
                "comment_id": comment_id,
                "resolved_by": current_user.full_name,
            }
        )
        return {
            "id": comment.id,
            "is_resolved": comment.is_resolved,
            "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
            "resolved_by": current_user.full_name,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resolving comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to resolve comment")


@router.post("/{review_id}/comments/{comment_id}/unresolve")
async def unresolve_comment(
    review_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark a comment as unresolved"""
    try:
        from app.services.cell_comment_service import CellCommentService
        comment_service = CellCommentService(db)
        comment = comment_service.unresolve_comment(
            comment_id=comment_id,
            user_id=current_user.id
        )
        # Broadcast unresolution via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "comment_unresolved",
                "comment_id": comment_id,
            }
        )
        return {
            "id": comment.id,
            "is_resolved": comment.is_resolved,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error unresolving comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unresolve comment")


@router.get("/{review_id}/review-queue")
async def get_review_queue(
    review_id: str,
    include_reviewed: bool = Query(False, description="Include reviewed items"),
    priority: Optional[int] = Query(None, description="Filter by priority (1-5)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get review queue items for a tabular review"""
    try:
        from app.services.review_queue_service import ReviewQueueService
        from app.models.tabular_review import ReviewQueueItem, TabularReview
        
        # Verify review belongs to user
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        # Get queue items from database
        query = db.query(ReviewQueueItem).filter(
            ReviewQueueItem.tabular_review_id == review_id
        )
        
        if not include_reviewed:
            query = query.filter(ReviewQueueItem.is_reviewed == False)
        
        if priority:
            query = query.filter(ReviewQueueItem.priority == priority)
        
        queue_items = query.order_by(ReviewQueueItem.priority.asc(), ReviewQueueItem.created_at.asc()).all()
        
        # Get stats
        queue_service = ReviewQueueService(db)
        stats = queue_service.get_queue_stats(review_id)
        
        return {
            "items": [
                {
                    "id": item.id,
                    "file_id": item.file_id,
                    "column_id": item.column_id,
                    "cell_id": item.cell_id,
                    "priority": item.priority,
                    "reason": item.reason,
                    "is_reviewed": item.is_reviewed,
                    "reviewed_by": item.reviewed_by,
                    "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in queue_items
            ],
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting review queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get review queue")


@router.post("/{review_id}/review-queue/rebuild")
async def rebuild_review_queue(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Rebuild review queue for a tabular review"""
    try:
        from app.services.review_queue_service import ReviewQueueService
        from app.models.tabular_review import ReviewQueueItem, TabularReview
        
        # Verify review belongs to user
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        # Delete existing unreviewed items
        db.query(ReviewQueueItem).filter(
            and_(
                ReviewQueueItem.tabular_review_id == review_id,
                ReviewQueueItem.is_reviewed == False
            )
        ).delete()
        
        # Build new queue
        queue_service = ReviewQueueService(db)
        queue_items = queue_service.build_review_queue(review_id)
        
        # Save to database
        for item in queue_items:
            queue_item = ReviewQueueItem(
                tabular_review_id=item.review_id,
                file_id=item.file_id,
                column_id=item.column_id,
                cell_id=item.cell_id,
                priority=item.priority,
                reason=item.reason
            )
            db.add(queue_item)
        
        db.commit()
        
        stats = queue_service.get_queue_stats(review_id)
        
        return {
            "message": f"Review queue rebuilt: {len(queue_items)} items",
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rebuilding review queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rebuild review queue")


@router.patch("/{review_id}/review-queue/{item_id}/mark-reviewed")
async def mark_queue_item_reviewed(
    review_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark a review queue item as reviewed"""
    try:
        from app.models.tabular_review import ReviewQueueItem, TabularReview
        from datetime import datetime
        
        # Verify review belongs to user
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        # Get queue item
        queue_item = db.query(ReviewQueueItem).filter(
            and_(
                ReviewQueueItem.id == item_id,
                ReviewQueueItem.tabular_review_id == review_id
            )
        ).first()
        
        if not queue_item:
            raise HTTPException(status_code=404, detail="Queue item not found")
        
        # Mark as reviewed
        queue_item.is_reviewed = True
        queue_item.reviewed_by = current_user.id
        queue_item.reviewed_at = datetime.utcnow()
        
        db.commit()
        db.refresh(queue_item)
        
        # Broadcast update via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "review_queue_updated",
                "item_id": item_id,
                "is_reviewed": True,
            }
        )
        
        return {
            "id": queue_item.id,
            "is_reviewed": queue_item.is_reviewed,
            "reviewed_at": queue_item.reviewed_at.isoformat() if queue_item.reviewed_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking queue item as reviewed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to mark queue item as reviewed")


class ConflictResolutionRequest(BaseModel):
    selected_candidate_id: int
    resolution_method: str  # 'select', 'merge', 'n_a'


@router.patch("/{review_id}/cells/{file_id}/{column_id}/resolve-conflict")
async def resolve_conflict(
    review_id: str,
    file_id: str,
    column_id: str,
    request: ConflictResolutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve a conflict by selecting a candidate or marking as N/A"""
    try:
        from app.models.tabular_review import TabularCell
        from datetime import datetime
        
        # Get the cell
        cell = db.query(TabularCell).filter(
            and_(
                TabularCell.tabular_review_id == review_id,
                TabularCell.file_id == file_id,
                TabularCell.column_id == column_id
            )
        ).first()
        
        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")
        
        if cell.status != 'conflict':
            raise HTTPException(status_code=400, detail="Cell is not in conflict status")
        
        if not cell.candidates or len(cell.candidates) == 0:
            raise HTTPException(status_code=400, detail="No candidates found for this cell")
        
        # Handle resolution
        if request.resolution_method == 'n_a':
            # Mark as N/A
            cell.cell_value = "N/A"
            cell.normalized_value = None
            cell.status = "n_a"
            cell.conflict_resolution = {
                "resolved_by": current_user.id,
                "resolution_method": "n_a",
                "resolved_at": datetime.utcnow().isoformat()
            }
        else:
            # Select candidate
            if request.selected_candidate_id < 0 or request.selected_candidate_id >= len(cell.candidates):
                raise HTTPException(status_code=400, detail="Invalid candidate ID")
            
            selected_candidate = cell.candidates[request.selected_candidate_id]
            
            # Update cell with selected candidate
            cell.cell_value = selected_candidate.get("value")
            cell.normalized_value = selected_candidate.get("normalized_value")
            cell.verbatim_extract = selected_candidate.get("verbatim")
            cell.reasoning = selected_candidate.get("reasoning")
            cell.confidence_score = selected_candidate.get("confidence")
            cell.source_page = selected_candidate.get("source_page")
            cell.source_section = selected_candidate.get("source_section")
            cell.source_references = selected_candidate.get("source_references")
            cell.status = "completed"
            cell.conflict_resolution = {
                "resolved_by": current_user.id,
                "resolution_method": request.resolution_method,
                "selected_candidate_id": request.selected_candidate_id,
                "resolved_at": datetime.utcnow().isoformat()
            }
        
        # Save history
        from app.services.cell_history_service import CellHistoryService
        history_service = CellHistoryService(db)
        history_service.create_history_record(
            tabular_review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            cell=cell,
            changed_by=current_user.id,
            change_type="updated",
            change_reason=f"Conflict resolved: {request.resolution_method}"
        )
        
        cell.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(cell)
        
        # Broadcast update via WebSocket
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "cell_updated",
                "file_id": file_id,
                "column_id": column_id,
                "cell": {
                    "id": cell.id,
                    "cell_value": cell.cell_value,
                    "status": cell.status,
                }
            }
        )
        
        return {
            "id": cell.id,
            "cell_value": cell.cell_value,
            "status": cell.status,
            "updated_at": cell.updated_at.isoformat() if cell.updated_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving conflict: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to resolve conflict")


@router.post("/{review_id}/export/csv")
async def export_csv(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export tabular review to CSV"""
    try:
        service = TabularReviewService(db)
        csv_content = service.export_to_csv(review_id, current_user.id)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=tabular_review_{review_id}.csv"}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export CSV")


@router.post("/{review_id}/export/excel")
async def export_excel(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export tabular review to Excel"""
    try:
        service = TabularReviewService(db)
        excel_content = service.export_to_excel(review_id, current_user.id)
        return Response(
            content=excel_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=tabular_review_{review_id}.xlsx"}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Excel")


@router.get("/")
async def list_reviews(
    case_id: Optional[str] = Query(None, description="Filter by case_id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of tabular reviews for current user, optionally filtered by case_id"""
    try:
        from app.models.tabular_review import TabularReview
        from sqlalchemy import desc
        
        # Build query
        query = db.query(TabularReview).filter(
            TabularReview.user_id == current_user.id
        )
        
        # Filter by case_id if provided
        if case_id:
            query = query.filter(TabularReview.case_id == case_id)
        
        # Get reviews ordered by updated_at desc
        reviews = query.order_by(desc(TabularReview.updated_at)).offset(skip).limit(limit).all()
        
        # Count total
        count_query = db.query(TabularReview).filter(
            TabularReview.user_id == current_user.id
        )
        if case_id:
            count_query = count_query.filter(TabularReview.case_id == case_id)
        total = count_query.count()
        
        return {
            "reviews": [
                {
                    "id": r.id,
                    "case_id": r.case_id,
                    "name": r.name,
                    "description": r.description,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in reviews
            ],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        logger.error(f"Error listing tabular reviews: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list tabular reviews")


@router.post("/{review_id}/templates/apply")
async def apply_template(
    review_id: str,
    template_id: str = Query(..., description="Template ID to apply"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Apply a template to a tabular review - adds all columns from template"""
    try:
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS H] [API apply_template] Template application called: review_id={review_id}, template_id={template_id}, user_id={current_user.id}")
        # #endregion
        logger.info(f"Applying template {template_id} to review {review_id} by user {current_user.id}")
        from app.models.tabular_review import TabularColumnTemplate
        from app.services.tabular_review_service import TabularReviewService
        
        # Get template
        template = db.query(TabularColumnTemplate).filter(
            or_(
                TabularColumnTemplate.id == template_id,
                and_(
                    TabularColumnTemplate.is_public == True,
                    TabularColumnTemplate.id == template_id
                ),
                and_(
                    TabularColumnTemplate.is_system == True,
                    TabularColumnTemplate.id == template_id
                )
            )
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Apply template columns to review
        service = TabularReviewService(db)
        
        # Verify review exists and belongs to user
        from app.models.tabular_review import TabularReview
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        # Get max order_index
        from app.models.tabular_review import TabularColumn
        max_order_result = db.query(TabularColumn.order_index).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index.desc()).first()
        max_order = max_order_result[0] if max_order_result else -1
        
        # Add all columns from template
        added_columns = []
        # #region agent log
        logger.error(f"[DEBUG HYPOTHESIS I] [API apply_template] About to add columns from template: review_id={review_id}, template_id={template_id}, template_name={template.name}, columns_count={len(template.columns)}, column_labels={[col.get('column_label') for col in template.columns]}")
        # #endregion
        logger.info(f"Template '{template.name}' has {len(template.columns)} columns. Adding them to review {review_id}")
        
        # Filter out unwanted columns from template before applying
        unwanted_column_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        unwanted_column_labels_lower = [label.lower() for label in unwanted_column_labels]
        
        filtered_columns = []
        for col_def in template.columns:
            col_label = col_def.get("column_label", "")
            col_label_lower = col_label.lower()
            
            # Skip unwanted columns
            if col_label in unwanted_column_labels:
                logger.warning(f"  Skipping unwanted column from template: '{col_label}'")
                continue
            elif col_label_lower in unwanted_column_labels_lower:
                logger.warning(f"  Skipping unwanted column from template: '{col_label}'")
                continue
            elif "per on" in col_label_lower and "mentioned" in col_label_lower:
                logger.warning(f"  Skipping unwanted column from template: '{col_label}'")
                continue
            
            filtered_columns.append(col_def)
        
        if len(filtered_columns) < len(template.columns):
            logger.warning(f"Filtered out {len(template.columns) - len(filtered_columns)} unwanted columns from template '{template.name}'")
        
        for idx, col_def in enumerate(filtered_columns):
            logger.info(f"  Adding column {idx + 1}/{len(filtered_columns)}: {col_def.get('column_label')} (type: {col_def.get('column_type')})")
            column = service.add_column(
                review_id=review_id,
                column_label=col_def.get("column_label", f"Column {idx + 1}"),
                column_type=col_def.get("column_type", "text"),
                prompt=col_def.get("prompt", ""),
                user_id=current_user.id
            )
            added_columns.append({
                "id": column.id,
                "column_label": column.column_label,
                "column_type": column.column_type,
            })
        
        # Refresh template usage count
        template.usage_count = (template.usage_count or 0) + 1
        db.commit()
        
        logger.info(f"Template '{template.name}' applied successfully: {len(added_columns)} columns added to review {review_id}")
        return {
            "message": f"Template applied: {len(added_columns)} columns added",
            "columns": added_columns
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to apply template")


@router.post("/templates")
async def save_template(
    request: TemplateCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Save a column template"""
    try:
        from app.models.tabular_review import TabularColumnTemplate
        
        template = TabularColumnTemplate(
            user_id=current_user.id,
            name=request.name,
            description=request.description,
            columns=request.columns,
            is_public=request.is_public,
            category=request.category,
            tags=request.tags or [],
            is_featured=request.is_featured
        )
        
        db.add(template)
        db.commit()
        db.refresh(template)
        
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "columns": template.columns,
            "is_public": template.is_public,
            "category": template.category,
            "tags": template.tags or [],
            "is_featured": template.is_featured,
        }
    except Exception as e:
        logger.error(f"Error saving template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save template")


class UpdateSelectedFilesRequest(BaseModel):
    file_ids: List[str]


@router.post("/{review_id}/files")
async def update_selected_files(
    review_id: str,
    request: UpdateSelectedFilesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update selected files for a tabular review"""
    try:
        service = TabularReviewService(db)
        review = service.update_selected_files(
            review_id=review_id,
            file_ids=request.file_ids,
            user_id=current_user.id
        )
        return {
            "id": review.id,
            "selected_file_ids": review.selected_file_ids,
            "message": f"Updated selected files: {len(request.file_ids)} files"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating selected files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update selected files")


@router.get("/{review_id}/available-files")
async def get_available_files(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all available files for a case (for selecting files for tabular review)"""
    try:
        from app.models.case import Case, File as FileModel
        from sqlalchemy import and_
        
        service = TabularReviewService(db)
        from app.models.tabular_review import TabularReview
        
        # Verify review belongs to user
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        # Get all files for the case
        files = db.query(FileModel).filter(FileModel.case_id == review.case_id).all()
        
        return {
            "files": [
                {
                    "id": file.id,
                    "filename": file.filename,
                    "file_type": file.file_type,
                    "created_at": file.created_at.isoformat() if file.created_at else None
                }
                for file in files
            ],
            "total": len(files),
            "selected_count": len(review.selected_file_ids) if review.selected_file_ids else 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting available files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get available files")


class TabularChatRequest(BaseModel):
    question: str


@router.post("/{review_id}/chat")
async def chat_over_table(
    review_id: str,
    request: TabularChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Chat over table - ask questions about table data"""
    try:
        from app.services.tabular_chat_service import TabularChatService
        
        service = TabularChatService(db)
        result = await service.analyze_table(
            review_id=review_id,
            question=request.question,
            user_id=current_user.id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error in chat over table: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze table")


@router.post("/columns/generate-prompt")
async def generate_column_prompt(
    request: ColumnPromptGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate AI prompt for a column based on label and type"""
    try:
        from app.services.llm_factory import create_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        
        llm = create_llm(temperature=0.7)
        
        # Build prompt generation request
        system_prompt = """Ты эксперт по созданию промптов для извлечения информации из юридических документов.
Твоя задача - создать четкий и эффективный промпт для AI-агента, который будет извлекать информацию из документов.

Типы колонок:
- text: свободный текст
- bulleted_list: маркированный список
- number: числовое значение
- currency: денежная сумма с валютой
- yes_no: да/нет (boolean)
- date: дата
- tag: один тег из предопределенного списка
- multiple_tags: несколько тегов из предопределенного списка
- verbatim: точная цитата из документа
- manual_input: ручной ввод (без AI)

Создай промпт на английском языке, который:
1. Четко описывает, какую информацию нужно извлечь
2. Указывает формат ответа
3. Для tag/multiple_tags - перечисляет доступные опции
4. Для verbatim - требует точную цитату с указанием источника

Верни ТОЛЬКО промпт, без дополнительных объяснений."""

        user_prompt = f"""Создай промпт для колонки:
Название: {request.column_label}
Тип: {request.column_type}

Промпт должен быть на английском языке и четко описывать, какую информацию нужно извлечь."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        prompt = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        
        return {"prompt": prompt}
        
    except Exception as e:
        logger.error(f"Error generating column prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate prompt")


@router.post("/{review_id}/columns/smart-from-description")
async def create_column_from_description(
    review_id: str,
    request: ColumnDescriptionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a column from natural language description"""
    try:
        from app.services.smart_column_service import SmartColumnService
        
        # Verify review belongs to user
        from app.models.tabular_review import TabularReview
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        service = SmartColumnService(db)
        column = await service.create_column_from_description(review_id, request.description)
        
        return {
            "id": column.id,
            "column_label": column.column_label,
            "column_type": column.column_type,
            "prompt": column.prompt,
            "column_config": column.column_config,
            "order_index": column.order_index,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating column from description: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create column from description")


@router.post("/{review_id}/columns/smart-from-examples")
async def create_column_from_examples(
    review_id: str,
    request: ColumnExamplesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a column from examples (few-shot learning)"""
    try:
        from app.services.smart_column_service import SmartColumnService, Example
        
        # Verify review belongs to user
        from app.models.tabular_review import TabularReview
        review = db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == current_user.id)
        ).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Tabular review not found or access denied")
        
        if len(request.examples) < 2:
            raise HTTPException(status_code=400, detail="At least 2 examples are required")
        
        # Convert to Example objects
        examples = [
            Example(
                document_text=ex.document_text,
                expected_value=ex.expected_value,
                context=ex.context
            )
            for ex in request.examples
        ]
        
        service = SmartColumnService(db)
        column = await service.create_column_from_examples(review_id, examples)
        
        return {
            "id": column.id,
            "column_label": column.column_label,
            "column_type": column.column_type,
            "prompt": column.prompt,
            "column_config": column.column_config,
            "order_index": column.order_index,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating column from examples: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create column from examples")

