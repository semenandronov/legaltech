"""Draft agent module smoke tests."""
from __future__ import annotations

from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_agent.prompts import DRAFT_AGENT_SYSTEM_PROMPT
from app.services.draft_agent.schemas import DraftCalculatorInput, DraftWriteDocumentInput


def test_draft_agent_context_thread_id():
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    assert ctx.thread_id == "draft-agent-c1-s1"


def test_draft_agent_prompt_mentions_tools():
    assert "draft_case_search" in DRAFT_AGENT_SYSTEM_PROMPT
    assert "draft_legal_search" in DRAFT_AGENT_SYSTEM_PROMPT
    assert "draft_court_practice_search" in DRAFT_AGENT_SYSTEM_PROMPT
    assert "draft_calculator" in DRAFT_AGENT_SYSTEM_PROMPT
    assert "draft_write_document" in DRAFT_AGENT_SYSTEM_PROMPT
    assert "write_todos" in DRAFT_AGENT_SYSTEM_PROMPT


def test_draft_calculator_schema():
    payload = DraftCalculatorInput(
        principal_amount="1 000 000",
        event_date="2024-06-01",
        payment_term_business_days=10,
        penalty_rate_percent_per_day=0.1,
    )
    assert payload.payment_term_business_days == 10


def test_draft_write_document_schema_min_length():
    payload = DraftWriteDocumentInput(
        document_instruction="Составь исковое заявление о взыскании задолженности по договору поставки с указанием сторон и сумм.",
    )
    assert "исковое" in payload.document_instruction
