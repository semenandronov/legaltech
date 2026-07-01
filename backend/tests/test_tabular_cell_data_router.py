"""Tests for tabular cell SQL/RAG routing (SQL-flagged files)."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.chat.structured_data_router import StructuredDataRouterResult
from app.services.tabular_cell_data_router import (
    route_tabular_cell_data_plane,
    tabular_cell_data_router_enabled,
)
from app.services.tabular_cell_pipeline import (
    format_routed_cell_context,
    run_tabular_cell_extraction,
)
from app.services.tabular_cell_sql_fetch import TabularCellSqlContext
from app.services.tabular_review_models import TabularCellExtractionModel


def test_format_routed_cell_context_merges_blocks():
    text = format_routed_cell_context(
        sql_block="Количество: 3",
        rag_block="Банк Т-Банк",
    )
    assert "[SQL" in text
    assert "Количество: 3" in text
    assert "[RAG" in text
    assert "Банк Т-Банк" in text


def test_tabular_cell_data_router_enabled_reads_config(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_cell_data_router.config.TABULAR_CELL_DATA_ROUTER_ENABLED",
        False,
        raising=False,
    )
    assert tabular_cell_data_router_enabled() is False


@patch("app.services.tabular_cell_data_router.route_structured_data_plane")
def test_route_tabular_cell_data_plane_scopes_single_file(mock_route):
    mock_route.return_value = StructuredDataRouterResult(
        data_plane="sql",
        statement_file_ids=["f1"],
        rag_file_ids=[],
        confidence=0.9,
        reason="sum",
        resolver="llm",
        information_need="tabular_aggregate",
    )
    column = SimpleNamespace(
        id="col1",
        prompt="Сумма списаний за июнь 2026",
        column_label="Сумма",
        column_type="currency",
    )
    result = route_tabular_cell_data_plane(
        MagicMock(),
        case_id="c1",
        file_id="f1",
        column=column,
    )
    assert result.data_plane == "sql"
    mock_route.assert_called_once()
    kwargs = mock_route.call_args.kwargs
    assert kwargs["eligible_sql_file_ids"] == ["f1"]
    assert kwargs["scope_rag_file_ids"] == ["f1"]
    assert kwargs["information_need"] == "tabular_aggregate"


@pytest.mark.asyncio
@patch("app.services.tabular_cell_pipeline._run_routed_sql_flag_cell_extraction", new_callable=AsyncMock)
async def test_run_tabular_cell_prefers_routed_sql_path(mock_routed):
    from app.services.tabular_cell_pipeline import (
        PreparedCellContext,
        TabularCellPipelineResult,
    )
    from app.services.tabular_cell_verification import CellVerificationOutcome

    extraction = TabularCellExtractionModel(
        cell_value="3100",
        reasoning="test",
        column_type="currency",
        extraction_method="tabular_routed_sql",
    )
    mock_routed.return_value = TabularCellPipelineResult(
        extraction=extraction,
        prepared=PreparedCellContext(file_chunks=[], context_text="x", included_docs=[]),
        verification=CellVerificationOutcome(result=extraction),
    )

    file = SimpleNamespace(id="f1", case_id="c1", filename="stmt.pdf", original_text="")
    column = SimpleNamespace(
        id="col1",
        prompt="Сумма списаний за 11.06.2026",
        column_label="Сумма",
        column_type="currency",
        column_config=None,
    )

    result = await run_tabular_cell_extraction(
        MagicMock(),
        rag_service=MagicMock(),
        file=file,
        column=column,
        normalize_fn=lambda d, c, f: d,
        db=MagicMock(),
    )
    assert result.extraction.cell_value == "3100"
    mock_routed.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.tabular_cell_pipeline.invoke_structured_cell_extraction", new_callable=AsyncMock)
@patch("app.services.tabular_cell_pipeline.prepare_cell_retrieval_sync")
@patch("app.services.tabular_cell_sql_fetch.fetch_tabular_cell_sql_context")
@patch("app.services.tabular_cell_data_router.route_tabular_cell_data_plane")
@patch("app.services.chat.file_scoped_agent_tools.scoped_files_have_transactions", return_value=True)
@patch("app.services.tabular_cell_pipeline.tabular_cell_data_router_enabled", return_value=True)
async def test_routed_sql_plane_uses_sql_context(
    _router_on,
    _has_sql,
    mock_route,
    mock_sql_fetch,
    mock_rag_prep,
    mock_extract,
):
    from app.services.tabular_cell_pipeline import (
        PreparedCellContext,
        _run_routed_sql_flag_cell_extraction,
    )

    mock_route.return_value = StructuredDataRouterResult(
        data_plane="sql",
        statement_file_ids=["f1"],
        rag_file_ids=[],
        confidence=0.9,
        reason="aggregate",
        resolver="llm",
    )
    mock_sql_fetch.return_value = TabularCellSqlContext(
        ok=True,
        context_text="Количество операций: 5",
        rows=[],
    )
    extraction = TabularCellExtractionModel(
        cell_value="5",
        reasoning="ok",
        column_type="number",
        extraction_method="tabular_routed_sql",
    )
    mock_extract.return_value = extraction

    file = SimpleNamespace(id="f1", case_id="c1", filename="stmt.pdf", original_text="x")
    column = SimpleNamespace(
        id="col1",
        prompt="Сколько операций в июне",
        column_label="Кол-во",
        column_type="number",
        column_config=None,
    )

    result = await _run_routed_sql_flag_cell_extraction(
        MagicMock(),
        rag_service=MagicMock(),
        db=MagicMock(),
        file=file,
        column=column,
        normalize_fn=lambda d, c, f: d,
    )
    assert result is not None
    assert result.extraction.extraction_method == "tabular_routed_sql"
    mock_sql_fetch.assert_called_once()
    mock_rag_prep.assert_not_called()
    ctx_passed = mock_extract.await_args.kwargs["context_text"]
    assert "Количество операций: 5" in ctx_passed
