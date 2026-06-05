"""Draft execute: каталог полей без full-HTML fallback."""
from unittest.mock import MagicMock, patch

from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec


def test_execute_catalog_field_fill_applies_values():
    catalog = TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:test",
        field_specs=[
            TemplateFieldSpec(
                field_id="ph_000",
                marker="[ИНН]",
                start_offset=3,
                end_offset=8,
                semantic_label="ИНН",
                what_to_find="ИНН",
                retrieval_query="ИНН кредитора",
            ),
        ],
        indexed_html='<p>ИНН <span data-draft-field="ph_000">[ИНН]</span></p>',
    )
    with patch("app.services.draft_execute_service._bulk_fill_enabled", return_value=False):
        with patch("app.services.draft_execute_service.retrieve_fields_parallel") as mock_rag:
            with patch("app.services.draft_execute_service.extract_fields_batch") as mock_ext:
                mock_rag.return_value = {"ph_000": ("ИНН 7701000000", {})}
                mock_ext.return_value = {"ph_000": "7701000000"}
                html, stats = execute_catalog_field_fill(
                    rag_service=MagicMock(),
                    case_id="c1",
                    catalog=catalog,
                    db=MagicMock(),
                )
    assert stats.get("fill_mode") == "per_field"
    assert "7701000000" in html
    assert stats["fields_filled"] == 1
    assert stats["replacement_ops"] >= 1


def test_full_html_fallback_disabled_by_default():
    from app.config import config

    assert getattr(config, "DRAFT_FULL_HTML_FALLBACK_ENABLED", False) is False
