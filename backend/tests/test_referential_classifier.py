"""Referential classifier — Phase 1 structural turn kinds."""
from app.services.chat.referential_classifier import (
    classify_referential_kind,
    is_memory_synthesis_question,
    needs_prior_turn_resolution,
)


def test_memory_synthesis_patterns():
    assert is_memory_synthesis_question("КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?")
    assert is_memory_synthesis_question("итог?")
    assert not is_memory_synthesis_question("расскажи про договор")


def test_classify_memory_synthesis_with_prior():
    kind = classify_referential_kind("резюме", has_prior=True)
    assert kind == "memory_synthesis"


def test_classify_scoped_deep_read_deictic():
    kind = classify_referential_kind("А эта сумма — откуда?", has_prior=True)
    assert kind == "scoped_deep_read"


def test_classify_scoped_deep_read_entity_pointer():
    assert needs_prior_turn_resolution("что в п. 2?")
    kind = classify_referential_kind("что в п. 2?", has_prior=True)
    assert kind == "scoped_deep_read"


def test_classify_none_without_prior():
    assert classify_referential_kind("итог?", has_prior=False) == "none"


def test_classify_none_for_explicit_new_topic():
    q = "найди практику по арбитражным сборам в другом деле и сравни с нашим"
    assert classify_referential_kind(q, has_prior=True) == "none"


def test_memory_synthesis_wins_over_deictic():
    kind = classify_referential_kind("ключевые выводы по этому", has_prior=True)
    assert kind == "memory_synthesis"
