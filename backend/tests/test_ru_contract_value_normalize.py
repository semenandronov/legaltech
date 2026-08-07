"""Tests for RU contract number / money normalization."""

from app.services.ru_contract_value_normalize import (
    money_plain_normalized,
    normalize_ru_contract_number,
    normalize_ru_money_amount,
)


def test_normalize_contract_number_strips_glued_cyrillic():
    assert normalize_ru_contract_number("03/03-2022/1от") == "03/03-2022/1"
    assert normalize_ru_contract_number("20/01-2022/1") == "20/01-2022/1"
    assert normalize_ru_contract_number(" №02/2022 ") == "02/2022"


def test_normalize_money_collapses_broken_ocr_spaces():
    assert normalize_ru_money_amount("959 335") == "959 335 руб."
    assert normalize_ru_money_amount("959 3 35") == "959 335 руб."
    assert normalize_ru_money_amount("959335 руб.") == "959 335 руб."
    assert money_plain_normalized("959 3 35 руб.") == "959335"
