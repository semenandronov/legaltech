"""Unit tests for value-level evidence grounding."""

from app.services.tabular_evidence_grounding import value_grounded_in_corpus


def test_inn_digits_in_ocr_noisy_corpus():
    corpus = "ИНН 9701 032 688"
    assert value_grounded_in_corpus("9701032688", column_type="text", corpus=corpus)


def test_case_number_normalized():
    corpus = "Дело № А40-4022/2024 в Арбитражном суде"
    assert value_grounded_in_corpus("A40-4022/2024", column_type="text", corpus=corpus)


def test_amount_integer_core():
    corpus = "Сумма 1 234 567,89 руб."
    assert value_grounded_in_corpus("1234567.89 RUB", column_type="currency", corpus=corpus)
