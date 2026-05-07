from app.services.chat.conversation_policy_service import RunContext
from app.services.chat.legal_quality_gates import LegalQualityGates


def _run_ctx(*, mode: str = "case_advice", case_id: str = "c1", citation_policy: str = "required") -> RunContext:
    return RunContext(
        session_id="s1",
        user_id="u1",
        scope="case",
        mode=mode,  # type: ignore[arg-type]
        matter_context=[],
        draft_state="none",
        retrieval_mode="matter",
        citation_policy=citation_policy,
        case_id=case_id,
        execution_path="case_orchestrator",
    )


def test_scope_gate_blocks_case_without_case_id() -> None:
    ctx = _run_ctx(case_id="")
    gate = LegalQualityGates.scope_gate(ctx)
    assert gate.allowed is False
    assert gate.status == "scope_blocked"


def test_citation_gate_required_blocks_when_empty() -> None:
    ctx = _run_ctx(citation_policy="required")
    gate = LegalQualityGates.citation_gate(ctx, citations=[], prompt_profile_id="legacy_default")
    assert gate.allowed is False
    assert gate.status == "clarify_required"


def test_citation_gate_best_effort_allows_when_policy_not_required() -> None:
    ctx = _run_ctx(citation_policy="best_effort")
    gate = LegalQualityGates.citation_gate(ctx, citations=[], prompt_profile_id="extraction_profile")
    assert gate.allowed is True
    assert gate.status in {"citations_best_effort", "citations_ok"}


def test_budget_gate_blocks_when_wall_time_exceeded() -> None:
    gate = LegalQualityGates.budget_gate(budget_profile={"max_wall_time_ms": 1000}, wall_time_ms=2000)
    assert gate.allowed is False
    assert gate.status == "budget_exceeded"
