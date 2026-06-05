"""Token-aware embedding splits (Yandex 2048-token ceiling)."""

import pytest

from app.services import yandex_embeddings as ye


def test_split_text_for_embedding_api_splits_long_cyrillic():
    text = ("Налогоплательщик имеет право на вычет. " * 400).strip()
    parts = ye.split_text_for_embedding_api(text)
    assert len(parts) >= 1
    max_t = ye._effective_max_embedding_tokens()
    for p in parts:
        assert ye._estimate_token_count(p) <= max_t + 32


def test_split_empty():
    assert ye.split_text_for_embedding_api("") == []
    assert ye.split_text_for_embedding_api("   ") == []


def test_short_text_single_piece():
    assert ye.split_text_for_embedding_api("Краткий текст.") == ["Краткий текст."]


def test_markdown_table_like_dense_text():
    rows = ["| a | b |", "|---|---|"] + [f"| {i} | {i * 2} |" for i in range(200)]
    text = "\n".join(rows)
    parts = ye.split_text_for_embedding_api(text)
    max_t = ye._effective_max_embedding_tokens()
    for p in parts:
        assert ye._estimate_token_count(p) <= max_t + 48
