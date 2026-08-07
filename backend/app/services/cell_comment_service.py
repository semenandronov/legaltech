"""Cell Comment Service for managing comments on tabular cells"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, desc, func
from datetime import datetime
from app.models.tabular_review import CellComment, TabularReview
from app.models.user import User
import logging

logger = logging.getLogger(__name__)


class CellCommentService:
    """Service for managing cell comments.

    Authorization is enforced at the route boundary via case ACL
    (require_review_access / require_review_write). This service loads
    reviews by id only.
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_review(self, review_id: str) -> TabularReview:
        review = (
            self.db.query(TabularReview)
            .filter(TabularReview.id == str(review_id))
            .first()
        )
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        return review

    def create_comment(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        comment_text: str,
        user_id: str
    ) -> CellComment:
        """Create a new comment on a cell"""
        self._get_review(review_id)

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
        self._get_review(review_id)

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

    def _require_comment(
        self,
        *,
        review_id: str,
        comment_id: str,
    ) -> tuple[CellComment, TabularReview]:
        """Return a comment scoped to the review (ACL already checked at route)."""
        review = self._get_review(review_id)

        comment = self.db.query(CellComment).filter(
            and_(
                CellComment.id == comment_id,
                CellComment.tabular_review_id == review_id,
            )
        ).first()
        if not comment:
            raise ValueError(f"Comment {comment_id} not found")
        return comment, review

    def update_comment(
        self,
        comment_id: str,
        comment_text: str,
        user_id: str,
        review_id: str,
    ) -> CellComment:
        """Update an existing comment"""
        comment, _review = self._require_comment(
            review_id=review_id,
            comment_id=comment_id,
        )

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
        user_id: str,
        review_id: str,
    ) -> Dict[str, Any]:
        """Delete a comment. Returns file_id/column_id for WS fan-out."""
        comment, _review = self._require_comment(
            review_id=review_id,
            comment_id=comment_id,
        )
        # Route already required require_review_write — any editor may delete.

        file_id = comment.file_id
        column_id = comment.column_id
        was_resolved = bool(comment.is_resolved)
        self.db.delete(comment)
        self.db.commit()
        logger.info(f"Deleted comment {comment_id}")
        return {
            "file_id": file_id,
            "column_id": column_id,
            "was_resolved": was_resolved,
        }

    def resolve_comment(
        self,
        comment_id: str,
        user_id: str,
        review_id: str,
    ) -> CellComment:
        """Mark a comment as resolved"""
        comment, _review = self._require_comment(
            review_id=review_id,
            comment_id=comment_id,
        )

        comment.is_resolved = True
        comment.resolved_by = user_id
        comment.resolved_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Resolved comment {comment_id}")
        return comment

    def unresolve_comment(
        self,
        comment_id: str,
        user_id: str,
        review_id: str,
    ) -> CellComment:
        """Mark a comment as unresolved"""
        comment, _review = self._require_comment(
            review_id=review_id,
            comment_id=comment_id,
        )

        comment.is_resolved = False
        comment.resolved_by = None
        comment.resolved_at = None
        self.db.commit()
        self.db.refresh(comment)
        logger.info(f"Unresolved comment {comment_id}")
        return comment

    def comment_counts_by_cell(self, review_id: str) -> Dict[tuple, Dict[str, int]]:
        """Return {(file_id, column_id): {comment_count, unresolved_comment_count}}."""
        rows = (
            self.db.query(
                CellComment.file_id,
                CellComment.column_id,
                func.count(CellComment.id),
                func.coalesce(
                    func.sum(case((CellComment.is_resolved.is_(False), 1), else_=0)),
                    0,
                ),
            )
            .filter(CellComment.tabular_review_id == review_id)
            .group_by(CellComment.file_id, CellComment.column_id)
            .all()
        )
        counts: Dict[tuple, Dict[str, int]] = {}
        for file_id, column_id, total, unresolved in rows:
            counts[(file_id, column_id)] = {
                "comment_count": int(total or 0),
                "unresolved_comment_count": int(unresolved or 0),
            }
        return counts
