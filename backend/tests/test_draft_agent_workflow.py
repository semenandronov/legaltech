"""Tests for hybrid draft workflow routing."""
from __future__ import annotations

from app.services.draft_agent.workflow import _route_after_coverage, _route_entry


def test_route_entry_catalog_fill():
    assert _route_entry({"template_mode": "catalog_fill"}) == "catalog_fill"
    assert _route_entry({"template_mode": "template_guide"}) == "decompose_task"


def test_route_after_coverage_retries_when_gaps_remain():
    state = {
        "coverage_sufficient": False,
        "retrieval_retry_count": 0,
        "coverage_gaps": [{"gap_id": "parties", "label": "Стороны"}],
    }
    assert _route_after_coverage(state) == "targeted_retrieval"


def test_route_after_coverage_proceeds_when_sufficient():
    state = {"coverage_sufficient": True, "retrieval_retry_count": 0, "coverage_gaps": []}
    assert _route_after_coverage(state) == "verify_financials"


def test_route_after_coverage_stops_retrying_at_limit():
    state = {
        "coverage_sufficient": False,
        "retrieval_retry_count": 2,
        "coverage_gaps": [{"gap_id": "parties"}],
    }
    assert _route_after_coverage(state) == "verify_financials"
