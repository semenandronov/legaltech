"""Cell History Service for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from app.models.tabular_review import TabularCell, CellHistory
from app.models.user import User
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CellHistoryService:
    """Service for managing cell version history"""
    
    def __init__(self, db: Session):
        """Initialize cell history service"""
        self.db = db
    
    def log_cell_change(
        self,
        cell: TabularCell,
        change_type: str,
        changed_by: str,
        previous_cell_value: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> CellHistory:
        """Log a change to a cell"""
        history_record = CellHistory(
            tabular_review_id=cell.tabular_review_id,
            file_id=cell.file_id,
            column_id=cell.column_id,
            cell_value=cell.cell_value,
            verbatim_extract=cell.verbatim_extract,
            reasoning=cell.reasoning,
            source_references=cell.source_references,
            confidence_score=cell.confidence_score,
            source_page=cell.source_page,
            source_section=cell.source_section,
            status=cell.status,
            changed_by=changed_by,
            change_type=change_type,
            previous_cell_value=previous_cell_value,
            change_reason=change_reason
        )
        self.db.add(history_record)
        self.db.commit()
        self.db.refresh(history_record)
        
        logger.info(f"Logged {change_type} change for cell {cell.id} by user {changed_by}")
        return history_record
    
    def get_cell_history(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        limit: int = 50
    ) -> List[CellHistory]:
        """Get history for a specific cell"""
        history = self.db.query(CellHistory).filter(
            and_(
                CellHistory.tabular_review_id == review_id,
                CellHistory.file_id == file_id,
                CellHistory.column_id == column_id
            )
        ).order_by(desc(CellHistory.created_at)).limit(limit).all()
        
        return history
    
    def get_review_history(
        self,
        review_id: str,
        limit: int = 100
    ) -> List[CellHistory]:
        """Get all history for a review (sorted by most recent)"""
        history = self.db.query(CellHistory).filter(
            CellHistory.tabular_review_id == review_id
        ).order_by(desc(CellHistory.created_at)).limit(limit).all()
        
        return history
    
    def get_history_by_user(
        self,
        review_id: str,
        user_id: str,
        limit: int = 100
    ) -> List[CellHistory]:
        """Get history for changes made by a specific user"""
        history = self.db.query(CellHistory).filter(
            and_(
                CellHistory.tabular_review_id == review_id,
                CellHistory.changed_by == user_id
            )
        ).order_by(desc(CellHistory.created_at)).limit(limit).all()
        
        return history
    
    def revert_to_version(
        self,
        history_id: str,
        current_cell: TabularCell,
        user_id: str,
        change_reason: Optional[str] = None
    ) -> TabularCell:
        """Revert a cell to a previous version"""
        # Get the history record
        history_record = self.db.query(CellHistory).filter(
            CellHistory.id == history_id
        ).first()
        
        if not history_record:
            raise ValueError(f"History record {history_id} not found")
        
        # Verify it's for the same cell
        if (history_record.file_id != current_cell.file_id or
            history_record.column_id != current_cell.column_id or
            history_record.tabular_review_id != current_cell.tabular_review_id):
            raise ValueError("History record does not match current cell")
        
        # Save current state before reverting
        previous_cell_value = current_cell.cell_value
        
        # Revert to the history version
        current_cell.cell_value = history_record.cell_value
        current_cell.verbatim_extract = history_record.verbatim_extract
        current_cell.reasoning = history_record.reasoning
        current_cell.source_references = history_record.source_references
        current_cell.confidence_score = history_record.confidence_score
        current_cell.source_page = history_record.source_page
        current_cell.source_section = history_record.source_section
        current_cell.status = history_record.status
        current_cell.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        # Log the revert action
        revert_reason = change_reason or f"Reverted to version from {history_record.created_at.isoformat()}"
        self.log_cell_change(
            cell=current_cell,
            change_type="reverted",
            changed_by=user_id,
            previous_cell_value=previous_cell_value,
            change_reason=revert_reason
        )
        
        self.db.refresh(current_cell)
        logger.info(f"Reverted cell {current_cell.id} to version {history_id} by user {user_id}")
        return current_cell
    
    def get_diff(
        self,
        history_id_1: str,
        history_id_2: str
    ) -> Dict[str, Any]:
        """Get diff between two history versions"""
        record_1 = self.db.query(CellHistory).filter(CellHistory.id == history_id_1).first()
        record_2 = self.db.query(CellHistory).filter(CellHistory.id == history_id_2).first()
        
        if not record_1 or not record_2:
            raise ValueError("One or both history records not found")
        
        diff = {
            "cell_value": {
                "old": record_1.cell_value,
                "new": record_2.cell_value,
                "changed": record_1.cell_value != record_2.cell_value
            },
            "verbatim_extract": {
                "old": record_1.verbatim_extract,
                "new": record_2.verbatim_extract,
                "changed": record_1.verbatim_extract != record_2.verbatim_extract
            },
            "reasoning": {
                "old": record_1.reasoning,
                "new": record_2.reasoning,
                "changed": record_1.reasoning != record_2.reasoning
            },
            "confidence_score": {
                "old": float(record_1.confidence_score) if record_1.confidence_score else None,
                "new": float(record_2.confidence_score) if record_2.confidence_score else None,
                "changed": record_1.confidence_score != record_2.confidence_score
            },
            "source_page": {
                "old": record_1.source_page,
                "new": record_2.source_page,
                "changed": record_1.source_page != record_2.source_page
            },
            "source_section": {
                "old": record_1.source_section,
                "new": record_2.source_section,
                "changed": record_1.source_section != record_2.source_section
            },
            "status": {
                "old": record_1.status,
                "new": record_2.status,
                "changed": record_1.status != record_2.status
            }
        }
        
        return diff
    
    def get_latest_version(
        self,
        review_id: str,
        file_id: str,
        column_id: str
    ) -> Optional[CellHistory]:
        """Get the latest history version for a cell"""
        history = self.db.query(CellHistory).filter(
            and_(
                CellHistory.tabular_review_id == review_id,
                CellHistory.file_id == file_id,
                CellHistory.column_id == column_id
            )
        ).order_by(desc(CellHistory.created_at)).first()
        
        return history

