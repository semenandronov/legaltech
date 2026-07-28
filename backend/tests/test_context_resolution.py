"""Tests for parent context resolution (micro → hard section for LLM)."""
from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.documents import Document

from app.services.chat.context_resolution import (
    filter_rerank_pool_to_micro,
    fit_section_text_to_budget,
    resolve_parent_context,
    stitch_section_macros,
)


def _micro(
    fid: str,
    *,
    pid: str = "",
    section_root: str = "",
    text: str = "micro",
    score: float = 0.9,
    char_start: int = 10,
    char_end: int = 50,
) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_level": "micro",
            "chunk_id": f"m_{fid}_{char_start}",
            "parent_macro_id": pid,
            "macro_id": pid,
            "section_root_id": section_root,
            "file_id": fid,
            "rerank_score": score,
            "char_start": char_start,
            "char_end": char_end,
        },
    )


def _macro(
    mid: str,
    text: str,
    *,
    section_root: str = "",
    char_start: int = 0,
    char_end: int = 100,
    title: str = "",
) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_level": "macro",
            "macro_id": mid,
            "chunk_id": f"mac_{mid}",
            "section_root_id": section_root,
            "section_title": title,
            "file_id": "f1",
            "char_start": char_start,
            "char_end": char_end,
        },
    )


def test_filter_rerank_pool_drops_macro():
    docs = [_micro("f1", pid="p1"), _macro("p2", "x"), _micro("f1", pid="p2")]
    out = filter_rerank_pool_to_micro(docs)
    assert len(out) == 2
    assert all(d.metadata.get("chunk_level") != "macro" for d in out)


def test_stitch_section_macros_drops_overlap():
    m1 = _macro("a", "ABCDEFGHIJ", section_root="s1", char_start=0, char_end=10)
    m2 = _macro("b", "FGHIJKLMNO", section_root="s1", char_start=5, char_end=15)
    text, cs, ce = stitch_section_macros([m2, m1])
    assert cs == 0 and ce == 15
    assert text == "ABCDEFGHIJKLMNO"


def test_fit_section_keeps_head_and_grounding():
    body = "HEAD" + ("x" * 2000) + "GROUND" + ("y" * 2000)
    # section starts at 100; grounding at absolute 100+2004
    fitted = fit_section_text_to_budget(
        body,
        max_chars=800,
        grounding_char_start=100 + 2004,
        grounding_char_end=100 + 2010,
        section_char_start=100,
    )
    assert fitted.startswith("HEAD")
    assert "GROUND" in fitted
    assert "…" in fitted
    assert len(fitted) <= 800


def test_resolve_expands_to_full_hard_section():
    t1 = "1. ПРЕДМЕТ\n1.1. Работа.\n"
    t2 = "1.4. Гарантия.\n1.5. Ещё.\n"
    store = MagicMock()
    store.fetch_macro_chunks_by_section_root_ids.return_value = {
        "sec_predmet": [
            _macro(
                "m1",
                t1,
                section_root="sec_predmet",
                char_start=100,
                char_end=100 + len(t1),
                title="1. ПРЕДМЕТ",
            ),
            _macro(
                "m2",
                t2,
                section_root="sec_predmet",
                char_start=100 + len(t1),
                char_end=100 + len(t1) + len(t2),
                title="1. ПРЕДМЕТ",
            ),
        ]
    }
    store.fetch_macro_chunks_by_macro_ids.return_value = {}
    ranked = [
        _micro(
            "f1",
            pid="m2",
            section_root="sec_predmet",
            text="1.4. Гарантия.",
            score=0.99,
            char_start=100 + len(t1),
            char_end=100 + len(t1) + 14,
        )
    ]
    resolved, meta = resolve_parent_context(ranked, case_id="case1", vector_store=store)
    assert len(resolved) == 1
    assert "1.1." in resolved[0].page_content
    assert "1.4." in resolved[0].page_content
    assert meta["sections_resolved"] == 1
    assert resolved[0].metadata.get("context_resolution") == "section_from_micro"
    assert resolved[0].metadata.get("section_root_id") == "sec_predmet"


def test_resolve_legacy_macro_without_section_root():
    store = MagicMock()
    store.fetch_macro_chunks_by_section_root_ids.return_value = {}
    store.fetch_macro_chunks_by_macro_ids.return_value = {
        "p1": _macro("p1", "Parent one full text"),
        "p2": _macro("p2", "Parent two full text"),
    }
    ranked = [
        _micro("f1", pid="p1", score=0.95),
        _micro("f1", pid="p1", score=0.80),
        _micro("f1", pid="p2", score=0.70),
    ]
    resolved, meta = resolve_parent_context(ranked, case_id="case1", vector_store=store)
    assert len(resolved) == 2
    assert resolved[0].page_content == "Parent one full text"
    assert resolved[1].page_content == "Parent two full text"
    assert meta["macros_resolved"] == 2
    assert resolved[0].metadata.get("grounding_micro_chunk_id") == "m_f1_10"


def test_resolve_parent_context_fallback_to_micro_when_section_missing():
    store = MagicMock()
    store.fetch_macro_chunks_by_section_root_ids.return_value = {"missing": []}
    store.fetch_macro_chunks_by_macro_ids.return_value = {}
    micro = _micro("f1", pid="m1", section_root="missing")
    resolved, meta = resolve_parent_context([micro], case_id="c1", vector_store=store)
    assert len(resolved) == 1
    assert resolved[0].page_content == "micro"
    assert meta["fallback_micro"] == 1


def test_resolve_dedupes_same_section_from_two_micros():
    store = MagicMock()
    store.fetch_macro_chunks_by_section_root_ids.return_value = {
        "sec": [_macro("m1", "FULL SECTION", section_root="sec", char_start=0, char_end=20)]
    }
    store.fetch_macro_chunks_by_macro_ids.return_value = {}
    ranked = [
        _micro("f", pid="m1", section_root="sec", score=0.9, char_start=0, char_end=5),
        _micro("f", pid="m2", section_root="sec", score=0.8, char_start=10, char_end=15),
    ]
    resolved, _ = resolve_parent_context(ranked, case_id="c1", vector_store=store)
    assert len(resolved) == 1
    assert resolved[0].page_content == "FULL SECTION"
