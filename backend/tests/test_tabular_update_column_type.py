"""Tests for tabular column_type update contract."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.tabular_column_type_contract import validate_column_type
from app.services.tabular_review_service import TabularReviewService


def test_validate_column_type_accepts_date():
    assert validate_column_type("date") == "date"


def test_update_column_persists_column_type():
    db = MagicMock()
    review = SimpleNamespace(id="rev-1", user_id="user-1")
    column = SimpleNamespace(
        id="col-1",
        tabular_review_id="rev-1",
        column_label="Дата",
        column_type="verbatim",
        prompt="Когда?",
        column_config=None,
    )

    review_query = MagicMock()
    review_query.filter.return_value.first.return_value = review

    column_query = MagicMock()
    column_query.filter.return_value.first.return_value = column

    db.query.side_effect = lambda model: review_query if "Review" in str(model) else column_query

    service = TabularReviewService(db)
    with patch.object(service.db, "commit"), patch.object(service.db, "refresh"):
        updated = service.update_column(
            "rev-1",
            "col-1",
            "user-1",
            column_type="date",
        )

    assert updated.column_type == "date"
