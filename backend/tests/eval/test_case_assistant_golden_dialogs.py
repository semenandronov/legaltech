"""
Golden dialog scenarios for case assistant turn contract (unit-level, no live DB).

Validates count→sum follow-up, narrative routing invariants, and drill-down need.
"""
from unittest.mock import patch

from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.structured_data_capability import enforce_data_plane_capability
from app.services.chat.tabular_metric_slot import resolve_sql_metric_dimension
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence
from app.services.chat.turn_delta_resolver import resolve_turn_delta
from app.services.chat.turn_execution_contract import resolve_turn_execution_contract


def _prior_count_may() -> PriorTurnEvidence:
    return PriorTurnEvidence(
        message_id="m1",
        assistant_excerpt="В мае 2026 года было совершено 106 операций.",
        citations=(),
        retrieval_metadata={
            "turn_state": {
                "domain": "statement_analytics",
                "statement_file_id": "40c0ebb9-3863-4118-9213-d666d6687c44",
                "operation": "count",
                "date_from": "01.05.2026",
                "date_to": "31.05.2026",
                "structured_data_plane": "sql",
            }
        },
    )


def test_golden_count_then_sum_follow_up():
    """«на какую сумму» после count наследует период и переключает metric slot."""
    with patch(
        "app.services.chat.turn_delta_resolver.turn_delta_llm_enabled",
        return_value=False,
    ):
        contract = resolve_turn_execution_contract(
            question="на какую сумму",
            turn_context={
                "referential_kind": "scoped_deep_read",
                "standalone_query": "на какую сумму",
                "original_question": "на какую сумму",
            },
            prior_evidence=_prior_count_may(),
        )
    assert contract.sql_plan_hints.get("operation") == "sum"
    assert contract.sql_plan_hints.get("date_from") == "01.05.2026"
    assert contract.information_need == "tabular_aggregate"
    assert "01.05.2026" in contract.effective_query or "40c0ebb9" in contract.effective_query


def test_golden_narrative_statement_question_routes_rag():
    """Вопрос о содержании выписки не должен идти в SQL plane."""
    plane, reason = enforce_data_plane_capability(
        "sql",
        "document_narrative",
        has_sql_tables=True,
    )
    assert plane == "rag"
    assert reason


def test_golden_shak_drill_down_need():
    prior = ConversationTurnState(
        domain="document_rag",
        rag_file_ids=("shak-file",),
        topic_file_ids=("shak-file",),
    )
    with patch(
        "app.services.chat.turn_delta_resolver.turn_delta_llm_enabled",
        return_value=False,
    ):
        delta = resolve_turn_delta(
            question="подробнее",
            prior_turn_state=prior,
            referential_kind="scoped_deep_read",
            prior_evidence=PriorTurnEvidence(
                message_id="m2",
                assistant_excerpt="Возражение ШАК касается ...",
                citations=(CitationAnchor(source_id="shak-file", quote_excerpt="фрагмент"),),
                retrieval_metadata={"turn_state": prior.to_dict()},
            ),
        )
    assert delta.information_need == "document_drill_down"
    assert "ШАК" in delta.effective_query or "возражение" in delta.effective_query.lower()


def test_metric_slot_stems_not_phrase_list():
    assert resolve_sql_metric_dimension("на какую сумму") == "sum"
    assert resolve_sql_metric_dimension("сколько операций") == "count"
    assert resolve_sql_metric_dimension("в мае") == "inherit"
