"""Tests for chat instrument / mode policy."""
from __future__ import annotations

from app.services.chat.chat_instrument_policy import (
    normalize_chat_instrument_flags,
    normalize_editor_mode_for_legal_research,
)


def test_draft_mode_clears_legal_corpus():
    draft, legal, practice = normalize_chat_instrument_flags(
        draft_mode=True,
        legal_research=True,
        use_legal_corpus=True,
        court_practice=True,
    )
    assert draft is True
    assert legal is False
    assert practice is False


def test_legal_corpus_when_not_draft():
    draft, legal, practice = normalize_chat_instrument_flags(
        draft_mode=False,
        use_legal_corpus=True,
    )
    assert draft is False
    assert legal is True
    assert practice is False


def test_both_flags_draft_wins():
    draft, legal, practice = normalize_chat_instrument_flags(
        draft_mode=True,
        use_legal_corpus=True,
        court_practice=True,
    )
    assert draft is True
    assert legal is False
    assert practice is False


def test_court_practice_with_legal_corpus():
    draft, legal, practice = normalize_chat_instrument_flags(
        draft_mode=False,
        legal_research=True,
        court_practice=True,
    )
    assert draft is False
    # практика приоритетнее справочника
    assert legal is False
    assert practice is True


def test_editor_legal_research_forces_ask():
    assert normalize_editor_mode_for_legal_research("edit", legal_research=True) == "ask"
    assert normalize_editor_mode_for_legal_research("draft", legal_research=True) == "ask"
    assert normalize_editor_mode_for_legal_research("edit", legal_research=False) == "edit"
