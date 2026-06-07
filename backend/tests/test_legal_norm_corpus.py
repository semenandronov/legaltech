"""Тесты norm chunking и cross-ref resolver для справочника."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.legal_chunker import LegalChunkerV2
from app.services.legal_instruments import resolve_instrument
from app.services.legal_norm_cross_ref import (
    make_norm_node_key,
    parse_cross_reference,
    parse_cross_references_from_text,
)


SAMPLE_CODE = """
Глава 1. Общие положения

Статья 1. Основные понятия
1. Настоящий Федеральный закон регулирует отношения.
2. В порядке, установленном ст. 61.3 настоящего Федерального закона, применяются нормы ГК РФ.

Статья 2. Сфера применения
1. Действие настоящего Федерального закона распространяется на всех должников.
"""


def test_parse_cross_reference_forward_to():
    text = "В порядке, установленном ст. 61.3 настоящего Федерального закона"
    parsed = parse_cross_reference("ст. 61.3", source_text=text, default_instrument_id="fz-127")
    assert parsed is not None
    assert parsed.article_number == "61.3"
    assert parsed.edge_type == "FORWARD_TO"
    assert parsed.target_instrument_id == "fz-127"


def test_parse_cross_reference_gk_hint():
    text = "согласно ст. 10 ГК РФ"
    parsed = parse_cross_reference("ст. 10 ГК РФ", source_text=text)
    assert parsed is not None
    assert parsed.article_number == "10"
    assert parsed.target_instrument_id == "gk-rf"


def test_make_norm_node_key_stable():
    key = make_norm_node_key("fz-127", "61.3")
    assert key == "fz-127::art::61.3"
    key2 = make_norm_node_key("fz-127", "61.3", clause_ref="2")
    assert key2 == "fz-127::art::61.3::clause::2"


def test_chunk_corpus_norms_article_metadata():
    chunker = LegalChunkerV2()
    docs = chunker.chunk_corpus_norms(
        content_bytes=None,
        filename="127-fz.txt",
        base_metadata={
            "file_id": "test-file",
            "instrument_id": "fz-127",
            "instrument_short_name": "127-ФЗ",
            "case_id": "GLOBAL_LEGAL_CORPUS",
            "doc_type": "legal_reference",
        },
        fallback_text=SAMPLE_CODE,
    )
    assert len(docs) >= 2
    norm_docs = [d for d in docs if d.metadata.get("chunk_level") == "norm"]
    assert norm_docs
    arts = {d.metadata.get("article_number") for d in norm_docs}
    assert "1" in arts or "2" in arts
    for d in norm_docs:
        assert d.metadata.get("norm_node_key")
        assert d.metadata.get("full_path")
        assert d.metadata.get("article_number")
        assert isinstance(d.metadata.get("cross_references"), list)


def test_instrument_priority_and_validity():
    inst = resolve_instrument("fz-127")
    assert inst is not None
    assert inst.norm_class == "special"
    assert inst.priority_weight > 1.0
    assert inst.valid_from is not None


def test_parse_multiple_refs():
    refs = parse_cross_references_from_text(
        "см. ст. 61 и п. 2 ст. 10 ГК РФ",
        default_instrument_id="fz-127",
    )
    assert len(refs) >= 2
