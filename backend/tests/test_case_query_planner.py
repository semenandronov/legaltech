"""Tests for case query planner."""
from __future__ import annotations

from unittest.mock import patch

from app.services.chat.case_query_planner import (
    apply_query_plan_to_budget,
    plan_case_query,
)


def test_attached_files_skip_scope_router_and_pre_route():
    plan = plan_case_query(
        case_id="c1",
        question="о чем возражение",
        retrieval_query="о чем возражение",
        task_type="single_doc_extraction",
        depth_tier="fast",
        execution_tier="instant",
        attached_file_ids=["file-a"],
    )
    assert plan.skip_document_scope_router is True
    assert plan.pre_retrieval_task is not None
    assert plan.pre_retrieval_task["file_ids"] == ["file-a"]
    assert plan.generation_profile == "draft"
    assert plan.rerank_policy == "skip"


def test_sql_path_analytics():
    plan = plan_case_query(
        case_id="c1",
        question="сколько списаний в мае",
        structured_data_plane="sql",
    )
    assert plan.path == "analytics"
    assert plan.skip_document_scope_router is True
    assert plan.rerank_policy == "skip"


def test_apply_plan_disables_rerank_on_instant():
    plan = plan_case_query(
        case_id="c1",
        question="факт",
        task_type="single_doc_extraction",
        depth_tier="fast",
        execution_tier="instant",
    )
    bp = apply_query_plan_to_budget({"execution_tier": "instant", "rerank_enabled": False}, plan)
    assert bp["rerank_enabled"] is False
    assert bp["generation_profile"] == "draft"


@patch("app.services.chat.case_query_planner.query_planner_enabled", return_value=False)
def test_planner_disabled_returns_default(_mock):
    plan = plan_case_query(case_id="c1", question="x")
    assert plan.plan_reason == "planner_disabled"
