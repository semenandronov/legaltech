"""Retrieval quality tests for court practice (unit + live index)."""
from __future__ import annotations

import re

import pytest

from app.services.court_practice_service import retrieve_court_practice
from app.services.court_practice_store import (
    CourtPracticeHit,
    _rrf_merge,
    count_chunks,
    diversify_by_case,
    hybrid_search,
)


def _norm_case(num: str) -> str:
    s = (num or "").strip().upper()
    return s.replace("A", "А")


def _require_gigachat_embeddings() -> None:
    from app.services.gigachat_embeddings import get_gigachat_embeddings

    emb = get_gigachat_embeddings()
    if not emb.is_available():
        pytest.skip("GIGACHAT_CREDENTIALS не заданы")
    try:
        emb.embed_query("тест доступности")
    except Exception as exc:
        pytest.skip(f"GigaChat embeddings недоступны: {exc}")


# Запросы под реальные акты из пилотной загрузки (~100 дел ВС РФ, 30.06.2020)
LIVE_EVAL_QUERIES = [
    (
        "субсидиарная ответственность Блянихов банкротство Кабардино-Балкария",
        "А20-759/2007",
        5,
    ),
    (
        "арест имущества банкротство Interactive Bank конкурсный управляющий",
        "А40-114174/2016",
        5,
    ),
    (
        "неустойка жилищно-коммунальные услуги УправДом субсидиарная ответственность",
        "А40-319001/2018",
        5,
    ),
    (
        "привлечение к субсидиарной ответственности Киселёв Оренбургское бюро",
        "А47-9339/2018",
        5,
    ),
    (
        "Пиголкин субсидиарная ответственность общество Деталь Нижний Новгород",
        "А43-3251/2017",
        5,
    ),
]


def test_diversify_by_case_limits_per_case():
    hits = [
        CourtPracticeHit(
            chunk_id=f"c{i}",
            document_id=f"d{i // 2}",
            case_number="А40-1/2024" if i < 4 else "А40-2/2024",
            court_name=None,
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=i,
            chunk_text=f"t{i}",
            score=1.0 - i * 0.01,
        )
        for i in range(6)
    ]
    out = diversify_by_case(hits, max_per_case=2)
    assert len(out) == 4
    assert sum(1 for h in out if h.case_number == "А40-1/2024") == 2


def test_rrf_merge_boosts_overlap():
    dense = [
        CourtPracticeHit(
            chunk_id="x",
            document_id="d1",
            case_number="А40-1/2024",
            court_name=None,
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=0,
            chunk_text="dense",
            score=0.9,
            dense_rank=1,
        )
    ]
    sparse = [
        CourtPracticeHit(
            chunk_id="x",
            document_id="d1",
            case_number="А40-1/2024",
            court_name=None,
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=0,
            chunk_text="sparse",
            score=0.5,
            sparse_rank=1,
        ),
        CourtPracticeHit(
            chunk_id="y",
            document_id="d2",
            case_number="А40-2/2024",
            court_name=None,
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=0,
            chunk_text="only sparse",
            score=0.4,
            sparse_rank=2,
        ),
    ]
    merged = _rrf_merge(dense, sparse)
    assert merged[0].chunk_id == "x"
    assert merged[0].score > merged[1].score


def test_retrieve_empty_index(monkeypatch):
    monkeypatch.setattr(
        "app.services.court_practice_service.count_chunks",
        lambda: 0,
    )
    out = retrieve_court_practice("банкротство")
    assert out.hits_count == 0
    assert out.meta.get("reason") == "empty_index"


def test_retrieve_without_rerank_respects_final_k(monkeypatch):
    hits = [
        CourtPracticeHit(
            chunk_id=f"id{i}",
            document_id=f"doc{i}",
            case_number=f"А40-{i}/2024",
            court_name="ВС РФ",
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=0,
            chunk_text=f"мотивировка {i}",
            score=1.0 - i * 0.1,
        )
        for i in range(10)
    ]

    class _Emb:
        def embed_query(self, text: str):
            return [0.1] * 2560

    monkeypatch.setattr(
        "app.services.court_practice_service.count_chunks",
        lambda: 10,
    )
    monkeypatch.setattr(
        "app.services.court_practice_service.get_gigachat_embeddings",
        lambda: _Emb(),
    )
    monkeypatch.setattr(
        "app.services.court_practice_service.hybrid_search",
        lambda q, vec: hits,
    )

    out = retrieve_court_practice("тест", final_k=3, use_reranker=False)
    assert out.hits_count == 3
    assert len(out.documents) == 3
    assert all(d.metadata.get("source_type") == "court_practice" for d in out.documents)


