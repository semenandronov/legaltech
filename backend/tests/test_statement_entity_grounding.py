"""Entity token grounding for counterparty questions."""

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_entity_grounding import select_best_entity_token


def _row(description: str) -> CaseFileTransaction:
    row = CaseFileTransaction()
    row.description = description
    return row


def test_surname_with_no_hits_does_not_fall_back_to_andre_prefix():
    rows = [
        _row("Перевод от А. Андрей Викторович. Операция по карте"),
        _row("Перевод от А. Семён Андреевич. Операция по карте"),
    ]
    token = select_best_entity_token(
        "есть ли операции с Андроновым Андреем Викторовичем?",
        rows=rows,
    )
    assert token
    assert "андрон" in token.lower()
    assert token.lower() != "андре"


def test_andronov_question_prefers_surname_stem_over_andre():
    rows = [
        _row("Перевод от А. Андрей Викторович"),
    ]
    token = select_best_entity_token(
        "Андронов Андрей Викторович",
        rows=rows,
    )
    assert "андрон" in token.lower()
