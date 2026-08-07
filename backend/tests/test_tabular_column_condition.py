"""Unit tests for conditional column run rules."""

from app.services.tabular_column_condition import (
    RunCondition,
    evaluate_run_condition,
    parse_run_condition,
    skipped_extraction_result,
    validate_run_condition_graph,
)
import pytest


def test_parse_run_condition_ok():
    cond = parse_run_condition(
        {"run_condition": {"source_column_id": "col-a", "operator": "is_yes"}}
    )
    assert cond is not None
    assert cond.source_column_id == "col-a"
    assert cond.operator == "is_yes"


def test_parse_run_condition_requires_value_for_equals():
    with pytest.raises(ValueError, match="value is required"):
        parse_run_condition(
            {"run_condition": {"source_column_id": "col-a", "operator": "equals"}}
        )


def test_evaluate_yes_no_and_empty():
    yes = RunCondition(source_column_id="a", operator="is_yes")
    no = RunCondition(source_column_id="a", operator="is_no")
    empty = RunCondition(source_column_id="a", operator="is_empty")
    not_empty = RunCondition(source_column_id="a", operator="is_not_empty")

    assert evaluate_run_condition(yes, source_cell_value="Да") is True
    assert evaluate_run_condition(yes, source_cell_value="yes") is True
    assert evaluate_run_condition(yes, source_cell_value="Нет") is False
    assert evaluate_run_condition(no, source_cell_value="Нет") is True
    assert evaluate_run_condition(empty, source_cell_value=None) is True
    assert evaluate_run_condition(empty, source_cell_value="N/A") is True
    assert evaluate_run_condition(not_empty, source_cell_value="текст") is True


def test_evaluate_equals_contains():
    eq = RunCondition(source_column_id="a", operator="equals", value="Аренда")
    contains = RunCondition(source_column_id="a", operator="contains", value="аренд")
    assert evaluate_run_condition(eq, source_cell_value="аренда") is True
    assert evaluate_run_condition(contains, source_cell_value="Договор аренды") is True
    assert evaluate_run_condition(contains, source_cell_value="Поставка") is False


def test_cycle_detection():
    with pytest.raises(ValueError, match="cycle"):
        validate_run_condition_graph(
            column_id="b",
            column_config={"run_condition": {"source_column_id": "a", "operator": "is_yes"}},
            review_column_ids={"a", "b"},
            conditions_by_column={
                "a": RunCondition(source_column_id="b", operator="is_yes"),
                "b": None,
            },
        )


def test_skipped_payload():
    payload = skipped_extraction_result(
        file_id="f1",
        column_id="c1",
        condition=RunCondition(source_column_id="src", operator="is_yes"),
        source_label="Есть опцион",
    )
    assert payload["status"] == "skipped"
    assert payload["extraction_method"] == "conditional_skip"
    assert payload["cell_value"] is None
