"""Validation tests for agent_draft tool schemas."""
import pytest

from app.services.agent_runs.schemas import DraftToolInput, DraftToolOutput


def test_draft_tool_input_valid():
    req = DraftToolInput(
        user_prompt="Составь претензию о взыскании задолженности по договору поставки",
        template_system_id="tpl-1",
    )
    assert req.template_system_id == "tpl-1"


def test_draft_tool_rejects_short_prompt():
    with pytest.raises(ValueError):
        DraftToolInput(user_prompt="коротко")


def test_draft_tool_output():
    out = DraftToolOutput(
        document_id="doc-1",
        title="Претензия",
        editor_path="/cases/c1/editor/doc-1",
        run_id="run-1",
    )
    assert out.status == "completed"
