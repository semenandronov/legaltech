"""Draft bulk fill: один RAG + unified extract + точечный дожим."""
from unittest.mock import MagicMock, patch

from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_field_fill import (
    extract_fields_unified,
    fields_needing_targeted_retry,
)
from app.services.draft_rag_query import build_bulk_rag_query
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec


def _sample_catalog() -> TemplateFieldCatalogSnapshot:
    return TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:test",
        field_specs=[
            TemplateFieldSpec(
                field_id="ph_000",
                marker="[ИНН]",
                start_offset=3,
                end_offset=8,
                semantic_label="ИНН",
                what_to_find="ИНН кредитора",
                retrieval_query="ИНН кредитора",
            ),
            TemplateFieldSpec(
                field_id="ph_001",
                marker="[СУММА]",
                start_offset=10,
                end_offset=16,
                semantic_label="Сумма",
                what_to_find="сумма требования",
                retrieval_query="сумма требования",
            ),
        ],
        indexed_html=(
            '<p>ИНН <span data-draft-field="ph_000">[ИНН]</span> '
            'сумма <span data-draft-field="ph_001">[СУММА]</span></p>'
        ),
    )


def test_build_bulk_rag_query_includes_fields():
    cat = _sample_catalog()
    q = build_bulk_rag_query(
        user_context="Составь заявление",
        template_label="Заявление",
        field_specs=cat.field_specs,
    )
    assert "Составь заявление" in q
    assert "Заявление" in q
    assert "ИНН" in q
    assert "сумма" in q.lower()


def test_fields_needing_targeted_retry_empty_and_low_conf():
    fields = _sample_catalog().field_specs
    values = {"ph_000": "7701", "ph_001": None}
    conf = {"ph_000": 0.2, "ph_001": 0.0}
    retry = fields_needing_targeted_retry(fields, values, conf, max_fields=8)
    ids = {f.field_id for f in retry}
    assert "ph_000" in ids
    assert "ph_001" in ids


def test_execute_catalog_field_fill_bulk_path():
    catalog = _sample_catalog()
    with patch("app.services.draft_execute_service._bulk_fill_enabled", return_value=True):
        with patch(
            "app.services.draft_execute_service._targeted_retry_enabled", return_value=True
        ):
            with patch(
                "app.services.draft_execute_service.retrieve_bulk_document_context"
            ) as mock_bulk_rag:
                with patch(
                    "app.services.draft_execute_service.extract_fields_unified"
                ) as mock_unified:
                    mock_bulk_rag.return_value = ("контекст дела " * 120, {"status": "ok"})
                    mock_unified.side_effect = [
                        (
                            {"ph_000": "7701000000", "ph_001": None},
                            {"ph_000": 0.9, "ph_001": 0.0},
                        ),
                        ({"ph_001": "1250000"}, {"ph_001": 0.7}),
                    ]
                    html, stats = execute_catalog_field_fill(
                        rag_service=MagicMock(),
                        case_id="c1",
                        catalog=catalog,
                        db=MagicMock(),
                    )
    mock_bulk_rag.assert_called_once()
    assert mock_unified.call_count == 2
    assert "7701000000" in html
    assert "1250000" in html
    assert stats["fill_mode"] == "bulk"
    assert stats["fields_filled"] == 2
    assert stats["retry_fields"] == 1
    assert stats.get("retry_mode") == "shared_context_only"


def test_extract_fields_unified_parses_json():
    fields = [_sample_catalog().field_specs[0]]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"fields": {"ph_000": {"value": "7701000000", "confidence": 0.95}}}'
    )
    values, conf = extract_fields_unified(
        fields,
        "В материалах указан ИНН 7701000000",
        llm=mock_llm,
    )
    assert values["ph_000"] == "7701000000"
    assert conf["ph_000"] >= 0.9
