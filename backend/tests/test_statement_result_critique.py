"""Tests for statement execution critique before answering."""

import json

from app.services.chat.statement_result_critique import critique_statement_execution
from app.services.chat.statement_table_session import StatementTableSession


def test_critique_accepts_zero_hits_when_token_matches_surname():
    session = StatementTableSession(
        case_id="c1",
        file_id="f1",
        file_label="v.pdf",
        question="есть ли операции с Андроновым Андреем Викторовичем?",
        rows=[],
    )
    session.tool_calls.append("resolve_entity")
    session.tool_calls.append("counterparty_dossier")
    log = [
        json.dumps({"grounded_token": "Андронов", "match_count": 0}, ensure_ascii=False),
        json.dumps({"token": "Андронов", "op_count": 0, "matched": False}, ensure_ascii=False),
    ]
    result = critique_statement_execution(
        question=session.question,
        session=session,
        execution_log=log,
    )
    assert result.ok


def test_critique_rejects_short_token_for_surname_question():
    session = StatementTableSession(
        case_id="c1",
        file_id="f1",
        file_label="v.pdf",
        question="были ли операции с Андроповым Андреем Викторовичем?",
        rows=[],
    )
    session.tool_calls.append("resolve_entity")
    session.tool_calls.append("counterparty_dossier")
    log = [
        json.dumps({"grounded_token": "Андре", "match_count": 171}, ensure_ascii=False),
        json.dumps(
            {
                "match_count": 171,
                "examples": ["Оплата Андрееву И.П.", "Сервис Андре"],
            },
            ensure_ascii=False,
        ),
    ]
    result = critique_statement_execution(
        question=session.question,
        session=session,
        execution_log=log,
    )
    assert not result.ok
    assert any("Андропов" in i or "якорь" in i.lower() or "корот" in i.lower() for i in result.issues)
