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
