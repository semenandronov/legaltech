"""Review Queue Service for automatic review queue building"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.tabular_review import TabularReview, TabularCell, TabularColumn
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ReviewRules:
    """Configuration for review queue rules"""
    def __init__(
        self,
        low_confidence_threshold: float = 0.7,
        critical_columns: Optional[List[str]] = None,
        always_review_types: Optional[List[str]] = None,
        conflict_priority: bool = True,
        ocr_quality_threshold: float = 0.8
    ):
        self.low_confidence_threshold = low_confidence_threshold
        self.critical_columns = critical_columns or []
        self.always_review_types = always_review_types or ['currency', 'date', 'yes_no']
        self.conflict_priority = conflict_priority
        self.ocr_quality_threshold = ocr_quality_threshold


class QueueItem:
    """Represents an item in the review queue"""
    def __init__(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        cell_id: str,
        priority: int,
        reason: str
    ):
        self.review_id = review_id
        self.file_id = file_id
        self.column_id = column_id
        self.cell_id = cell_id
        self.priority = priority  # 1-5, where 1 is highest priority
        self.reason = reason
        self.created_at = datetime.utcnow()


class ReviewQueueService:
    """Service for building and managing review queues"""
    
    def __init__(self, db: Session):
        """Initialize review queue service"""
        self.db = db
    
    def build_review_queue(
        self,
        review_id: str,
        rules: Optional[ReviewRules] = None
    ) -> List[QueueItem]:
        """
        Build review queue based on rules
        
        Args:
            review_id: Tabular review ID
            rules: ReviewRules configuration (uses defaults if None)
        
        Returns:
            List of QueueItem objects
        """
        if rules is None:
            # Get rules from review config or use defaults
            review = self.db.query(TabularReview).filter(TabularReview.id == review_id).first()
            if review and review.review_rules:
                rules_dict = review.review_rules
                rules = ReviewRules(
                    low_confidence_threshold=rules_dict.get("low_confidence_threshold", 0.7),
                    critical_columns=rules_dict.get("critical_columns", []),
                    always_review_types=rules_dict.get("always_review_types", ['currency', 'date', 'yes_no']),
                    conflict_priority=rules_dict.get("conflict_priority", True),
                    ocr_quality_threshold=rules_dict.get("ocr_quality_threshold", 0.8)
                )
            else:
                rules = ReviewRules()
        
        queue_items = []
        
        # Get all cells for this review
        cells = self.db.query(TabularCell).filter(
            TabularCell.tabular_review_id == review_id
        ).all()
        
        # Get columns for reference
        columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).all()
        column_dict = {col.id: col for col in columns}
        
        for cell in cells:
            column = column_dict.get(cell.column_id)
            if not column:
                continue
            
            # Check various conditions
            reasons = []
            priority = 5  # Default priority (lowest)
            
            # 1. Conflict priority
            if cell.status == 'conflict' and rules.conflict_priority:
                reasons.append("conflict")
                priority = min(priority, 1)  # Highest priority
            
            # 2. Low confidence
            if cell.confidence_score and cell.confidence_score < rules.low_confidence_threshold:
                reasons.append("low_confidence")
                priority = min(priority, 2)
            
            # 3. Critical columns
            if cell.column_id in rules.critical_columns:
                reasons.append("critical_column")
                priority = min(priority, 1)
            
            # 4. Always review types
            if column.column_type in rules.always_review_types:
                reasons.append("always_review_type")
                priority = min(priority, 3)
            
            # 5. Empty or N/A status (might need review)
            if cell.status in ['empty', 'n_a']:
                reasons.append("empty_or_na")
                priority = min(priority, 4)
            
            # 6. Pending status
            if cell.status == 'pending':
                reasons.append("pending")
                priority = min(priority, 3)
            
            # If any reason found, add to queue
            if reasons:
                reason_text = ", ".join(reasons)
                queue_items.append(QueueItem(
                    review_id=review_id,
                    file_id=cell.file_id,
                    column_id=cell.column_id,
                    cell_id=cell.id,
                    priority=priority,
                    reason=reason_text
                ))
        
        # Sort by priority (1 = highest)
        queue_items.sort(key=lambda x: x.priority)
        
        return queue_items
    
    def get_queue_stats(self, review_id: str) -> Dict[str, Any]:
        """Get statistics about review queue"""
        rules = ReviewRules()  # Use defaults for stats
        queue_items = self.build_review_queue(review_id, rules)
        
        # Group by reason
        by_reason = {}
        by_priority = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        
        for item in queue_items:
            # Count by reason
            for reason in item.reason.split(", "):
                by_reason[reason] = by_reason.get(reason, 0) + 1
            
            # Count by priority
            by_priority[item.priority] = by_priority.get(item.priority, 0) + 1
        
        return {
            "total_items": len(queue_items),
            "by_reason": by_reason,
            "by_priority": by_priority,
            "high_priority_count": sum(by_priority[i] for i in [1, 2])
        }

