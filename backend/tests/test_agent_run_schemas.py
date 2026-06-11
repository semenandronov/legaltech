"""Validation tests for agent run API schemas."""
import pytest
from pydantic import ValidationError

from app.services.agent_runs.schemas import CreateAgentRunRequest, PingToolInput, PingToolOutput


def test_create_agent_run_requires_non_empty_task():
    with pytest.raises(ValidationError):
        CreateAgentRunRequest(case_id="c1", user_task="   ")


def test_ping_tool_roundtrip():
    inp = PingToolInput(message="ping")
    out = PingToolOutput(echo=inp.message, run_id="r1")
    assert out.model_dump()["status"] == "success"
