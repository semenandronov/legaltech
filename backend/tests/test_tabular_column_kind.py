"""Tests for ColumnKind routing and risk section planner."""

from types import SimpleNamespace

import pytest

from app.services.tabular_column_kind import infer_column_kind, resolve_column_kind
from app.services.tabular_column_type_contract import validate_column_config
from app.services.tabular_risk_analysis_graph import plan_risk_sections
from app.services.contract_field_catalog import RU_DD_LEASE_TEMPLATE


def test_infer_fact_from_field_id():
    assert (
        infer_column_kind(
            column_type="text",
            prompt="Номер",
            column_config={"field_id": "doc_number"},
        )
        == "fact"
    )


def test_infer_risk_from_prompt():
    assert (
        infer_column_kind(
            column_type="text",
            column_label="Риски",
            prompt="Перечисли ключевые риски договора",
        )
        == "risk_analysis"
    )


def test_infer_manual_from_type():
    assert infer_column_kind(column_type="manual_input", prompt="x") == "manual"


def test_infer_verbatim_from_type():
    assert infer_column_kind(column_type="verbatim", prompt="цитата") == "verbatim"


def test_explicit_column_kind_wins():
    assert (
        infer_column_kind(
            column_type="text",
            prompt="Перечисли риски",
            column_config={"column_kind": "summary"},
        )
        == "summary"
    )


def test_resolve_column_kind_from_model():
    col = SimpleNamespace(
        column_type="text",
        column_label="Ключевые риски",
        prompt="риски",
        column_config={"column_kind": "risk_analysis"},
    )
    assert resolve_column_kind(col) == "risk_analysis"


def test_validate_column_kind():
    validate_column_config("text", {"column_kind": "fact"})
    with pytest.raises(ValueError, match="column_kind"):
        validate_column_config("text", {"column_kind": "agentic_chaos"})


def test_plan_risk_sections_default_and_targeted():
    default = plan_risk_sections("Перечисли ключевые риски")
    assert len(default) >= 1
    assert "liability" in default or "penalty" in default

    targeted = plan_risk_sections("Какая неустойка и условия расторжения?")
    assert "penalty" in targeted
    assert "termination" in targeted


def test_lease_template_includes_risk_column():
    kinds = [
        (c.get("column_config") or {}).get("column_kind")
        for c in RU_DD_LEASE_TEMPLATE["columns"]
    ]
    assert "risk_analysis" in kinds
    assert kinds.count("fact") >= 5
