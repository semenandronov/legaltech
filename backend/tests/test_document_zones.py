"""Tests for document zone inference and tabular zone routing."""

from langchain_core.documents import Document

from app.services.document_zones import (
    annotate_documents_with_zones,
    infer_chunk_zone,
    prefer_zone_docs_for_prompt,
)
from app.services.tabular_column_type_contract import validate_column_config
from app.services.tabular_zone_routing import infer_preferred_zones
import pytest


def test_infer_preamble_from_chunk_level():
    assert (
        infer_chunk_zone(
            page_content="ООО Альфа именуемое Арендодатель",
            metadata={"chunk_level": "preamble"},
        )
        == "preamble"
    )


def test_infer_table_from_row_level():
    assert (
        infer_chunk_zone(
            page_content="1 | Май | 41996",
            metadata={"chunk_level": "row", "is_table": True},
        )
        == "table"
    )


def test_infer_requisites_from_inn_kpp():
    text = "ИНН 7707083893 КПП 770701001 р/с 40702810900000000001"
    assert infer_chunk_zone(page_content=text, metadata={}) == "requisites"


def test_infer_signature_near_end():
    text = "В удостоверение чего стороны поставили свои подписи / М.П."
    assert (
        infer_chunk_zone(
            page_content=text,
            metadata={"char_start": 9000},
            document_chars=10000,
        )
        == "signature"
    )


def test_annotate_documents_with_zones():
    docs = [
        Document(
            page_content="Шапка договора",
            metadata={"chunk_level": "preamble", "char_start": 0, "char_end": 20},
        ),
        Document(
            page_content="1. ПРЕДМЕТ ДОГОВОРА Стороны согласовали",
            metadata={"chunk_level": "micro", "char_start": 500, "char_end": 600},
        ),
    ]
    annotate_documents_with_zones(docs, document_chars=2000)
    assert docs[0].metadata["zone"] == "preamble"
    assert docs[1].metadata["zone"] == "body"


def test_prefer_zone_docs_for_prompt_orders_preferred_first():
    docs = [
        Document(page_content="body", metadata={"zone": "body"}),
        Document(page_content="req", metadata={"zone": "requisites"}),
        Document(page_content="pre", metadata={"zone": "preamble"}),
    ]
    ordered = prefer_zone_docs_for_prompt(docs, ["preamble", "requisites"])
    assert [d.metadata["zone"] for d in ordered] == [
        "requisites",
        "preamble",
        "body",
    ]


def test_infer_preferred_zones_from_prompt_inn():
    zones = infer_preferred_zones(
        column_type="text",
        column_label="ИНН",
        prompt="Укажи ИНН ООО Смарт Сити",
    )
    assert zones[0] == "requisites"


def test_infer_preferred_zones_explicit_config_wins():
    zones = infer_preferred_zones(
        column_type="text",
        prompt="ИНН компании",
        column_config={"preferred_zones": ["table", "body"]},
    )
    assert zones == ("table", "body")


def test_validate_preferred_zones_rejects_unknown():
    with pytest.raises(ValueError, match="preferred_zones"):
        validate_column_config("text", {"preferred_zones": ["galaxy"]})


def test_validate_preferred_zones_accepts_valid():
    validate_column_config("text", {"preferred_zones": ["preamble", "requisites"]})
