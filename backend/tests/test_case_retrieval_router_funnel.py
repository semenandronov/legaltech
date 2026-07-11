"""Unit tests for CaseRetrievalRouter funnel (no database)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.chat.retrieval_router import CaseRetrievalRouter, RetrievalTask
from app.services.file_summary_index import FileScopeResult, FileSummaryCandidate


def _catalog_entry(file_id: str, filename: str, doc_type: str = "other"):
    from app.services.chat.retrieval_router import CaseFileCatalogEntry

    return CaseFileCatalogEntry(
        file_id=file_id,
        filename=filename,
        doc_type=doc_type,
        summary=f"Summary of {filename}",
        key_points=[],
    )


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def large_case_env(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._count_case_files",
        lambda db, case_id: 12,
    )
    monkeypatch.setattr(
        "app.services.chat.case_file_catalog_cache.get_case_file_catalog_cached",
        lambda db, case_id, limit=80: [
            _catalog_entry("f1", "Договор.pdf", "contract"),
            _catalog_entry("f2", "Иск.pdf", "statement_of_claim"),
        ],
    )


def test_small_case_full_corpus(mock_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._count_case_files",
        lambda db, case_id: 3,
    )
    monkeypatch.setattr(
        "app.services.chat.case_file_catalog_cache.get_case_file_catalog_cached",
        lambda db, case_id, limit=80: [
            _catalog_entry("f1", "pretenzija.pdf"),
            _catalog_entry("f2", "vstrechnyj isk.pdf"),
        ],
    )
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._resolve_small_case_scope",
        lambda **kwargs: None,
    )
    # No LLM: fall through to full corpus (legacy small-case behaviour).
    router = CaseRetrievalRouter(llm=None)
    task = router.route(
        question="срок оплаты",
        case_id="c1",
        db=mock_db,
        allow_llm_scope=True,
    )
    assert task.scope_mode == "full_case"
    assert task.rationale == "small_case_full_corpus"
    assert not task.file_ids


def test_small_case_llm_scope_before_full_corpus(mock_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._count_case_files",
        lambda db, case_id: 3,
    )
    monkeypatch.setattr(
        "app.services.chat.case_file_catalog_cache.get_case_file_catalog_cached",
        lambda db, case_id, limit=80: [
            _catalog_entry("f-pret", "03. pretenzija 5l.pdf"),
            _catalog_entry("f-isk", "00. vstrechnyj isk.pdf"),
        ],
    )
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._resolve_small_case_scope",
        lambda **kwargs: None,
    )
    llm_task = RetrievalTask(
        search_query="сумма претензии",
        file_ids=["f-pret"],
        scope_mode="resolved",
        confidence=0.9,
        rationale="pretension",
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = llm_task
    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="Какая общая сумма задолженности указана в претензии?",
        case_id="c1",
        db=mock_db,
        allow_llm_scope=True,
    )
    assert task.file_ids == ["f-pret"]
    assert task.scope_mode == "resolved"
    assert task.within_file_expand is True
    assert "llm_scope" in task.rationale


def test_summary_resolved_skips_llm(mock_db, large_case_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *a, **k: FileScopeResult(
            ["f1"],
            "single_winner",
            0.91,
            "resolved",
            (FileSummaryCandidate("f1", "a.pdf", 0.91),),
        ),
    )
    mock_llm = MagicMock()
    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(question="неустойка", case_id="c1", db=mock_db)
    assert task.scope_mode == "summary_hybrid"
    assert task.file_ids == ["f1"]
    mock_llm.with_structured_output.assert_not_called()


def test_llm_resolves_after_summary_miss(mock_db, large_case_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *a, **k: FileScopeResult([], "below_threshold", 0.4, "miss", ()),
    )
    llm_task = RetrievalTask(
        search_query="неустойка",
        file_ids=["f1"],
        scope_mode="resolved",
        confidence=0.9,
        rationale="mock",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = llm_task
    mock_llm.with_structured_output.return_value = mock_structured

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(question="неустойка в договоре", case_id="c1", db=mock_db)
    assert task.file_ids == ["f1"]
    assert task.scope_mode == "resolved"


def test_relaxed_scope_when_llm_unavailable(mock_db, large_case_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *a, **k: FileScopeResult(
            ["f1", "f2"],
            "relaxed_dynamic_k_cluster",
            0.42,
            "relaxed",
            (
                FileSummaryCandidate("f1", "a.pdf", 0.42),
                FileSummaryCandidate("f2", "b.pdf", 0.40),
            ),
        ),
    )
    router = CaseRetrievalRouter(llm=None)
    task = router.route(question="срок", case_id="c1", db=mock_db)
    assert task.scope_mode == "summary_hybrid"
    assert set(task.file_ids) == {"f1", "f2"}


def test_llm_full_case_only_with_high_confidence(mock_db, large_case_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *a, **k: FileScopeResult([], "empty", 0.0, "miss", ()),
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = RetrievalTask(
        search_query="обзор",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.5,
        rationale="low",
    )
    mock_llm.with_structured_output.return_value = mock_structured

    router = CaseRetrievalRouter(llm=mock_llm)
    low = router.route(question="обзор дела", case_id="c1", db=mock_db)
    assert low.rationale == "no_summary_index_signal"

    mock_structured.invoke.return_value = RetrievalTask(
        search_query="обзор",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.9,
        rationale="explicit",
    )
    high = router.route(question="обзор дела", case_id="c1", db=mock_db)
    assert high.scope_mode == "full_case"
    assert "llm_scope" in high.rationale


def test_llm_query_rewrite_preserved_on_fallback(mock_db, large_case_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *a, **k: FileScopeResult([], "empty", 0.0, "miss", ()),
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = RetrievalTask(
        search_query="перефразированный запрос",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.2,
        rationale="weak",
    )
    mock_llm.with_structured_output.return_value = mock_structured

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(question="исходный вопрос", case_id="c1", db=mock_db)
    assert task.search_query == "перефразированный запрос"
