"""Unit tests for file-level summary index (dynamic K, RRF)."""
from __future__ import annotations

from app.services.file_summary_index import (
    FileSummaryCandidate,
    _resolve_file_scope_from_candidates,
    build_search_text,
    rrf_merge_file_scores,
    select_file_ids_by_score_gap,
)


def test_build_search_text_includes_metadata():
    text = build_search_text(
        filename="Договор_Ромашка.pdf",
        doc_type="contract",
        summary="Договор поставки",
        key_points=["неустойка 0.1%"],
    )
    assert "Ромашка" in text
    assert "contract" in text
    assert "неустойка" in text


def test_select_single_winner():
    cands = [
        FileSummaryCandidate(file_id="a", filename="a.pdf", score=0.9),
        FileSummaryCandidate(file_id="b", filename="b.pdf", score=0.4),
    ]
    ids, reason, top = select_file_ids_by_score_gap(
        cands, min_threshold=0.6, max_gap=0.15
    )
    assert ids == ["a"]
    assert reason == "single_winner"
    assert top == 0.9


def test_select_dynamic_k_cluster():
    cands = [
        FileSummaryCandidate(file_id="a", filename="a.pdf", score=0.85),
        FileSummaryCandidate(file_id="b", filename="b.pdf", score=0.78),
        FileSummaryCandidate(file_id="c", filename="c.pdf", score=0.72),
        FileSummaryCandidate(file_id="d", filename="d.pdf", score=0.45),
    ]
    ids, reason, _ = select_file_ids_by_score_gap(
        cands, min_threshold=0.6, max_gap=0.15
    )
    assert ids == ["a", "b", "c"]
    assert reason == "dynamic_k_cluster"


def test_select_below_threshold_triggers_fallback():
    cands = [
        FileSummaryCandidate(file_id="a", filename="a.pdf", score=0.45),
        FileSummaryCandidate(file_id="b", filename="b.pdf", score=0.42),
    ]
    ids, reason, top = select_file_ids_by_score_gap(
        cands, min_threshold=0.6, max_gap=0.15
    )
    assert ids == []
    assert reason == "below_threshold"
    assert top == 0.45


def test_rrf_merge_boosts_files_in_both_lists():
    dense = [("f1", 0.9), ("f2", 0.8)]
    sparse = [("f2", 1.0), ("f3", 0.7)]
    merged = rrf_merge_file_scores(dense, sparse)
    assert merged["f2"] >= merged["f1"]
    assert merged["f2"] >= merged["f3"]
    assert all(0.0 <= v <= 1.0 for v in merged.values())


def test_resolve_scope_strict_then_relaxed():
    cands = [
        FileSummaryCandidate(file_id="a", filename="a.pdf", score=0.48),
        FileSummaryCandidate(file_id="b", filename="b.pdf", score=0.44),
        FileSummaryCandidate(file_id="c", filename="c.pdf", score=0.1),
    ]
    result = _resolve_file_scope_from_candidates(cands)
    assert result.scope_hint == "relaxed"
    assert "a" in result.file_ids
    assert "c" not in result.file_ids


def test_resolve_scope_near_miss_top_k():
    cands = [
        FileSummaryCandidate(file_id="a", filename="a.pdf", score=0.25),
        FileSummaryCandidate(file_id="b", filename="b.pdf", score=0.22),
        FileSummaryCandidate(file_id="c", filename="c.pdf", score=0.21),
        FileSummaryCandidate(file_id="d", filename="d.pdf", score=0.05),
    ]
    result = _resolve_file_scope_from_candidates(cands)
    assert result.scope_hint == "relaxed"
    assert result.reason == "near_miss_top_k"
    assert len(result.file_ids) == 3

