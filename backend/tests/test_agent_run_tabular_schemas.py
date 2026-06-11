"""Validation tests for tabular review agent tool schemas."""
import pytest

from app.services.agent_runs.schemas import TabularReviewToolInput


def test_tabular_tool_input_valid():
    req = TabularReviewToolInput(
        review_name="Суммы и стороны",
        columns=[
            {
                "column_label": "Сумма",
                "column_type": "currency",
                "prompt": "Какая сумма указана в документе?",
            }
        ],
    )
    assert req.review_name == "Суммы и стороны"
    assert req.columns[0].column_type == "currency"


def test_tabular_tool_rejects_invalid_column_type():
    with pytest.raises(ValueError):
        TabularReviewToolInput(
            review_name="Test",
            columns=[
                {
                    "column_label": "X",
                    "column_type": "invalid_type",
                    "prompt": "Q?",
                }
            ],
        )


def test_tabular_tool_rejects_empty_columns():
    with pytest.raises(ValueError):
        TabularReviewToolInput(review_name="Test", columns=[])
