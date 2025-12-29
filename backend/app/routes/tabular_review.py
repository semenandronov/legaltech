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
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    is_featured: bool = False


class ColumnPromptGenerateRequest(BaseModel):
    column_label: str
    column_type: str  # text, date, currency, number, yes_no, tags, verbatim


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
            description=request.description,
            selected_file_ids=request.selected_file_ids
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
            "verbatim_extract": cell.verbatim_extract,
            "reasoning": cell.reasoning,
            "confidence_score": float(cell.confidence_score) if cell.confidence_score else None,
            "source_page": cell.source_page,
            "source_section": cell.source_section,
            "status": cell.status,
            "column_type": column_type,
            "has_verbatim": has_verbatim,
            "highlight_mode": highlight_mode,
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


@router.get("/")
async def list_reviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of tabular reviews for current user"""
    try:
        from app.models.tabular_review import TabularReview
        from sqlalchemy import desc
        
        # Get reviews for current user, ordered by updated_at desc
        reviews = db.query(TabularReview).filter(
            TabularReview.user_id == current_user.id
        ).order_by(desc(TabularReview.updated_at)).offset(skip).limit(limit).all()
        
        total = db.query(TabularReview).filter(
            TabularReview.user_id == current_user.id
        ).count()
        
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
        from sqlalchemy import and_
        
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
        
        templates = query.order_by(
            TabularColumnTemplate.is_featured.desc(),
            TabularColumnTemplate.usage_count.desc(),
            TabularColumnTemplate.created_at.desc()
        ).all()
        
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "columns": t.columns,
                "is_public": t.is_public,
                "is_system": t.is_system,
                "is_featured": t.is_featured,
                "category": t.category,
                "tags": t.tags or [],
                "usage_count": t.usage_count,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
    except Exception as e:
        logger.error(f"Error getting templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get templates")


@router.post("/{review_id}/templates/apply")
async def apply_template(
    review_id: str,
    template_id: str = Query(..., description="Template ID to apply"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Apply a template to a tabular review - adds all columns from template"""
    try:
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
        for idx, col_def in enumerate(template.columns):
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

