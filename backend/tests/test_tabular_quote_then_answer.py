"""Unit tests for quote-then-answer grounding helpers."""

from app.services.tabular_quote_then_answer import (
    canonicalize_extraction_quotes,
    quote_grounded_in_corpus,
    resolve_quote_span_in_original,
    snap_quote_to_corpus,
    tabular_quote_then_answer_enabled,
)
from app.services.tabular_review_models import TabularCellExtractionModel


def test_quote_grounded_rejects_short_and_missing():
    assert not quote_grounded_in_corpus("short", "short text here")
    assert not quote_grounded_in_corpus(
        "completely different invented clause about widgets",
        "Material Adverse Effect means any change",
    )


def test_quote_grounded_head_tail_tolerance():
    head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    mid = " UNIQUE_MIDDLE_TOKEN "
    tail = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    quote = head + mid + tail
    # Corpus contains head and tail but not the middle (simulates packing cut).
    corpus = f"prefix {head} ...packed... {tail} suffix"
    assert quote_grounded_in_corpus(quote, corpus)
    # Soft grounding is not a contiguous snap target.
    assert snap_quote_to_corpus(quote, corpus) is None


def test_snap_quote_returns_corpus_text_not_model_paraphrase():
    corpus = (
        "передать во временное владение и пользование Арендатору недвижимое имущество – "
        "нежилые помещения (номера на поэтажном плане 3,\n4, 5, 6, 7, 8, 18), общей площадью "
        "83,3 кв. м, расположенные по адресу: г. Иркутск, ул. Байкальская, д.\n250 А "
        "(далее по тексту – «Объект аренды»)"
    )
    # Model rewrote недвижимое → нежилое and flattened newlines.
    quote = (
        "нежилое имущество – нежилые помещения (номера на поэтажном плане 3, 4, 5, 6, 7, 8, 18), "
        "общей площадью 83,3 кв. м, расположенные по адресу: г. Иркутск, ул. Байкальская, д. 250 А "
        "(далее по тексту – «Объект аренды»)"
    )
    snapped = snap_quote_to_corpus(quote, corpus)
    assert snapped is not None
    assert "нежилое имущество" not in snapped
    assert "недвижимое имущество" in snapped or "нежилые помещения" in snapped
    assert "\n" in snapped or "250 А" in snapped
    span = resolve_quote_span_in_original(quote, corpus)
    assert span is not None
    assert corpus[span[0] : span[1]].strip() == snapped


def test_snap_quote_recovers_near_match():
    corpus = (
        "Material Adverse Effect means any change, event, or effect that is materially adverse "
        "to the business of the Company."
    )
    quote = (
        "Material Adverse Effect means any change event or effect that is materially adverse "
        "to the business of the Company"
    )
    snapped = snap_quote_to_corpus(quote, corpus)
    assert snapped is not None
    assert "material adverse effect" in snapped.lower()
    # Must be copied from corpus, not the model string.
    assert "change, event" in snapped


def test_canonicalize_replaces_verbatim_and_refs():
    original = (
        "Арендодатель обязуется передать недвижимое имущество – нежилые помещения "
        "по адресу ул. Байкальская, д. 250 А (далее – «Объект аренды»)."
    )
    paraphrased = (
        "нежилое имущество – нежилые помещения по адресу ул. Байкальская, д. 250 А "
        "(далее – «Объект аренды»)"
    )
    result = TabularCellExtractionModel(
        cell_value="нежилые помещения, 250 А",
        verbatim_extract=paraphrased,
        reasoning="из п.1.1",
        confidence=0.9,
        column_type="text",
        source_references=[{"text": paraphrased, "page": 1}],
    )
    out = canonicalize_extraction_quotes(result, original)
    assert out.verbatim_extract is not None
    assert "нежилое имущество" not in (out.verbatim_extract or "")
    assert "нежилые помещения" in (out.verbatim_extract or "")
    assert out.source_references
    ref = out.source_references[0]
    assert ref["text"] == out.verbatim_extract or "нежилые помещения" in ref["text"]
    assert ref.get("char_start") is not None
    assert ref.get("char_end") is not None
    assert original[ref["char_start"] : ref["char_end"]].strip() == ref["text"].strip()


def test_quote_then_answer_enabled_default(monkeypatch):
    monkeypatch.setattr(
        "app.config.config.TABULAR_QUOTE_THEN_ANSWER",
        True,
        raising=False,
    )
    assert tabular_quote_then_answer_enabled() is True
