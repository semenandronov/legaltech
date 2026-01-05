"""Cell Comment Service for managing comments on tabular cells"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from datetime import datetime
from app.models.tabular_review import TabularCell, CellComment, TabularReview, TabularColumn
from app.models.user import User
import logging

logger = logging.getLogger(__name__)


class CellCommentService:
    """Service for managing cell comments"""

    def __init__(self, db: Session):
        self.db = db

    def create_comment(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        comment_text: str,
        user_id: str
    ) -> CellComment:
        """Create a new comment on a cell"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        comment = CellComment(
            tabular_review_id=review_id,
            file_id=file_id,
            column_id=column_id,
            comment_text=comment_text,
            created_by=user_id
        )
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Created comment {comment.id} for cell in review {review_id}")
        return comment

    def get_comments(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        user_id: str,
        include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all comments for a specific cell"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        query = self.db.query(CellComment).filter(
            and_(
                CellComment.tabular_review_id == review_id,
                CellComment.file_id == file_id,
                CellComment.column_id == column_id
            )
        )

        if not include_resolved:
            query = query.filter(CellComment.is_resolved == False)

        comments = query.order_by(desc(CellComment.created_at)).all()

        results = []
        for comment in comments:
            author = self.db.query(User).filter(User.id == comment.created_by).first()
            resolver = None
            if comment.resolved_by:
                resolver = self.db.query(User).filter(User.id == comment.resolved_by).first()

            results.append({
                "id": comment.id,
                "comment_text": comment.comment_text,
                "created_by": author.full_name if author else "Unknown",
                "created_by_id": comment.created_by,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
                "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
                "is_resolved": comment.is_resolved,
                "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
                "resolved_by": resolver.full_name if resolver else None,
                "resolved_by_id": comment.resolved_by,
            })
        return results

    def update_comment(
        self,
        comment_id: str,
        comment_text: str,
        user_id: str
    ) -> CellComment:
        """Update an existing comment"""
        comment = self.db.query(CellComment).filter(CellComment.id == comment_id).first()
        if not comment:
            raise ValueError(f"Comment {comment_id} not found")

        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == comment.tabular_review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {comment.tabular_review_id} not found or access denied")

        # Only the author can update their comment
        if comment.created_by != user_id:
            raise ValueError("You can only update your own comments")

        comment.comment_text = comment_text
        comment.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Updated comment {comment_id}")
        return comment

    def delete_comment(
        self,
        comment_id: str,
        user_id: str
    ) -> None:
        """Delete a comment"""
        comment = self.db.query(CellComment).filter(CellComment.id == comment_id).first()
        if not comment:
            raise ValueError(f"Comment {comment_id} not found")

        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == comment.tabular_review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {comment.tabular_review_id} not found or access denied")

        # Only the author or review owner can delete
        if comment.created_by != user_id and review.user_id != user_id:
            raise ValueError("You don't have permission to delete this comment")

        self.db.delete(comment)
        self.db.commit()
        logger.info(f"Deleted comment {comment_id}")

    def resolve_comment(
        self,
        comment_id: str,
        user_id: str
    ) -> CellComment:
        """Mark a comment as resolved"""
        comment = self.db.query(CellComment).filter(CellComment.id == comment_id).first()
        if not comment:
            raise ValueError(f"Comment {comment_id} not found")

        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == comment.tabular_review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {comment.tabular_review_id} not found or access denied")

        comment.is_resolved = True
        comment.resolved_at = datetime.utcnow()
        comment.resolved_by = user_id
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Resolved comment {comment_id}")
        return comment

    def unresolve_comment(
        self,
        comment_id: str,
        user_id: str
    ) -> CellComment:
        """Mark a comment as unresolved"""
        comment = self.db.query(CellComment).filter(CellComment.id == comment_id).first()
        if not comment:
            raise ValueError(f"Comment {comment_id} not found")

        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == comment.tabular_review_id, TabularReview.user_id == user_id)
        ).first()
        if not review:
            raise ValueError(f"Tabular review {comment.tabular_review_id} not found or access denied")

        comment.is_resolved = False
        comment.resolved_at = None
        comment.resolved_by = None
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Unresolved comment {comment_id}")
        return comment

