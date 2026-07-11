"""Тесты подготовки PDF законов для справочника."""
from __future__ import annotations

from app.services.consultant_pdf_preprocess import (
    clean_legal_pdf_text,
    is_consultant_plus_pdf,
    should_preprocess_legal_pdf,
)
from app.services.legal_chunker import LegalChunkerV2


SAMPLE_PDF_TEXT = """
КонсультантПлюс
www.consultant.ru

Оглавление
Статья 1 ........ 5
Статья 2 ........ 8

1

Статья 61.1. Общие положения
1. Сделка, совершенная должником, может быть признана недействительной.
2. В порядке, установленном ст. 61.3 настоящего Федерального закона, применяются нормы ГК РФ.

Статья 61.2. Подозрительные сделки
1. Сделка, совершенная должником во вред кредиторам, может быть оспорена.
"""


def test_clean_legal_pdf_text_strips_toc_and_watermark():
    cleaned = clean_legal_pdf_text(SAMPLE_PDF_TEXT)
    assert "КонсультантПлюс" not in cleaned
    assert "Оглавление" not in cleaned
    assert cleaned.lstrip().startswith("Статья 61.1")
    assert "Статья 61.2" in cleaned


def test_should_preprocess_legal_pdf_for_fz127():
    assert should_preprocess_legal_pdf(instrument_id="fz-127", ext="pdf")
    assert not should_preprocess_legal_pdf(instrument_id="fz-127", ext="html")


def test_chunk_corpus_norms_from_pdf_prepared_text():
    cleaned = clean_legal_pdf_text(SAMPLE_PDF_TEXT)
    chunker = LegalChunkerV2()
    docs = chunker.chunk_corpus_norms(
        content_bytes=None,
        filename="127fz-glava-VI.pdf",
        base_metadata={
            "file_id": "pdf-test",
            "instrument_id": "fz-127",
            "instrument_short_name": "127-ФЗ",
            "case_id": "GLOBAL_LEGAL_CORPUS",
            "doc_type": "legal_reference",
        },
        prepared_pdf_text=cleaned,
    )
    norm_docs = [d for d in docs if d.metadata.get("chunk_level") == "norm"]
    assert len(norm_docs) >= 2
    arts = {d.metadata.get("article_number") for d in norm_docs}
    assert "61.1" in arts
    assert "61.2" in arts


def test_is_consultant_plus_pdf_by_content():
    raw = SAMPLE_PDF_TEXT.encode("utf-8")
    assert is_consultant_plus_pdf(b"%PDF-1.4\n" + raw, filename="127-fz.pdf")
