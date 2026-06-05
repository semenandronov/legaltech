"""Evidence plan — intent-specific latency contract."""
from app.services.chat.case_assistant_intent import resolve_case_assistant_intent
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.evidence_plan import apply_evidence_plan, build_evidence_plan
from app.services.chat.execution_tier import attach_pipeline_budget_for_tier, resolve_execution_tier


def test_overview_uses_summary_path_and_standard_tier(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True

    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "multi_doc_synthesis",
        corpus_size=4,
        question="о чем документы кратко",
        attached_files_count=0,
    )
    assert profile["primary_intent"] == "case_corpus_overview"
    assert profile["execution_tier"] == "standard"
    assert profile["retrieval_path"] == "summary_overview"
    assert profile["evidence_mode"] == "case_metadata"
    assert profile["recall_k"] == 0
    assert profile["rerank_enabled"] is False


def test_named_doc_not_drill_down():
    intent = resolve_case_assistant_intent(
        question="о чем Договор от 02.02.2024",
        corpus_size=4,
    )
    assert intent.primary == "standard_case_qa"
    assert intent.task_type == "single_doc_extraction"
    assert intent.primary != "drill_down"


def test_evidence_plan_caps_drill_down_rounds():
    intent = resolve_case_assistant_intent(question="подробнее про возражение")
    tier, _ = resolve_execution_tier(
        question="подробнее про возражение",
        task_type=intent.task_type,
        depth_tier=intent.depth_tier,
        primary_intent=intent.primary,
    )
    base = attach_pipeline_budget_for_tier(
        {"name": "fast_legal_reasoning", "max_sources": 8, "max_context_chars": 16000, "max_tokens": 1500},
        tier,
        primary_intent=intent.primary,
    )
    refined = apply_evidence_plan(base, intent=intent)
    assert refined["max_retrieval_rounds"] <= 1


def test_build_evidence_plan_narrow_fact_uses_light_rerank():
    intent = resolve_case_assistant_intent(question="какая сумма в п. 6.2", corpus_size=3)
    plan = build_evidence_plan(
        intent=intent,
        execution_tier="instant",
        rerank_enabled=False,
        max_retrieval_rounds=2,
    )
    assert plan.rerank_enabled is True
    assert plan.rerank_tier == "light"
    assert plan.parent_context_enabled is False
    assert plan.max_retrieval_rounds == 1
