"""Tests for Adaptive RAG latency path (FAST vs HEAVY gate)."""
from app.services.chat.case_latency_path import (
    apply_latency_path_to_budget,
    resolve_case_latency_path,
)
from app.services.chat.referential_llm_judge import classify_referential_kind_judge


def test_default_document_qa_is_fast():
    path = resolve_case_latency_path(question="какая сумма займа в договоре?")
    assert path.kind == "fast"
    assert path.skip_turn_context_llm is True
    assert path.skip_structured_data_router is True
    # Fast lite LLM file-scope is ON by default; other prep LLMs stay skipped.
    assert path.skip_llm_document_scope is False
    assert path.force_execution_tier == "instant"
    assert path.rerank_policy == "skip"


def test_fast_llm_file_scope_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.case_latency_path.config.CASE_ASSISTANT_FAST_LLM_FILE_SCOPE_ENABLED",
        False,
    )
    path = resolve_case_latency_path(question="какая сумма займа в договоре?")
    assert path.kind == "fast"
    assert path.skip_llm_document_scope is True


def test_court_practice_alone_stays_fast():
    path = resolve_case_latency_path(
        question="какая позиция судов по неустойке?",
        court_practice=True,
    )
    assert path.kind == "fast"
    assert "court_practice" in path.reason


def test_ui_deep_think_is_heavy():
    path = resolve_case_latency_path(question="какая сумма?", deep_think=True)
    assert path.kind == "heavy"
    assert path.skip_turn_context_llm is False


def test_ui_legal_research_is_heavy():
    path = resolve_case_latency_path(question="статья 395 гк", legal_research=True)
    assert path.kind == "heavy"


def test_ui_draft_is_heavy():
    path = resolve_case_latency_path(question="напиши возражение", draft_mode=True)
    assert path.kind == "heavy"


def test_contradiction_intent_is_heavy():
    path = resolve_case_latency_path(
        question="найди противоречия между договором и актом",
        corpus_size=5,
    )
    assert path.kind == "heavy"


def test_greeting_is_no_retrieval():
    path = resolve_case_latency_path(question="спасибо")
    assert path.kind == "no_retrieval"


def test_memory_synthesis_referential_is_memory():
    path = resolve_case_latency_path(
        question="ключевые выводы",
        referential_kind="memory_synthesis",
    )
    assert path.kind == "memory"


def test_apply_latency_path_tightens_budget():
    path = resolve_case_latency_path(question="кто истец?")
    bp = apply_latency_path_to_budget(
        {
            "execution_tier": "standard",
            "rerank_enabled": True,
            "max_retrieval_rounds": 3,
            "max_context_chars": 16000,
            "max_tokens": 800,
        },
        path,
    )
    assert bp["execution_tier"] == "instant"
    assert bp["rerank_enabled"] is False
    assert bp["skip_llm_document_scope"] is False
    assert bp["max_retrieval_rounds"] <= 2
    assert bp["max_retrieval_rounds"] >= 1
    assert bp["latency_path"]["kind"] == "fast"
    assert bp["compact_system_prompt"] is True
    assert bp["max_context_chars"] <= 3500
    assert bp["max_tokens"] <= 300
    assert bp["tier_contract"]["llm_max_tokens"] <= 300


def test_judge_skips_llm_when_disallowed():
    result = classify_referential_kind_judge(
        question="а что насчёт сроков поставки в целом по делу?",
        has_prior=True,
        allow_llm=False,
    )
    assert result.referential_kind == "none"
    assert result.resolver == "regex_fallback"
    assert "latency_path_skip_llm_judge" in result.reason
