"""Integration test: prebuilt assistant state skips draft pipeline bootstrap."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.draft_pipeline.graph import _route_draft_pipeline_entry


def test_draft_pipeline_entry_skips_bootstrap_when_assistant_prebuilt():
    route = _route_draft_pipeline_entry(
        {
            "_from_internal_assistant": True,
            "extracted_facts": {"document_type": "исковое заявление"},
        }
    )
    assert route == "resolve_template"


def test_draft_pipeline_entry_full_bootstrap_without_assistant():
    route = _route_draft_pipeline_entry({"case_id": "c1"})
    assert route == "decompose_task"
