"""Tests for CaseRetrievalRouter (secretary scope funnel)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.analysis import DocumentClassification
from app.models.case import File as CaseFile
from app.services.chat.retrieval_router import (
    CaseFileCatalogEntry,
    CaseRetrievalRouter,
    RetrievalTask,
    _batch_doc_types_by_file_id,
    _match_catalog_files_by_question,
    build_case_file_catalog,
    build_metadata_filter,
    resolve_scoped_file_ids,
)
from app.services.file_summary_index import FileScopeResult, FileSummaryCandidate


@pytest.fixture
def large_case_threshold(monkeypatch):
    """Treat 2-file fixtures as large corpus (exercise summary/LLM funnel)."""
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_ROUTER_SMALL_CASE_MAX_FILES", 0)


@pytest.fixture(autouse=True)
def _file_summary_index_miss(monkeypatch):
    """Default: strict summary miss → exercises LLM/relaxed paths for large cases."""
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *args, **kwargs: FileScopeResult(
            [],
            "below_threshold",
            0.0,
            "miss",
            (
                FileSummaryCandidate("x", "x.pdf", 0.4),
                FileSummaryCandidate("y", "y.pdf", 0.38),
            ),
        ),
    )


@pytest.fixture
def case_with_files(db_session, test_case):
    f1 = CaseFile(
        case_id=test_case.id,
        filename="Договор_ООО_Ромашка.pdf",
        file_type="pdf",
        original_text="договор неустойка",
        doc_summary_short="Договор поставки с ООО Ромашка",
        doc_key_points=["неустойка 0.1%", "срок 30 дней"],
    )
    f2 = CaseFile(
        case_id=test_case.id,
        filename="Исковое_заявление.pdf",
        file_type="pdf",
        original_text="иск",
        doc_summary_short="Иск к ответчику",
        doc_key_points=["сумма 1 млн"],
    )
    db_session.add_all([f1, f2])
    db_session.commit()
    db_session.refresh(f1)
    db_session.refresh(f2)
    db_session.add(
        DocumentClassification(
            case_id=test_case.id,
            file_id=f1.id,
            doc_type="contract",
            relevance_score=90,
        )
    )
    db_session.commit()
    return test_case, f1, f2


def test_match_catalog_files_by_date_in_question():
    catalog = [
        CaseFileCatalogEntry(
            file_id="f-contract",
            filename="Договор_02.02.2024.pdf",
            doc_type="contract",
        ),
        CaseFileCatalogEntry(
            file_id="f-claim",
            filename="Исковое_заявление.pdf",
            doc_type="claim",
        ),
    ]
    matched = _match_catalog_files_by_question(catalog, "о чем Договор от 02.02.2024")
    assert matched == ["f-contract"]


def test_attached_file_ids_override_llm(db_session, case_with_files):
    case, f1, _f2 = case_with_files
    mock_llm = MagicMock()
    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="неустойка в договоре",
        case_id=case.id,
        db=db_session,
        attached_file_ids=[f1.id],
    )
    mock_llm.invoke.assert_not_called()
    assert task.scope_mode == "attached"
    assert task.file_ids == [f1.id]
    assert task.confidence >= 0.9


def test_small_case_full_corpus_when_no_scope_signal(db_session, case_with_files, monkeypatch):
    case, _f1, _f2 = case_with_files
    build_mock = MagicMock()
    monkeypatch.setattr(
        "app.services.chat.case_file_catalog_cache.get_case_file_catalog_cached",
        build_mock,
    )
    router = CaseRetrievalRouter(llm=MagicMock())
    task = router.route(
        question="какой срок оплаты",
        case_id=case.id,
        db=db_session,
    )
    build_mock.assert_called_once()
    assert task.scope_mode == "full_case"
    assert task.rationale == "small_case_full_corpus"


def test_small_case_resolves_named_contract(db_session, case_with_files, monkeypatch):
    case, f1, _f2 = case_with_files
    monkeypatch.setattr(
        "app.services.file_summary_index.file_summary_index_enabled",
        lambda: False,
    )
    router = CaseRetrievalRouter(llm=MagicMock())
    task = router.route(
        question="о чем Договор от 02.02.2024",
        case_id=case.id,
        db=db_session,
    )
    assert task.scope_mode == "resolved"
    assert f1.id in task.file_ids
    assert task.rationale == "small_case_filename_match"


def test_mock_llm_catalog_resolves_file_ids(
    db_session, case_with_files, large_case_threshold
):
    case, f1, f2 = case_with_files
    catalog = build_case_file_catalog(db_session, case.id)
    assert len(catalog) == 2

    llm_task = RetrievalTask(
        search_query="неустойка договор",
        file_ids=[f1.id],
        scope_mode="resolved",
        confidence=0.88,
        rationale="mock_llm",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = llm_task
    mock_llm.with_structured_output.return_value = mock_structured

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="неустойка в договоре с Ромашкой",
        case_id=case.id,
        db=db_session,
    )
    assert task.file_ids == [f1.id]
    assert task.scope_mode == "resolved"
    assert f2.id not in task.file_ids


def test_llm_doc_type_scope(db_session, case_with_files, large_case_threshold):
    case, _f1, _f2 = case_with_files
    llm_task = RetrievalTask(
        search_query="условия договора",
        file_ids=[],
        doc_type="contract",
        scope_mode="doc_type",
        confidence=0.82,
        rationale="all_contracts",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = llm_task
    mock_llm.with_structured_output.return_value = mock_structured

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="какие условия во всех договорах",
        case_id=case.id,
        db=db_session,
    )
    assert task.scope_mode == "doc_type"
    assert task.doc_type == "contract"
    assert not task.file_ids


def test_build_metadata_filter_single_and_multi():
    single = RetrievalTask(
        search_query="q",
        file_ids=["uuid-1"],
        scope_mode="resolved",
        confidence=0.9,
        rationale="t",
    )
    assert build_metadata_filter(single) == {"file_id": "uuid-1"}

    multi = RetrievalTask(
        search_query="q",
        file_ids=["a", "b"],
        scope_mode="attached",
        confidence=0.9,
        rationale="t",
    )
    assert build_metadata_filter(multi) == {"file_id": ["a", "b"]}

    dtype = RetrievalTask(
        search_query="q",
        doc_type="contract",
        scope_mode="doc_type",
        confidence=0.7,
        rationale="t",
    )
    assert build_metadata_filter(dtype) == {"doc_type": "contract"}
    assert resolve_scoped_file_ids(dtype) is None


def test_low_confidence_llm_still_refines_search_query(
    db_session, case_with_files, large_case_threshold, monkeypatch
):
    case, _f1, _f2 = case_with_files
    llm_task = RetrievalTask(
        search_query="неустойка договор ромашка",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.3,
        rationale="uncertain",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = llm_task
    mock_llm.with_structured_output.return_value = mock_structured
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *args, **kwargs: FileScopeResult([], "empty_candidates", 0.0, "miss", ()),
    )

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="неустойка в договоре с Ромашкой",
        case_id=case.id,
        db=db_session,
    )
    assert task.search_query == "неустойка договор ромашка"


def test_active_document_id_boost(db_session, case_with_files):
    case, f1, _f2 = case_with_files
    router = CaseRetrievalRouter(llm=None)
    task = router.route(
        question="что в этом документе",
        case_id=case.id,
        db=db_session,
        document_id=f1.id,
    )
    assert f1.id in task.file_ids
    assert task.scope_mode == "resolved"


def test_build_case_file_catalog_uses_batch_classification(db_session, case_with_files):
    case, f1, _f2 = case_with_files
    catalog = build_case_file_catalog(db_session, case.id)
    by_id = {e.file_id: e for e in catalog}
    assert by_id[f1.id].doc_type == "contract"


def test_batch_doc_types_single_query_pattern(db_session, case_with_files):
    case, f1, f2 = case_with_files
    mapping = _batch_doc_types_by_file_id(db_session, [f1.id, f2.id])
    assert mapping[f1.id] == "contract"


def test_document_id_skips_catalog_build(db_session, case_with_files, monkeypatch):
    case, f1, _f2 = case_with_files
    build_mock = MagicMock()
    monkeypatch.setattr(
        "app.services.chat.case_file_catalog_cache.get_case_file_catalog_cached",
        build_mock,
    )
    router = CaseRetrievalRouter(llm=None)
    task = router.route(
        question="что в этом документе",
        case_id=case.id,
        db=db_session,
        document_id=f1.id,
    )
    build_mock.assert_not_called()
    assert task.scope_mode == "resolved"


def test_summary_hybrid_scope_when_index_hits(
    db_session, case_with_files, large_case_threshold, monkeypatch
):
    case, f1, _f2 = case_with_files
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *args, **kwargs: FileScopeResult(
            [f1.id],
            "single_winner",
            0.92,
            "resolved",
            (FileSummaryCandidate(f1.id, "a.pdf", 0.92),),
        ),
    )
    mock_llm = MagicMock()
    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="срок оплаты по договору",
        case_id=case.id,
        db=db_session,
    )
    mock_llm.invoke.assert_not_called()
    assert task.scope_mode == "summary_hybrid"
    assert f1.id in task.file_ids
    assert task.confidence >= 0.72


def test_relaxed_summary_scope_without_llm(
    db_session, case_with_files, large_case_threshold, monkeypatch
):
    case, f1, f2 = case_with_files
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *args, **kwargs: FileScopeResult(
            [f1.id, f2.id],
            "relaxed_dynamic_k_cluster",
            0.48,
            "relaxed",
            (
                FileSummaryCandidate(f1.id, "a.pdf", 0.48),
                FileSummaryCandidate(f2.id, "b.pdf", 0.45),
            ),
        ),
    )
    router = CaseRetrievalRouter(llm=None)
    task = router.route(
        question="срок оплаты",
        case_id=case.id,
        db=db_session,
    )
    assert task.scope_mode == "summary_hybrid"
    assert set(task.file_ids) == {f1.id, f2.id}
    assert "relaxed" in task.rationale


def test_llm_explicit_full_case_requires_high_confidence(
    db_session, case_with_files, large_case_threshold, monkeypatch
):
    case, _f1, _f2 = case_with_files
    low_conf = RetrievalTask(
        search_query="обзор",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.5,
        rationale="uncertain_overview",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = low_conf
    mock_llm.with_structured_output.return_value = mock_structured
    monkeypatch.setattr(
        "app.services.file_summary_index.resolve_file_scope",
        lambda *args, **kwargs: FileScopeResult([], "empty", 0.0, "miss", ()),
    )

    router = CaseRetrievalRouter(llm=mock_llm)
    task = router.route(
        question="дай обзор по всему делу",
        case_id=case.id,
        db=db_session,
    )
    assert task.scope_mode == "full_case"
    assert task.rationale == "no_summary_index_signal"

    high_conf = RetrievalTask(
        search_query="обзор дела",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.85,
        rationale="explicit_overview",
    )
    mock_structured.invoke.return_value = high_conf
    task2 = router.route(
        question="дай обзор по всему делу",
        case_id=case.id,
        db=db_session,
    )
    assert task2.scope_mode == "full_case"
    assert "llm_scope" in task2.rationale
