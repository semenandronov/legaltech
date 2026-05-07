from __future__ import annotations

from app.services.chat.metrics import ChatMetrics
from app.services.chat.prompt_profiles import PROMPT_PROFILES, PromptProfileResolver, build_base_prompt


def test_prompt_profile_resolver_by_route() -> None:
    assert PromptProfileResolver.resolve_for_route("retrieval").profile_id == "retrieval_profile"
    assert PromptProfileResolver.resolve_for_route("extraction").profile_id == "extraction_profile"
    assert PromptProfileResolver.resolve_for_route("legal_qna").profile_id == "legal_qna_profile"
    assert PromptProfileResolver.resolve_for_route("mixed").profile_id == "mixed_profile"
    assert PromptProfileResolver.resolve_for_route("unknown").profile_id == "legacy_default"


def test_prompt_profiles_have_required_contract_fields() -> None:
    required = {
        "profile_id",
        "goal",
        "response_format",
        "clarify_criteria",
        "fallback_criteria",
        "route_addon",
        "constraints",
        "output_style",
        "citation_policy",
    }
    for _, profile in PROMPT_PROFILES.items():
        payload = profile.__dict__
        assert required.issubset(set(payload.keys()))
        assert payload["route_addon"]
        assert payload["goal"]
        assert payload["response_format"]


def test_base_prompt_is_compact_and_profiles_are_distinct() -> None:
    base = build_base_prompt("(Дополнительные инструменты не включены)")
    assert len(base) < 1500
    assert PROMPT_PROFILES["retrieval_profile"].route_addon != PROMPT_PROFILES["legal_qna_profile"].route_addon


def test_metrics_collect_prompt_profile_summary() -> None:
    metrics = ChatMetrics()
    metrics.record_prompt_profile("retrieval_profile", "citation_pass_rate", True)
    metrics.record_prompt_profile("retrieval_profile", "citation_pass_rate", False)
    summary = metrics.get_summary()
    assert "prompt_profiles" in summary
    assert summary["prompt_profiles"]["retrieval_profile"]["citation_pass_rate:pass"] == 1
    assert summary["prompt_profiles"]["retrieval_profile"]["citation_pass_rate:fail"] == 1
