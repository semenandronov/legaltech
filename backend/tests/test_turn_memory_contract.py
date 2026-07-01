"""TurnMemoryContract — unified memory routing per turn."""
from unittest.mock import patch

import pytest

from app.services.chat.session_context_retrieval import is_memory_only_turn
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence
from app.services.chat.turn_memory_contract import (
    apply_structured_plane_to_contract,
    memory_contract_skips_structured_router,
    resolve_turn_memory_contract,
)


@pytest.fixture(autouse=True)
def _disable_live_llm_judge(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "TURN_CONTEXT_LLM_JUDGE_ENABLED", False)


def _shak_prior_turns() -> list[SessionMessageTurn]:
    return [
        SessionMessageTurn(message_id="u1", role="user", content="о чем возражение шиошвили"),
        SessionMessageTurn(
            message_id="a1",
            role="assistant",
            content="Возражение касается оспаривания сделок.",
            evidence={
                "citations": [
                    {"source_id": "shak-file", "chunk_id": "c-1", "quote": "фрагмент"},
                ],
                "retrieval_metadata": {
                    "turn_state": {
                        "domain": "document_rag",
                        "rag_file_ids": ["shak-file"],
                        "topic_file_ids": ["shak-file"],
                    }
                },
            },
        ),
    ]


def test_drill_down_is_scoped_document_not_chat_replay():
    contract = resolve_turn_memory_contract(
        question="подробнее про возражение",
        turns=_shak_prior_turns(),
    )
    assert contract.execution_mode == "scoped_document"
    assert contract.turn_context.referential_kind == "scoped_deep_read"
    assert contract.turn_context.needs_document_retrieval is True
    assert not memory_contract_skips_structured_router(contract)


def test_memory_synthesis_is_chat_replay():
    contract = resolve_turn_memory_contract(
        question="кратко повтори итог",
        turns=_shak_prior_turns(),
    )
    assert contract.execution_mode == "chat_replay"
    assert contract.turn_context.referential_kind == "memory_synthesis"
    assert memory_contract_skips_structured_router(contract)


def test_is_memory_only_turn_reads_execution_mode():
    assert is_memory_only_turn(
        {
            "execution_mode": "chat_replay",
            "prior_answer_available": True,
        }
    )
    assert not is_memory_only_turn(
        {
            "execution_mode": "scoped_document",
            "prior_answer_available": True,
        }
    )


def test_sql_follow_up_structured_mode():
    prior = PriorTurnEvidence(
        message_id="m1",
        assistant_excerpt="В мае 2026 было 106 операций.",
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
    turns = [
        SessionMessageTurn(message_id="u0", role="user", content="сколько в мае"),
        SessionMessageTurn(
            message_id="a0",
            role="assistant",
            content=prior.assistant_excerpt,
            evidence={"retrieval_metadata": prior.retrieval_metadata},
        ),
    ]
    with patch(
        "app.services.chat.turn_delta_resolver.turn_delta_llm_enabled",
        return_value=False,
    ):
        contract = resolve_turn_memory_contract(
            question="а в июне 2026",
            turns=turns,
        )
    assert contract.execution_mode == "structured_sql"
    assert contract.information_need == "tabular_aggregate"
    assert contract.execution_contract.sql_plan_hints.get("date_from") == "01.06.2026"
    assert contract.execution_mode == "structured_sql"


def test_apply_hybrid_plane_refines_mode():
    contract = resolve_turn_memory_contract(
        question="сколько операций в мае 2026",
        turns=[],
    )
    refined = apply_structured_plane_to_contract(contract, data_plane="hybrid")
    assert refined.execution_mode == "hybrid"
