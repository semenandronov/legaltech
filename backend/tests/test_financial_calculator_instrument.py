"""Tests for draft financial calculator (agent-driven, draft mode only)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.services.chat.draft_financial_agent import run_draft_financial_calculator_agent
from app.services.chat.financial_calculator_instrument import execute_financial_calculator
from app.services.draft_pipeline.schemas import (
    DraftTaskPlan,
    ExtractedFacts,
    FinancialLineItem,
    PenaltyTerms,
)


def _sample_facts() -> ExtractedFacts:
    return ExtractedFacts(
        document_type="исковое заявление",
        penalty_terms=PenaltyTerms(
            payment_term_value=10,
            payment_term_unit="business_days",
            act_date="2025-06-02",
            penalty_rate_percent_per_day="0.1",
            principal_amount="4500000",
            penalty_end_date="2026-06-07",
            partial_payments=[
                FinancialLineItem(date="2025-06-25", amount="1500000", source="112"),
            ],
        ),
    )


def test_execute_financial_calculator_applies_when_terms_complete():
    updated, meta = execute_financial_calculator(_sample_facts(), reason="неустойка в иске")
    assert meta["applied"] is True
    assert updated.financial.verified is not None
    assert updated.financial.verified.penalty_days == 355


def test_execute_financial_calculator_insufficient_terms():
    facts = ExtractedFacts(document_type="ходатайство")
    updated, meta = execute_financial_calculator(facts, reason="test")
    assert meta["applied"] is False
    assert meta["skip_reason"] == "insufficient_structured_terms"
    assert updated.financial.verified is None


@patch("app.services.chat.draft_financial_agent.create_react_agent")
@patch("app.services.chat.draft_financial_agent.create_legal_llm")
def test_draft_agent_skips_tool_when_not_needed(mock_llm, mock_create_agent):
    mock_create_agent.return_value.invoke.return_value = {
        "messages": [
            HumanMessage(content="brief"),
            AIMessage(content="Документ без денежных требований — расчёт не нужен."),
        ]
    }

    facts = _sample_facts()
    updated, meta = run_draft_financial_calculator_agent(
        user_prompt="Составь доверенность",
        facts=facts,
    )

    assert meta["tool_called"] is False
    assert meta["applied"] is False
    assert "доверен" in meta["agent_skipped_reason"].lower() or meta["agent_skipped_reason"]
    assert updated.financial.verified is None



@patch("app.services.chat.draft_financial_agent.create_react_agent")
@patch("app.services.chat.draft_financial_agent.create_legal_llm")
def test_draft_agent_tool_invocation_updates_facts(mock_llm, mock_create_agent):
    """End-to-end through real StructuredTool inside agent factory."""
    facts = _sample_facts()
    tool_holder = {"fn": None}

    def capture_create(model, tools, prompt):
        tool_holder["fn"] = tools[0].func
        agent = MagicMock()

        def invoke(state, config=None):
            result_text = tool_holder["fn"](reason="неустойка по договору поставки")
            return {
                "messages": [
                    HumanMessage(content="x"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "compute_contract_financials",
                                "args": {"reason": "неустойка"},
                                "id": "tc1",
                            }
                        ],
                    ),
                    AIMessage(content=f"done {result_text[:20]}"),
                ]
            }

        agent.invoke = invoke
        return agent

    mock_create_agent.side_effect = capture_create

    updated, meta = run_draft_financial_calculator_agent(
        user_prompt="иск о взыскании неустойки",
        facts=facts,
    )

    assert meta["tool_called"] is True
    assert meta["applied"] is True
    assert updated.financial.verified is not None
    assert updated.financial.verified.penalty_days == 355
