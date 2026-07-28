"""Multi-channel retrieval: lexical recall, merge, pins, short evidence first."""

from langchain_core.documents import Document

from app.services.retrieval_channels import (
    count_term_hits,
    extract_lexical_terms,
    merge_evidence_pins,
    merge_retrieval_channels,
    prefer_short_docs_for_prompt,
    recall_lexical_term_docs,
    select_pinned_lexical_docs,
    term_matches_text,
)


def test_flexion_duplicates_do_not_inflate_hit_count():
    text = "В случае просрочки поставки уплачивается неустойка."
    n, hits = count_term_hits(
        ["просрочка", "просрочку", "неустойка"],
        text,
    )
    assert n == 2
    stems = " ".join(hits)
    assert "просроч" in stems
    assert "неустойка" in stems
    terms = extract_lexical_terms(
        "Предусмотрена ли в договоре неустойка или штраф за просрочку?"
    )
    joined = " ".join(terms)
    assert "неустойка" in joined
    assert "штраф" in joined
    assert "просроч" in joined
    assert "предусмотрена" not in joined
    assert "договоре" not in joined


def test_term_matches_russian_flexions():
    text = "За просрочку поставки Покупатель вправе взыскать неустойку в размере 0,1%."
    assert term_matches_text("неустойка", text)
    assert term_matches_text("штраф", "штраф 0,1% от цены")
    assert not term_matches_text("неустойка", "Стороны освобождаются от ответственности")


def test_merge_puts_exact_then_lexical_ahead_of_hybrid():
    exact = Document(
        page_content="4.1. Гарантийный срок 6 месяцев.",
        metadata={"chunk_id": "e", "anchor_match": True, "exact_channel": True},
    )
    lexical = Document(
        page_content="7.2. неустойку 0,1% за каждый день просрочки.",
        metadata={"chunk_id": "l", "lexical_match": True, "lexical_score": 9.0},
    )
    hybrid = Document(
        page_content="шапка договора на шесть тысяч знаков…",
        metadata={"chunk_id": "h", "combined_score": 0.99},
    )
    merged = merge_retrieval_channels(
        exact_docs=[exact],
        lexical_docs=[lexical],
        hybrid_docs=[hybrid, lexical],  # duplicate identity must keep lexical flag
    )
    assert [d.metadata["chunk_id"] for d in merged] == ["e", "l", "h"]
    assert merged[1].metadata.get("lexical_match") is True


def test_lexical_pins_and_prefer_short_lead_prompt():
    proof = Document(
        page_content="7.2. Поставщик уплачивает неустойку 0,1%.",
        metadata={
            "chunk_id": "proof",
            "chunk_level": "micro",
            "lexical_match": True,
            "lexical_score": 8.0,
        },
    )
    header = Document(
        page_content=("ДОГОВОР ПОСТАВКИ " * 400),
        metadata={"chunk_id": "hdr", "chunk_level": "macro", "combined_score": 1.0},
    )
    section = Document(
        page_content="8. ФОРС-МАЖОР. Стороны освобождаются…",
        metadata={"chunk_id": "fm", "chunk_level": "micro"},
    )
    pins = select_pinned_lexical_docs(
        [header, proof, section],
        terms=["неустойка", "штраф", "просрочка"],
    )
    assert pins and pins[0].metadata["chunk_id"] == "proof"

    ranked = merge_evidence_pins(
        exact_pins=[],
        lexical_pins=pins,
        ranked=[header, section, proof],
        final_k=3,
    )
    assert ranked[0].metadata.get("lexical_pinned") is True
    ordered = prefer_short_docs_for_prompt(ranked)
    assert ordered[0].metadata["chunk_id"] == "proof"


class _FakeStore:
    def __init__(self, chunks):
        self._chunks = chunks

    def list_chunks_by_file(self, case_id, file_id):
        return list(self._chunks)


def test_recall_lexical_term_docs_tags_and_ranks_short_hits():
    short = Document(
        page_content="7.2. неустойку 0,1% за просрочку поставки.",
        metadata={"chunk_id": "s", "chunk_level": "micro", "file_id": "f1"},
    )
    long_header = Document(
        page_content=("ДОГОВОР " * 500) + " неустойка где-то внизу",
        metadata={"chunk_id": "long", "chunk_level": "macro", "file_id": "f1"},
    )
    miss = Document(
        page_content="1.1. Предмет договора — поставка оборудования.",
        metadata={"chunk_id": "m", "chunk_level": "micro", "file_id": "f1"},
    )
    store = _FakeStore([long_header, miss, short])
    docs = recall_lexical_term_docs(
        case_id="c1",
        file_ids=["f1"],
        terms=["неустойка", "штраф", "просрочка"],
        vector_store=store,
        k=5,
    )
    assert docs
    assert docs[0].metadata["chunk_id"] == "s"
    assert docs[0].metadata.get("lexical_match") is True
    assert "неустойка" in " ".join(docs[0].metadata.get("lexical_term_hits") or [])
