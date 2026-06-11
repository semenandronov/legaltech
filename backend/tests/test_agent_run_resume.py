"""Unit tests for agent run resume contracts."""
from app.services.agent_runs.schemas import ResumeAgentRunRequest


def test_resume_request_defaults():
    req = ResumeAgentRunRequest()
    assert req.approved is True
    assert req.payload is None


def test_resume_request_with_payload():
    req = ResumeAgentRunRequest(approved=False, payload={"reason": "needs revision"})
    assert req.approved is False
    assert req.payload["reason"] == "needs revision"
