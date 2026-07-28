"""Exact-channel must survive within-file BM25 expand."""

from langchain_core.documents import Document

from app.services.chat.scoped_file_expand import (
    _merge_exact_channel_with_lexical,
    _tokenize_text,
    score_chunk_for_question,
)
from app.services.clause_anchor import select_pinned_clause_anchor_docs


def test_tokenize_keeps_dotted_clause_numbers():
    tokens = _tokenize_text("пункт 4.1 договора")
    assert "4.1" in tokens
    assert "пункт" in tokens
    assert "договора" in tokens


def test_score_rewards_clause_number_in_chunk():
    q = "пункт 4.1 договора"
    hit = "4. ГАРАНТИЙНЫЙ СРОК\n\n4.1. Гарантийный срок товара 6 месяцев."
    miss = "5. ПОРЯДОК РАСЧЕТОВ\n\n5.1. Деньги за поставленное оборудование…"
    assert score_chunk_for_question(q, hit) > score_chunk_for_question(q, miss)


def test_merge_puts_exact_channel_first_and_wins_identity():
    exact = Document(
        page_content="4.1. Гарантийный срок товара 6 месяцев.",
        metadata={
            "anchor_match": True,
            "anchor_pos": 105,
            "chunk_id": "same",
            "chunk_level": "micro",
        },
    )
    # Lexical copy of the same chunk without the exact-channel flag.
    lexical_copy = Document(
        page_content="4.1. Гарантийный срок товара 6 месяцев.",
        metadata={"chunk_id": "same", "chunk_level": "micro"},
    )
    noise = Document(
        page_content="5. ПОРЯДОК РАСЧЕТОВ",
        metadata={"chunk_id": "noise", "chunk_level": "macro"},
    )
    hybrid_other = Document(
        page_content="3.1. Продавец обязан…",
        metadata={"chunk_id": "hyb", "combined_score": 0.5},
    )

    merged, exact_kept = _merge_exact_channel_with_lexical(
        hybrid_docs=[exact, hybrid_other],
        lexical_docs=[noise, lexical_copy],
        file_count=1,
        pool_limit=32,
    )

    assert exact_kept == 1
    assert merged[0].metadata.get("anchor_match") is True
    assert merged[0].metadata["chunk_id"] == "same"
    # Unflagged duplicate must not replace or duplicate the exact hit.
    same_ids = [d.metadata["chunk_id"] for d in merged if d.metadata["chunk_id"] == "same"]
    assert same_ids == ["same"]
    assert {d.metadata["chunk_id"] for d in merged} >= {"same", "noise", "hyb"}


def test_merge_puts_lexical_channel_after_exact():
    exact = Document(
        page_content="4.1. Гарантийный срок.",
        metadata={"chunk_id": "ex", "anchor_match": True, "exact_channel": True},
    )
    lexical = Document(
        page_content="7.2. неустойку 0,1%.",
        metadata={"chunk_id": "lex", "lexical_match": True, "literal_channel": True},
    )
    noise = Document(
        page_content="шум BM25",
        metadata={"chunk_id": "n"},
    )
    merged, exact_kept = _merge_exact_channel_with_lexical(
        hybrid_docs=[noise, exact],
        lexical_docs=[lexical, noise],
        file_count=1,
        pool_limit=32,
    )
    assert exact_kept == 1
    assert merged[0].metadata["chunk_id"] == "ex"
    assert merged[1].metadata["chunk_id"] == "lex"
    assert merged[1].metadata.get("lexical_match") is True


def test_pins_survive_after_merge_like_production_bug():
    """Regression: BM25 noise first used to bury 4.1; exact lead + pin recovers."""
    exact = Document(
        page_content="4. ГАРАНТИЙНЫЙ СРОК\n\n4.1. Гарантийный срок товара 6 месяцев.",
        metadata={
            "anchor_match": True,
            "anchor_pos": 105,
            "chunk_id": "c41",
            "chunk_level": "micro",
        },
    )
    noise_docs = [
        Document(
            page_content=f"шум {i} пункте Договора оплата",
            metadata={"chunk_id": f"n{i}", "chunk_level": "micro"},
        )
        for i in range(8)
    ]
    merged, exact_kept = _merge_exact_channel_with_lexical(
        hybrid_docs=[exact],
        lexical_docs=noise_docs,
        file_count=1,
        pool_limit=10,
    )
    assert exact_kept == 1
    assert merged[0].metadata["chunk_id"] == "c41"

    pins = select_pinned_clause_anchor_docs(merged, exact_query="4.1")
    assert len(pins) == 1
    assert pins[0].metadata["chunk_id"] == "c41"
