"""Tests for tabular column run context (one embedding per column)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.tabular_column_run_context import (
    TabularColumnRunContext,
    prepare_tabular_column_run_context,
)
from app.services.tabular_search_query_rewrite import TabularSearchQueryRewriteResult


def test_prepare_tabular_column_run_context_embeds_rewritten_query():
    column = SimpleNamespace(
        prompt="найди раздел ПРЕДМЕТ ДОГОВОРА и пришли полностью",
        column_label="Предмет",
        column_type="text",
    )
    fake_vec = [0.1] * 256
    rewritten = TabularSearchQueryRewriteResult(
        search_query="ПРЕДМЕТ ДОГОВОРА",
        source_query=column.prompt,
        method="llm",
        rationale="section",
        exact_query=None,
    )

    with patch(
        "app.services.tabular_column_run_context.rewrite_tabular_search_query",
        return_value=rewritten,
    ) as rewrite, patch(
        "app.services.yandex_embeddings.get_yandex_embeddings"
    ) as get_emb:
        inst = get_emb.return_value
        inst.is_available.return_value = True
        inst.embed_query.return_value = fake_vec

        ctx = prepare_tabular_column_run_context(column)

    rewrite.assert_called_once()
    assert isinstance(ctx, TabularColumnRunContext)
    assert ctx.search_query == "ПРЕДМЕТ ДОГОВОРА"
    assert ctx.exact_query is None
    assert ctx.source_query == column.prompt
    assert ctx.rewrite_method == "llm"
    assert ctx.lexical_terms == ()
    assert len(ctx.query_embedding) == 256
    inst.embed_query.assert_called_once_with("ПРЕДМЕТ ДОГОВОРА")


def test_prepare_tabular_column_run_context_keeps_lexical_terms():
    column = SimpleNamespace(
        prompt="Предусмотрена ли неустойка?",
        column_label="Неустойка",
        column_type="yes_no",
    )
    fake_vec = [0.3] * 256
    rewritten = TabularSearchQueryRewriteResult(
        search_query="неустойка штраф просрочка",
        source_query=column.prompt,
        method="llm",
        rationale="yes_no",
        exact_query=None,
        lexical_terms=("неустойка", "штраф", "пеня"),
    )
    with patch(
        "app.services.tabular_column_run_context.rewrite_tabular_search_query",
        return_value=rewritten,
    ), patch("app.services.yandex_embeddings.get_yandex_embeddings") as get_emb:
        inst = get_emb.return_value
        inst.is_available.return_value = True
        inst.embed_query.return_value = fake_vec
        ctx = prepare_tabular_column_run_context(column)
    assert ctx.lexical_terms == ("неустойка", "штраф", "пеня")
    assert ctx.search_query == "неустойка штраф просрочка"


def test_prepare_tabular_column_run_context_keeps_exact_query():
    column = SimpleNamespace(
        prompt="пункт 1.4",
        column_label="1.4",
        column_type="verbatim",
    )
    fake_vec = [0.2] * 256
    rewritten = TabularSearchQueryRewriteResult(
        search_query="пункт 1.4",
        source_query=column.prompt,
        method="heuristic",
        rationale="compact",
        exact_query="1.4",
    )
    with patch(
        "app.services.tabular_column_run_context.rewrite_tabular_search_query",
        return_value=rewritten,
    ), patch("app.services.yandex_embeddings.get_yandex_embeddings") as get_emb:
        inst = get_emb.return_value
        inst.is_available.return_value = True
        inst.embed_query.return_value = fake_vec
        ctx = prepare_tabular_column_run_context(column)
    assert ctx.exact_query == "1.4"
    inst.embed_query.assert_called_once_with("пункт 1.4")


def test_prepare_tabular_column_run_context_empty_query():
    column = SimpleNamespace(prompt="", column_label="", column_type="text")
    with patch(
        "app.services.tabular_column_run_context.rewrite_tabular_search_query",
        return_value=TabularSearchQueryRewriteResult(
            search_query="",
            source_query="",
            method="passthrough",
        ),
    ):
        with pytest.raises(ValueError, match="empty_query"):
            prepare_tabular_column_run_context(column)
