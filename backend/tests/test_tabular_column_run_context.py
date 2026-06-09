"""Tests for tabular column run context (one embedding per column)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.tabular_column_run_context import (
    TabularColumnRunContext,
    prepare_tabular_column_run_context,
)


def test_prepare_tabular_column_run_context_embeds_once():
    column = SimpleNamespace(prompt="Какая дата?", column_label="Дата")
    fake_vec = [0.1] * 256

    with patch("app.services.yandex_embeddings.get_yandex_embeddings") as get_emb:
        inst = get_emb.return_value
        inst.is_available.return_value = True
        inst.embed_query.return_value = fake_vec

        ctx = prepare_tabular_column_run_context(column)

    assert isinstance(ctx, TabularColumnRunContext)
    assert ctx.search_query == "Какая дата?"
    assert len(ctx.query_embedding) == 256
    inst.embed_query.assert_called_once_with("Какая дата?")


def test_prepare_tabular_column_run_context_empty_query():
    column = SimpleNamespace(prompt="", column_label="")
    with pytest.raises(ValueError, match="empty_query"):
        prepare_tabular_column_run_context(column)
