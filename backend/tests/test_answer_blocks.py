"""Unit tests for Phase 2 answer_blocks grounding validation."""

from app.services.chat.answer_blocks import validate_answer_blocks_grounding


def test_validate_drops_unknown_citation_ids():
    citations = [
        {"citation_id": "cit_a", "quote": "договор заключён на срок один год", "quote_anchor": "один год"},
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "Срок **один год** [1]",
            "citation_ids": ["cit_a", "cit_ghost"],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations)
    assert len(out) == 1
    assert "cit_a" in out[0]["citation_ids"]
    assert "cit_ghost" not in out[0]["citation_ids"]
    assert "[" not in out[0]["markdown_text"]


def test_validate_drops_low_overlap():
    citations = [
        {
            "citation_id": "cit_x",
            "quote": "совершенно другой текст про налоговую базу",
            "quote_anchor": "налоговую базу",
        },
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "Стороны договорились о поставке оборудования в течение месяца.",
            "citation_ids": ["cit_x"],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations, min_jaccard=0.2)
    assert out[0]["citation_ids"] == []


def test_validate_sorts_citation_ids_by_catalog_order():
    """Чипы в UI идут в порядке каталога, даже если модель вернула id в обратном порядке."""
    citations = [
        {
            "citation_id": "cit_first",
            "quote": "срок поставки составляет тридцать дней",
            "quote_anchor": "срок поставки",
        },
        {
            "citation_id": "cit_second",
            "quote": "поставка оборудования должна быть выполнена в течение тридцати дней",
            "quote_anchor": "поставка оборудования",
        },
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "Срок поставки и поставка оборудования согласованы на **тридцать дней**.",
            "citation_ids": ["cit_second", "cit_first"],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations, min_jaccard=0.04)
    assert out[0]["citation_ids"] == ["cit_first", "cit_second"]


def test_validate_keeps_related_overlap():
    citations = [
        {
            "citation_id": "cit_y",
            "quote": "поставка оборудования должна быть выполнена в течение тридцати дней",
            "quote_anchor": "поставка оборудования",
        },
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "Поставка оборудования согласована на период в **тридцать дней**.",
            "citation_ids": ["cit_y"],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations, min_jaccard=0.04)
    assert "cit_y" in out[0]["citation_ids"]


def test_validate_backfills_when_model_left_citation_ids_empty():
    """Содержательный блок без id — одна цитата с максимальным пересечением."""
    citations = [
        {
            "citation_id": "cit_obj",
            "quote": "возражения представителя должника против требований о реализации имущества",
            "quote_anchor": "возражения представителя должника",
        },
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "В документе изложены **возражения представителя должника** против процедуры **реализации имущества** в рамках дела о несостоятельности.",
            "citation_ids": [],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations, min_jaccard=0.06)
    assert out[0]["citation_ids"] == ["cit_obj"]


def test_validate_backfill_skips_disclaimer_blocks():
    citations = [
        {
            "citation_id": "cit_any",
            "quote": "любой текст из дела для проверки",
            "quote_anchor": "любой текст",
        },
    ]
    blocks = [
        {
            "block_id": "b1",
            "markdown_text": "Для полной квалификации **не хватает** номера дела, наименования суда и дат процессуальных действий.",
            "citation_ids": [],
        }
    ]
    out = validate_answer_blocks_grounding(blocks, citations, min_jaccard=0.06)
    assert out[0]["citation_ids"] == []
