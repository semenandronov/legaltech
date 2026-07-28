"""Tests for clause-boundary exact anchors (1.4 must not match 4.1.4)."""

import re

from langchain_core.documents import Document

from app.services.clause_anchor import (
    extract_clause_numbers,
    merge_pinned_clause_anchors,
    postgres_clause_boundary_regex,
    primary_exact_anchor,
    select_pinned_clause_anchor_docs,
    text_has_clause_boundary,
)


def test_primary_exact_anchor_prefers_labeled_clause():
    assert primary_exact_anchor("пункт 1.4") == "1.4"
    assert primary_exact_anchor("п. 6.8.1 полностью") == "6.8.1"
    assert primary_exact_anchor("ПРЕДМЕТ ДОГОВОРА") is None


def test_extract_clause_numbers_order():
    assert extract_clause_numbers("см. п. 1.4 и 10.2") == ["1.4", "10.2"]


def test_boundary_regex_matches_clause_heading_not_nested():
    rx = postgres_clause_boundary_regex("1.4")
    assert rx is not None
    pat = re.compile(rx, re.IGNORECASE | re.MULTILINE)

    assert pat.search("1.4. Заказчик обязуется…")
    assert pat.search("п. 1.4. Текст")
    assert pat.search("\n1.4 Текст без точки")
    assert not pat.search("4.1.4. Вложенный номер")
    assert not pat.search("7.1.4 что-то")
    assert not pat.search("1.4.1. Более глубокий пункт")
    # Mid-line cross-ref without newline before the number
    assert not pat.search("в соответствии с п.п. 1.4.; 1.5 настоящего Договора")


def test_text_has_clause_boundary():
    assert text_has_clause_boundary("1.4. Заказчик гарантирует…", "1.4")
    assert not text_has_clause_boundary("4.1.4. По своему выбору…", "1.4")


def _anchor_doc(text: str, *, chunk_id: str, anchor_pos: int, level: str = "micro") -> Document:
    return Document(
        page_content=text,
        metadata={
            "anchor_match": True,
            "anchor_pos": anchor_pos,
            "chunk_id": chunk_id,
            "chunk_level": level,
            "char_start": anchor_pos,
        },
    )


def test_select_pins_caps_and_prefers_earliest_verified():
    docs = [
        _anchor_doc("4.1.4. Ложный вложенный", chunk_id="bad", anchor_pos=10),
        Document(
            page_content="4. ПРАВА И ОБЯЗАННОСТИ",
            metadata={"chunk_id": "sem", "combined_score": 0.99},
        ),
        _anchor_doc(
            "1.4. Заказчик гарантирует права на участок",
            chunk_id="good",
            anchor_pos=100,
        ),
        _anchor_doc(
            "1.4. Дубликат позже",
            chunk_id="dup-later",
            anchor_pos=500,
        ),
        _anchor_doc(
            "1.4. Ещё один",
            chunk_id="third",
            anchor_pos=800,
        ),
    ]
    pins = select_pinned_clause_anchor_docs(docs, exact_query="1.4", max_pins=2)
    assert [d.metadata["chunk_id"] for d in pins] == ["good", "dup-later"]
    assert all(text_has_clause_boundary(d.page_content, "1.4") for d in pins)


def test_select_pins_recovers_unflagged_boundary_when_exact_query_set():
    """Expand may strip anchor_match; verified heading + exact_query still pins."""
    unflagged = Document(
        page_content="4.1. Гарантийный срок товара 6 месяцев.",
        metadata={"chunk_id": "recovered", "chunk_level": "micro", "char_start": 100},
    )
    noise = Document(
        page_content="5. ПОРЯДОК РАСЧЕТОВ\n5.1. Оплата…",
        metadata={"chunk_id": "noise", "combined_score": 0.99},
    )
    pins = select_pinned_clause_anchor_docs(
        [noise, unflagged], exact_query="4.1", max_pins=3
    )
    assert [d.metadata["chunk_id"] for d in pins] == ["recovered"]


