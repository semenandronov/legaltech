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
    norm_docs = [d for d in docs if d.metadata.get("chunk_level") == "norm"]
    assert len(norm_docs) >= 4
    clause_docs = [d for d in norm_docs if d.metadata.get("clause_ref")]
    assert len(clause_docs) >= 3
    arts = {d.metadata.get("article_number") for d in norm_docs}
    assert "1" in arts or "2" in arts
    for d in norm_docs:
        assert d.metadata.get("norm_node_key")
        assert d.metadata.get("full_path")
        assert d.metadata.get("article_number")
        assert isinstance(d.metadata.get("cross_references"), list)


def test_article_boundary_ignores_cross_ref_statyami():
    from app.services.legal_chunker import (
        _Segment,
        _group_segments_into_articles,
        _article_number_from_segment_group,
        _is_article_boundary_segment,
    )

    assert not _is_article_boundary_segment(
        _Segment(text="статьями 61.2 настоящего Федерального закона\n", section_title="56", section_number="56")
    )
    segs = [
        _Segment(text="Статья 56. Заинтересованные лица\n", section_title="Статья 56. Заинтересованные лица", section_number="56"),
        _Segment(text="1. Текст пункта.\n", section_title="Статья 56. Заинтересованные лица", section_number="56"),
        _Segment(text="статьями 61.2 настоящего Федерального закона.\n", section_title="Статья 56. Заинтересованные лица", section_number="56"),
        _Segment(text="Статья 57. Следующая\n", section_title="Статья 57. Следующая", section_number="57"),
    ]
    groups = _group_segments_into_articles(segs)
    assert len(groups) == 2
    assert _article_number_from_segment_group(groups[0]) == "56"
    assert _article_number_from_segment_group(groups[1]) == "57"


def test_consultant_html_strips_toc_and_links():
    from app.services.consultant_html_preprocess import clean_consultant_html, html_to_plain_text

    raw = """
    <html><body>
    <div>Оглавление</div>
    <a href="#Par81">Статья 1</a>
    <a id="Par81"></a>Статья 1. Тест
    <div>1. Пункт <a href="http://consultant.ru">кодекс</a>.</div>
    </body></html>
    """
    cleaned = clean_consultant_html(raw)
    assert "Оглавление" not in cleaned
    assert 'href="http://consultant.ru"' not in cleaned
    assert "Статья 1." in cleaned
    plain = html_to_plain_text(cleaned)
    assert "кодекс" in plain
    assert "consultant.ru" not in plain


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
