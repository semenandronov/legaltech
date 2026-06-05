"""Tests for tabular evidence-first verification."""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.services.tabular_cell_verification import (
    apply_evidence_first_policy,
    assess_evidence,
    quote_exists_in_document,
)
from app.services.tabular_extraction_policy import (
    coerce_source_references,
    count_nonempty_cells,
    is_na_cell_value,
)
from app.services.tabular_review_models import TabularCellExtractionModel


def _file(text: str = "Договор поставки между сторонами заключён 01.01.2024"):
    return SimpleNamespace(id="file-1", original_text=text)


def _column(column_type: str = "document_type", **cfg):
    return SimpleNamespace(
        column_type=column_type,
        column_config=cfg or None,
    )


def test_coerce_source_references_normalizes_llm_shapes():
    assert coerce_source_references(None) == []
    assert coerce_source_references("цитата") == [{"text": "цитата"}]
    assert coerce_source_references([{"text": "a"}, "b"]) == [{"text": "a"}, {"text": "b"}]


def test_count_nonempty_cells_excludes_na():
    cells = [
        {"cell_value": "Договор"},
        {"cell_value": "N/A"},
        {"cell_value": ""},
        {"cell_value": "—"},
    ]
    assert count_nonempty_cells(cells) == 1
    assert is_na_cell_value("N/A")
    assert not is_na_cell_value("Договор")


def test_quote_exists_in_document():
    f = _file("Договор поставки между сторонами")
    assert quote_exists_in_document("Договор поставки", f)
    assert not quote_exists_in_document("несуществующая цитата xyz", f)


def test_assess_evidence_chunk_provenance():
    result = TabularCellExtractionModel(
        cell_value="Договор",
        reasoning="r",
        column_type="document_type",
    )
    docs = [Document(page_content="x", metadata={"char_start": 0, "char_end": 50})]
    ev = assess_evidence(result, _file(), docs)
    assert ev.has_sufficient_evidence


def test_fact_column_without_evidence_forced_to_na(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_extraction_policy.config.TABULAR_EVIDENCE_REQUIRED",
        True,
        raising=False,
    )
    result = TabularCellExtractionModel(
        cell_value="Договор поставки",
        reasoning="угадано",
        column_type="document_type",
        confidence=0.95,
    )
    outcome = apply_evidence_first_policy(
        result,
        column=_column("document_type"),
        file=_file("совсем другой текст без договора"),
        included_docs=[],
    )
    assert outcome.forced_na
    assert outcome.result.cell_value == "N/A"
    assert "missing_evidence" in outcome.issues


def test_text_column_without_evidence_keeps_value_but_needs_review(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_extraction_policy.config.TABULAR_EVIDENCE_REQUIRED",
        True,
        raising=False,
    )
    result = TabularCellExtractionModel(
        cell_value="Краткое описание документа",
        reasoning="summary",
        column_type="text",
        confidence=0.9,
    )
    outcome = apply_evidence_first_policy(
        result,
        column=_column("text"),
        file=_file("нет совпадений в тексте"),
        included_docs=[],
    )
    assert outcome.needs_review
    assert not outcome.forced_na
    assert outcome.result.cell_value == "Краткое описание документа"
    assert outcome.result.confidence <= 0.45


def test_evidence_from_grounded_quote_passes_fact_column(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_extraction_policy.config.TABULAR_EVIDENCE_REQUIRED",
        True,
        raising=False,
    )
    doc_text = "Договор поставки между ООО Альфа и ООО Бета"
    result = TabularCellExtractionModel(
        cell_value="Договор поставки",
        verbatim_extract="Договор поставки между ООО Альфа",
        reasoning="найдено в шапке",
        column_type="document_type",
        confidence=0.88,
        source_references=[{"text": "Договор поставки между ООО Альфа"}],
    )
    outcome = apply_evidence_first_policy(
        result,
        column=_column("document_type"),
        file=_file(doc_text),
        included_docs=[],
    )
    assert not outcome.forced_na
    assert not outcome.needs_review
    assert outcome.result.cell_value == "Договор поставки"
