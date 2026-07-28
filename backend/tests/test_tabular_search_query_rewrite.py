"""Tests for tabular column prompt → dual retrieval rewrite."""

from types import SimpleNamespace
from unittest.mock import patch

from app.services.tabular_search_query_rewrite import (
    TabularSearchQueryLLMOutput,
    heuristic_exact_query,
    heuristic_search_query,
    rewrite_tabular_search_query,
    sanitize_search_query,
)


def test_sanitize_strips_format_examples_from_en_prompt():
    raw = (
        "You are reviewing a US public merger agreement. "
        "Deal point: FLS MAE standard. "
        "Answer with the exact deal point value used in MAUD annotations "
        "(e.g. Yes/No, All Cash, Each Covenant). Be concise."
    )
    cleaned = sanitize_search_query(raw)
    assert "yes/no" not in cleaned.lower()
    assert "all cash" not in cleaned.lower()
    assert "each covenant" not in cleaned.lower()
    assert "fls" in cleaned.lower() or "mae" in cleaned.lower() or "standard" in cleaned.lower()


def test_heuristic_uses_label_when_prompt_is_instructional():
    out = heuristic_search_query(
        "найди и пришли полностью",
        column_type="text",
        column_label="ПРЕДМЕТ ДОГОВОРА",
    )
    assert out == "ПРЕДМЕТ ДОГОВОРА"


def test_heuristic_exact_query_from_punkt():
    assert heuristic_exact_query("пункт 1.4") == "1.4"
    assert heuristic_exact_query("ПРЕДМЕТ ДОГОВОРА") is None


def test_rewrite_skips_llm_for_compact_prompt(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="дата подписания договора",
        column_label="Дата",
        column_type="date",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query"
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=True)
    llm.assert_not_called()
    assert "дата" in result.search_query.lower()
    assert result.method in {"heuristic", "passthrough"}
    assert result.exact_query is None


def test_rewrite_uses_llm_for_instructional_prompt(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="найди в документе раздел ПРЕДМЕТ ДОГОВОРА и пришли мне его полностью",
        column_label="Предмет",
        column_type="text",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="ПРЕДМЕТ ДОГОВОРА",
            exact_query=None,
            rationale="section_title",
        ),
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=True)
    llm.assert_called_once()
    assert result.method == "llm"
    assert result.search_query == "ПРЕДМЕТ ДОГОВОРА"
    assert result.exact_query is None
    assert "найди" in result.source_query.lower()


def test_rewrite_llm_dual_query_punkt(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="найди пункт 1.4 и пришли полностью",
        column_label="п. 1.4",
        column_type="verbatim",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="пункт 1.4",
            exact_query="1.4",
            rationale="clause",
        ),
    ):
        result = rewrite_tabular_search_query(column, allow_llm=True)
    assert result.method == "llm"
    assert result.search_query == "пункт 1.4"
    assert result.exact_query == "1.4"


def test_rewrite_heuristic_fills_exact_when_llm_omits(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="найди пункт 1.4 и пришли полностью",
        column_label="п.1.4",
        column_type="verbatim",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="гарантии заказчика",
            exact_query=None,
            rationale="topic",
        ),
    ):
        result = rewrite_tabular_search_query(column, allow_llm=True)
    assert result.exact_query == "1.4"


def test_rewrite_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="найди раздел ЦЕНА ДОГОВОРА и пришли полностью",
        column_label="Цена",
        column_type="text",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        side_effect=RuntimeError("boom"),
    ):
        result = rewrite_tabular_search_query(column, allow_llm=True)
    assert result.method == "fallback"
    assert "найди" not in result.search_query.lower()
    assert "ЦЕНА" in result.search_query.upper() or "Цена" in result.search_query


def test_rewrite_disabled_uses_legacy_build_retrieval_query(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: False,
    )
    column = SimpleNamespace(
        prompt="Какая дата?",
        column_label="Дата",
        column_type="text",
    )
    result = rewrite_tabular_search_query(column, allow_llm=True)
    assert result.method == "disabled"
    assert result.search_query == "Какая дата?"


def test_o_chem_prompt_is_instructional_and_uses_label():
    from app.services.tabular_search_query_rewrite import (
        _looks_like_instruction,
        heuristic_search_query,
    )

    assert _looks_like_instruction("о чем пункт пункт 2.1")
    cleaned = heuristic_search_query(
        "о чем пункт пункт 2.1",
        column_type="text",
        column_label="пункт 2.1",
    )
    assert cleaned == "пункт 2.1"


