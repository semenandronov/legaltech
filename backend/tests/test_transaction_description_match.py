"""Tests for whole-token description matching (not substring)."""

from sqlalchemy import select

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.transaction_description_match import (
    description_token_match,
    postgres_token_boundary_pattern,
)


def test_token_match_accepts_merchant_code_parts():
    assert description_token_match("Оплата VK*1234*ADS Moskva RUS", "VK")
    assert description_token_match("Оплата в YANDEX*4121*GO Moskva RUS", "Yandex")
    assert description_token_match("Перевод Иванову Ивану", "Иванов")


def test_token_match_rejects_embedded_letters():
    assert not description_token_match("Оплата AVK STORE", "VK")
    assert not description_token_match("FOOVKBAR payment", "VK")
    assert not description_token_match("SVK*99*SHOP", "VK")


def test_postgres_pattern_uses_boundaries():
    pattern = postgres_token_boundary_pattern("VK")
    assert pattern.startswith("(^|")
    assert "VK" in pattern
    # Special regex chars in needle are escaped
    assert r"\." in postgres_token_boundary_pattern("a.b") or "a\\.b" in postgres_token_boundary_pattern(
        "a.b"
    )


def test_apply_query_filters_uses_token_regex_for_description_contains():
    query = select(CaseFileTransaction)
    filtered = CaseFileTransactionService._apply_query_filters(
        query,
        case_id="case-1",
        file_id="stmt-1",
        description_contains="VK",
    )
    compiled = str(filtered.compile(compile_kwargs={"literal_binds": True}))
    assert "~*" in compiled
    assert "VK" in compiled
    assert "%VK%" not in compiled


def test_apply_query_filters_keeps_substring_ilike_for_ui_search():
    query = select(CaseFileTransaction)
    filtered = CaseFileTransactionService._apply_query_filters(
        query,
        case_id="case-1",
        file_id="stmt-1",
        search="Yan",
    )
    compiled = str(filtered.compile(compile_kwargs={"literal_binds": True}))
    assert "like" in compiled.lower()
    assert "%Yan%" in compiled
    assert "~*" not in compiled
