"""Unit tests for cell comment count aggregation."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.cell_comment_service import CellCommentService


def test_comment_counts_by_cell_aggregates_unresolved():
    service = CellCommentService(db=MagicMock())
    service.db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        ("file-a", "col-1", 3, 2),
        ("file-b", "col-2", 1, 0),
    ]

    counts = service.comment_counts_by_cell("review-1")

    assert counts[("file-a", "col-1")] == {
        "comment_count": 3,
        "unresolved_comment_count": 2,
    }
    assert counts[("file-b", "col-2")] == {
        "comment_count": 1,
        "unresolved_comment_count": 0,
    }


def test_delete_comment_returns_cell_coords():
    db = MagicMock()
    service = CellCommentService(db=db)
    comment = SimpleNamespace(
        id="c1",
        file_id="f1",
        column_id="col1",
        is_resolved=False,
        created_by="user-1",
    )
    review = SimpleNamespace(id="r1", user_id="user-1")
    service._require_comment = MagicMock(return_value=(comment, review))

    meta = service.delete_comment(comment_id="c1", user_id="user-1", review_id="r1")

    assert meta == {"file_id": "f1", "column_id": "col1", "was_resolved": False}
    db.delete.assert_called_once_with(comment)
    db.commit.assert_called()