def test_retrieve_rerank_promotes_relevant_chunk(monkeypatch):
    h0 = CourtPracticeHit(
        chunk_id="0",
        document_id="d0",
        case_number="А40-1/2024",
        court_name=None,
        court_tier="vs_rf",
        judgment_date=None,
        chunk_index=0,
        chunk_text="общие положения процессуального кодекса",
        score=0.95,
    )
    h1 = CourtPracticeHit(
        chunk_id="1",
        document_id="d1",
        case_number="А40-2/2024",
        court_name=None,
        court_tier="vs_rf",
        judgment_date=None,
        chunk_index=0,
        chunk_text="субсидиарная ответственность контролирующих лиц при банкротстве",
        score=0.80,
    )

    class _Emb:
        def embed_query(self, text: str):
            return [0.0] * 2560

    class _FakeReranker:
        def rerank(self, query, documents, top_k=10, score_threshold=None, **kwargs):
            order = sorted(
                documents,
                key=lambda d: d.page_content.count("субсидиарная"),
                reverse=True,
            )
            return [(d, 0.99 - 0.1 * i) for i, d in enumerate(order[:top_k])]

    monkeypatch.setattr("app.services.court_practice_service.count_chunks", lambda: 2)
    monkeypatch.setattr("app.services.court_practice_service.get_gigachat_embeddings", lambda: _Emb())
    monkeypatch.setattr(
        "app.services.court_practice_service.hybrid_search",
        lambda q, vec: [h0, h1],
    )
    monkeypatch.setattr(
        "app.services.reranker_service.get_reranker_service",
        lambda: _FakeReranker(),
    )

    out = retrieve_court_practice(
        "субсидиарная ответственность при банкротстве",
        final_k=1,
        use_reranker=True,
    )
    assert out.hits_count == 1
    assert "субсидиарная" in (out.documents[0].page_content or "")


@pytest.mark.integration
@pytest.mark.parametrize("query,expected_case,top_k", LIVE_EVAL_QUERIES)
def test_live_retrieval_finds_expected_case(query: str, expected_case: str, top_k: int):
    """Качество на проиндексированной пилотной базе (Neon + GigaChat)."""
    if count_chunks() < 10:
        pytest.skip("Индекс судебной практики пуст — сначала загрузите CSV")
    _require_gigachat_embeddings()

    result = retrieve_court_practice(query, final_k=top_k, use_reranker=False)
    assert result.hits_count > 0, f"нет хитов для запроса: {query!r}"

    cases = [
        _norm_case((d.metadata or {}).get("case_number", "")) for d in result.documents
    ]
    want = _norm_case(expected_case)
    assert want in cases, (
        f"ожидали {want} в top-{top_k}, получили {cases}; "
        f"запрос={query!r}"
    )


@pytest.mark.integration
def test_live_hybrid_vs_fts_both_contribute():
    if count_chunks() < 10:
        pytest.skip("Индекс судебной практики пуст")
    _require_gigachat_embeddings()

    from app.services.gigachat_embeddings import get_gigachat_embeddings
    from app.services.court_practice_store import _dense_search, _fts_search

    query = "субсидиарная ответственность банкротство"
    vec = get_gigachat_embeddings().embed_query(query)
    dense = _dense_search(vec, k=15)
    sparse = _fts_search(query, k=15)
    merged = hybrid_search(query, vec)

    assert len(dense) > 0, "dense search пуст"
    assert len(sparse) > 0, "FTS пуст"
    assert len(merged) > 0
    # RRF: хотя бы один chunk_id из обоих каналов в топе
    dense_ids = {h.chunk_id for h in dense[:10]}
    sparse_ids = {h.chunk_id for h in sparse[:10]}
    top_ids = {h.chunk_id for h in merged[:10]}
    assert top_ids & (dense_ids | sparse_ids)


@pytest.mark.integration
def test_live_retrieval_with_reranker_if_available(monkeypatch):
    """Полный reranker (bge) — только при RUN_SLOW_TESTS=1 (загрузка модели ~минуты)."""
    import os

    if not os.getenv("RUN_SLOW_TESTS"):
        pytest.skip("Пропуск медленного reranker-теста (задайте RUN_SLOW_TESTS=1)")

    if count_chunks() < 10:
        pytest.skip("Индекс судебной практики пуст")
    _require_gigachat_embeddings()

    query = "субсидиарная ответственность банкротство А20-759"
    out = retrieve_court_practice(query, final_k=5, use_reranker=True)
    assert out.hits_count > 0
    cases = [_norm_case((d.metadata or {}).get("case_number", "")) for d in out.documents]
    assert any(re.search(r"А20-759/2007", c) for c in cases)