def test_rewrite_yes_no_neustoyka_gets_lexical_terms_and_calls_llm(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="Предусмотрена ли в договоре неустойка или штраф за просрочку?",
        column_label="Есть неустойка?",
        column_type="yes_no",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="неустойка штраф просрочка ответственность",
            lexical_terms=["неустойка", "штраф", "пеня", "просрочка"],
            exact_query=None,
            rationale="yes_no_liability",
        ),
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=True)
    llm.assert_called_once()
    assert result.method == "llm"
    assert "предусмотрена" not in result.search_query.lower()
    terms = " ".join(result.lexical_terms).lower()
    assert "неустойка" in terms
    assert "штраф" in terms
    assert result.exact_query is None


def test_heuristic_yes_no_strips_interrogative_to_content_terms():
    out = heuristic_search_query(
        "Предусмотрена ли в договоре неустойка или штраф за просрочку?",
        column_type="yes_no",
        column_label="Есть неустойка?",
    )
    lower = out.lower()
    assert "неустойка" in lower or "штраф" in lower
    assert "предусмотрена ли" not in lower


def test_allow_llm_false_never_calls_model(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="найди предмет договора полностью пожалуйста",
        column_label="Предмет",
        column_type="text",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query"
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=False)
    llm.assert_not_called()
    assert result.method in {"heuristic", "passthrough"}
    assert result.search_query


def test_llm_output_accepts_legacy_search_query_alias():
    out = TabularSearchQueryLLMOutput(search_query="ПРЕДМЕТ ДОГОВОРА", rationale="x")
    assert out.semantic_query == "ПРЕДМЕТ ДОГОВОРА"


def test_llm_output_rejects_nullish_semantic_as_empty():
    out = TabularSearchQueryLLMOutput(
        semantic_query="null",
        exact_query="1.4",
        rationale="null",
    )
    assert out.semantic_query == ""
    assert out.exact_query == "1.4"
    assert out.rationale == ""


def test_rewrite_fills_heuristic_when_llm_semantic_is_null_string(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="пришли мне пункт 1.4",
        column_label="пункт 1.4",
        column_type="verbatim",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="null",
            exact_query="1.4",
            rationale="null",
        ),
    ):
        result = rewrite_tabular_search_query(column, allow_llm=True)
    assert result.method == "llm"
    assert result.exact_query == "1.4"
    assert result.search_query != "null"
    assert "1.4" in result.search_query
    assert "nullish" in result.rationale


def test_english_analyst_label_forces_llm_and_keeps_multi_query(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="FLS MAE standard",
        column_label="FLS MAE standard",
        column_type="text",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="Material Adverse Effect definition",
            search_queries=[
                "Material Adverse Effect",
                "would reasonably be expected to",
                "taken as a whole",
            ],
            lexical_terms=[
                "Material Adverse Effect",
                "reasonably be expected",
                "taken as a whole",
            ],
            rationale="defined_term_expansion",
        ),
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=True)
    llm.assert_called_once()
    assert result.method == "llm"
    assert "Material Adverse Effect" in result.search_query
    assert len(result.search_queries) >= 2
    assert any("reasonably" in q.lower() for q in result.search_queries)
    joined = " ".join(result.lexical_terms).lower()
    assert "material adverse effect" in joined


def test_russian_compact_topic_still_skips_llm(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="дата подписания договора",
        column_label="Дата",
        column_type="date",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query"
    ) as llm:
        result = rewrite_tabular_search_query(column, allow_llm=True)
    llm.assert_not_called()
    assert result.method in {"heuristic", "passthrough"}
    assert result.search_queries
    assert result.search_queries[0] == result.search_query


def test_llm_output_normalizes_search_queries():
    out = TabularSearchQueryLLMOutput(
        semantic_query="предмет договора",
        search_queries=["предмет договора", "предмет договора", "существенные условия"],
    )
    assert out.search_queries == ["предмет договора", "существенные условия"]


def test_prefer_expanded_semantic_when_label_kept(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_search_query_rewrite.tabular_search_query_rewrite_enabled",
        lambda: True,
    )
    column = SimpleNamespace(
        prompt="FLS MAE standard",
        column_label="FLS MAE standard",
        column_type="text",
    )
    with patch(
        "app.services.tabular_search_query_rewrite._llm_rewrite_search_query",
        return_value=TabularSearchQueryLLMOutput(
            semantic_query="FLS MAE standard",
            search_queries=[
                "FLS MAE standard",
                "Material Adverse Effect would reasonably be expected",
                "taken as a whole",
            ],
            lexical_terms=["Material Adverse Effect"],
            rationale="partial",
        ),
    ):
        result = rewrite_tabular_search_query(column, allow_llm=True)
    assert "Material Adverse Effect" in result.search_query
    assert result.search_query != "FLS MAE standard"

