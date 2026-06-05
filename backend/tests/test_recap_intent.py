from __future__ import annotations

from app.services.chat.recap_intent import is_recap_query


def test_is_recap_query_positive():
    assert is_recap_query("повтори про то дело") is True
    assert is_recap_query("Напомни, какое дело ты приводил?") is True


def test_is_recap_query_negative_long_text():
    assert is_recap_query("а" * 2000) is False


def test_is_recap_query_negative_empty():
    assert is_recap_query("") is False
    assert is_recap_query("   ") is False