def test_select_pins_rejects_unverified_anchor_match_metadata():
    docs = [
        _anchor_doc("просто текст без номера", chunk_id="lie", anchor_pos=1),
    ]
    assert select_pinned_clause_anchor_docs(docs, exact_query="1.4") == []


def test_select_pins_without_exact_query_still_requires_flag():
    unflagged = Document(
        page_content="1.4. Заказчик гарантирует…",
        metadata={"chunk_id": "noflag", "chunk_level": "micro"},
    )
    assert select_pinned_clause_anchor_docs([unflagged], exact_query=None) == []
    assert select_pinned_clause_anchor_docs([unflagged], exact_query="") == []


def test_select_pins_prefers_flagged_over_unflagged_same_clause():
    flagged = _anchor_doc(
        "1.4. С флагом", chunk_id="flagged", anchor_pos=200, level="micro"
    )
    unflagged = Document(
        page_content="1.4. Без флага раньше в тексте",
        metadata={
            "chunk_id": "unflagged",
            "chunk_level": "micro",
            "char_start": 50,
            "anchor_pos": 50,
        },
    )
    pins = select_pinned_clause_anchor_docs(
        [unflagged, flagged], exact_query="1.4", max_pins=2
    )
    assert pins[0].metadata["chunk_id"] == "flagged"
    assert pins[1].metadata["chunk_id"] == "unflagged"


def test_merge_pins_front_and_never_drops_pins_for_small_final_k():
    pins = [
        _anchor_doc("1.4. A", chunk_id="a", anchor_pos=1),
        _anchor_doc("1.4. B", chunk_id="b", anchor_pos=2),
    ]
    ranked = [
        Document(page_content="wrong §4", metadata={"chunk_id": "w"}),
        Document(page_content="other", metadata={"chunk_id": "o"}),
    ]
    # Additive: pins + up to final_k ranked (exact does not consume rerank budget).
    merged = merge_pinned_clause_anchors(pins, ranked, final_k=1, additive_ranked=True)
    assert [d.metadata["chunk_id"] for d in merged] == ["a", "b", "w"]
    assert all(d.metadata.get("anchor_pinned") for d in merged[:2])
    assert all(d.metadata.get("exact_channel") for d in merged[:2])

    merged8 = merge_pinned_clause_anchors(pins, ranked, final_k=8, additive_ranked=True)
    assert [d.metadata["chunk_id"] for d in merged8] == ["a", "b", "w", "o"]

    # Legacy shared budget: pins take slots inside final_k.
    shared = merge_pinned_clause_anchors(pins, ranked, final_k=2, additive_ranked=False)
    assert [d.metadata["chunk_id"] for d in shared] == ["a", "b"]


def test_merge_dedupes_pin_already_in_ranked():
    pin = _anchor_doc("1.4. Текст", chunk_id="same", anchor_pos=1)
    ranked = [
        Document(page_content="1.4. Текст", metadata={"chunk_id": "same"}),
        Document(page_content="filler", metadata={"chunk_id": "f"}),
    ]
    merged = merge_pinned_clause_anchors([pin], ranked, final_k=4, additive_ranked=True)
    assert [d.metadata["chunk_id"] for d in merged] == ["same", "f"]
    assert merged[0].metadata.get("anchor_pinned") is True


def test_select_pins_default_cap_is_three():
    docs = [
        _anchor_doc(f"1.4. hit {i}", chunk_id=f"c{i}", anchor_pos=i * 10)
        for i in range(1, 6)
    ]
    pins = select_pinned_clause_anchor_docs(docs, exact_query="1.4")
    assert len(pins) == 3
    assert [d.metadata["chunk_id"] for d in pins] == ["c1", "c2", "c3"]


def test_exclude_docs_by_identity_removes_exact_from_rerank_pool():
    from app.services.clause_anchor import exclude_docs_by_identity

    a = _anchor_doc("1.4. A", chunk_id="a", anchor_pos=1)
    b = Document(page_content="other", metadata={"chunk_id": "b"})
    pool = exclude_docs_by_identity([a, b], [a])
    assert [d.metadata["chunk_id"] for d in pool] == ["b"]
