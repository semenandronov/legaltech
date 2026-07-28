"""Unit tests for quote-then-answer grounding helpers."""

import pytest

from app.services.tabular_quote_then_answer import (
    quote_grounded_in_corpus,
    tabular_quote_then_answer_enabled,
)


def test_quote_grounded_rejects_short_and_missing():
    assert not quote_grounded_in_corpus("short", "short text here")
    assert not quote_grounded_in_corpus(
        "completely different invented clause about widgets",
        "Material Adverse Effect means any change",
    )


def test_quote_grounded_head_tail_tolerance():
    head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    mid = " UNIQUE_MIDDLE_TOKEN "
    tail = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    quote = head + mid + tail
    # Corpus contains head and tail but not the middle (simulates packing cut).
    corpus = f"prefix {head} ...packed... {tail} suffix"
    assert quote_grounded_in_corpus(quote, corpus)


def test_snap_quote_recovers_near_match():
    from app.services.tabular_quote_then_answer import snap_quote_to_corpus

    corpus = (
        "Material Adverse Effect means any change, event, or effect that is materially adverse "
        "to the business of the Company."
    )
    # Model dropped a comma / slightly rewrote spacing — still mostly the same span.
    quote = (
        "Material Adverse Effect means any change event or effect that is materially adverse "
        "to the business of the Company"
    )
    snapped = snap_quote_to_corpus(quote, corpus)
    assert snapped is not None
    assert "material adverse effect" in snapped.lower()


def test_quote_then_answer_enabled_default(monkeypatch):
    monkeypatch.setattr(
        "app.config.config.TABULAR_QUOTE_THEN_ANSWER",
        True,
        raising=False,
    )
    assert tabular_quote_then_answer_enabled() is True
