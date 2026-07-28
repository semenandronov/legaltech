from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_counterparty_pipeline import (
    compose_counterparty_lawyer_answer,
    investigate_counterparty,
)
from app.services.chat.statement_table_session import StatementTableSession


def _row(description: str, amount: str = "1000") -> CaseFileTransaction:
    return CaseFileTransaction(
        id="r1",
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_datetime_text="01.01.2026 12:00",
        amount_rub=Decimal(amount),
        amount_raw=amount,
        description=description,
        row_columns={},
        page_start=1,
    )


def test_investigate_finds_name_patronymic_when_surname_absent_in_text():
    rows = [
        _row("Перевод от Андрей Викторович И. по договору"),
        _row("Комиссия банка"),
    ]
    inv = investigate_counterparty(
        "Есть ли операции с Андроновым Андреем Викторовичем?",
        rows,
    )
    assert inv.surname_label == "Андронов"
    assert inv.surname_profile is not None
    assert inv.surname_profile.op_count == 0  # type: ignore[union-attr]
    assert inv.name_patronymic_parts
    assert inv.name_patronymic_profile is not None
    assert inv.name_patronymic_profile.op_count == 1  # type: ignore[union-attr]


def test_compose_answer_states_no_surname_but_lists_name_patronymic_hits():
    rows = [_row("Перевод от Андрей Викторович И.")]
    inv = investigate_counterparty(
        "Есть ли операции с Андроновым Андреем Викторовичем?",
        rows,
    )
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="vypiska.pdf",
        question="Есть ли операции с Андроновым Андреем Викторовичем?",
        rows=rows,
    )
    answer = compose_counterparty_lawyer_answer(
        session=session,
        question=session.question,
        investigation=inv,
    )
    assert "Андронов" in answer
    assert "0" in answer or "нет" in answer.lower() or "не найден" in answer.lower()
    assert "андрей" in answer.lower() and "викторович" in answer.lower()
