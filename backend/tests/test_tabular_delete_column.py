"""Tests for tabular column delete (order_index compaction)."""
from unittest.mock import MagicMock

from app.services.tabular_review_service import TabularReviewService


def _chain_first(value):
    chain = MagicMock()
    chain.filter.return_value.first.return_value = value
    return chain


def _chain_all(values):
    chain = MagicMock()
    chain.filter.return_value.order_by.return_value.all.return_value = values
    return chain


def test_delete_column_compacts_order_index():
    db = MagicMock()
    review = MagicMock()
    review.id = "review-1"
    review.user_id = "user-1"

    col_a = MagicMock(id="a", order_index=0)
    col_b = MagicMock(id="b", order_index=1)
    col_c = MagicMock(id="c", column_label="Дата", order_index=2)

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "TabularReview":
            return _chain_first(review)
        if name == "TabularColumn":
            col_chain = MagicMock()
            col_chain.filter.return_value.first.return_value = col_c
            col_chain.filter.return_value.order_by.return_value.all.return_value = [col_a, col_b]
            return col_chain
        return MagicMock()

    db.query.side_effect = query_side_effect

    service = TabularReviewService(db)
    result = service.delete_column("review-1", "c", "user-1")

    assert result["column_id"] == "c"
    assert result["column_label"] == "Дата"
    assert col_a.order_index == 0
    assert col_b.order_index == 1
    db.delete.assert_called_once_with(col_c)
    db.flush.assert_called_once()
    db.commit.assert_called_once()


def test_delete_column_removes_review_queue_before_column():
    db = MagicMock()
    review = MagicMock(id="review-1", user_id="user-1")
    col = MagicMock(id="col-q", column_label="Дата", order_index=1)

    delete_chain = MagicMock()
    delete_chain.filter.return_value.delete.return_value = 0
    queried_models: list[str] = []

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        queried_models.append(name)
        if name == "TabularReview":
            return _chain_first(review)
        if name == "TabularColumn":
            col_chain = MagicMock()
            col_chain.filter.return_value.first.return_value = col
            col_chain.filter.return_value.order_by.return_value.all.return_value = []
            return col_chain
        if name in ("ReviewQueueItem", "CellComment", "CellHistory", "TabularCell"):
            return delete_chain
        return MagicMock()

    db.query.side_effect = query_side_effect

    service = TabularReviewService(db)
    result = service.delete_column("review-1", "col-q", "user-1")

    assert result["column_id"] == "col-q"
    assert queried_models[:4] == [
        "TabularReview",
        "TabularColumn",
        "ReviewQueueItem",
        "CellComment",
    ]
    assert "CellHistory" in queried_models
    assert "TabularCell" in queried_models
    assert delete_chain.filter.return_value.delete.call_count == 4
