"""Tabular Review routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.tabular_review_service import TabularReviewService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tabular-review", tags=["tabular-review"])


# Request/Response models
class TabularReviewCreateRequest(BaseModel):
    case_id: str
    name: str
    description: Optional[str] = None


class ColumnCreateRequest(BaseModel):
    column_label: str
    column_type: str  # text, date, currency, number, yes_no, tags, verbatim
    prompt: str


class DocumentStatusUpdateRequest(BaseModel):
    file_id: str
    status: str  # not_reviewed, reviewed, flagged, pending_clarification


class TemplateCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[dict]
    is_public: bool = False


@router.post("/")
async def create_review(
    request: TabularReviewCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new tabular review"""
    try:
        service = TabularReviewService(db)
        review = service.create_tabular_review(
            case_id=request.case_id,
            user_id=current_user.id,
            name=request.name,
            description=request.description
        )
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
        service = TabularReviewService(db)
        column = service.add_column(
            review_id=review_id,
            column_label=request.column_label,
            column_type=request.column_type,
            prompt=request.prompt,
            user_id=current_user.id
        )
        return {
            "id": column.id,
            "column_label": column.column_label,
            "column_type": column.column_type,
            "prompt": column.prompt,
            "order_index": column.order_index,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding column: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add column")


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


@router.get("/{review_id}/table-data")
async def get_table_data(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get table data for tabular review"""
    try:
        service = TabularReviewService(db)
        data = service.get_table_data(review_id, current_user.id)
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
        from app.models.tabular_review import TabularCell
        
        cell = db.query(TabularCell).filter(
            TabularCell.tabular_review_id == review_id,
            TabularCell.file_id == file_id,
            TabularCell.column_id == column_id
        ).first()
        
        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")
        
        return {
            "id": cell.id,
            "cell_value": cell.cell_value,
            "verbatim_extract": cell.verbatim_extract,
            "reasoning": cell.reasoning,
            "confidence_score": float(cell.confidence_score) if cell.confidence_score else None,
            "source_page": cell.source_page,
            "source_section": cell.source_section,
            "status": cell.status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cell details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get cell details")


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


@router.get("/templates")
async def get_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available column templates"""
    try:
        from app.models.tabular_review import TabularColumnTemplate
        
        templates = db.query(TabularColumnTemplate).filter(
            or_(
                TabularColumnTemplate.user_id == current_user.id,
                TabularColumnTemplate.is_public == True
            )
        ).all()
        
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "columns": t.columns,
                "is_public": t.is_public,
            }
            for t in templates
        ]
    except Exception as e:
        logger.error(f"Error getting templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get templates")


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
            is_public=request.is_public
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
        }
    except Exception as e:
        logger.error(f"Error saving template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save template")

