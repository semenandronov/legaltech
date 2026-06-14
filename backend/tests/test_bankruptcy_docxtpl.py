"""Тесты docxtpl-шаблонов банкротства."""
from pathlib import Path

import pytest

from app.services.bankruptcy_field_catalog import (
    BANKRUPTCY_FIELD_CATALOG,
    TEMPLATE_VARIABLES,
    build_extraction_model,
    get_field_description,
)
from app.services.bankruptcy_templates import (
    clear_manifest_cache,
    find_best_system_template_match,
    get_manifest_placeholders,
    get_manifest_variables,
    get_template_engine,
    list_public_templates,
)
from app.services.draft_docxtpl_service import (
    docx_to_preview_html,
    render_docxtpl,
    rendered_docx_to_html,
    scan_docxtpl_occurrences,
)
from app.services.draft_template_indexer import (
    build_specs_from_manifest_variables,
    scan_docxtpl_placeholder_occurrences,
)


DRAFT_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "draft"


@pytest.fixture(autouse=True)
def _clear_manifest():
    clear_manifest_cache()
    yield
    clear_manifest_cache()


def test_manifest_has_four_docxtpl_templates():
    templates = list_public_templates()
    assert len(templates) == 4
    assert all(t["engine"] == "docxtpl" for t in templates)


def test_template_variables_in_catalog():
    for tid, vars_list in TEMPLATE_VARIABLES.items():
        for var in vars_list:
            assert var in BANKRUPTCY_FIELD_CATALOG, f"{tid}: missing {var}"
            assert len(get_field_description(var)) > 20


def test_build_extraction_model():
    keys = TEMPLATE_VARIABLES["creditor_ul_general"][:5]
    Model = build_extraction_model(keys, model_name="TestExtract")
    assert "court_name" in Model.model_fields
    assert "creditor_name" in Model.model_fields


def test_auto_match_creditor_ul():
    tid = find_best_system_template_match(
        "составь заявление кредитора о банкротстве юридического лица"
    )
    assert tid == "creditor_ul_general"


def test_get_manifest_placeholders_docxtpl():
    ph = get_manifest_placeholders("creditor_ul_general")
    assert len(ph) == len(TEMPLATE_VARIABLES["creditor_ul_general"])
    assert ph[0]["variable"] == "court_name"
    assert "{{ court_name }}" in ph[0]["marker"]


def test_docx_files_exist():
    for tid in TEMPLATE_VARIABLES:
        docx = DRAFT_DIR / f"{tid}.docx"
        assert docx.is_file(), f"missing {docx}"


def test_docx_preview_and_render():
    docx_path = DRAFT_DIR / "creditor_ul_general.docx"
    html = docx_to_preview_html(docx_path)
    occs = scan_docxtpl_placeholder_occurrences(html)
    assert len(occs) >= 10
    vars_found = {var for var, _, _, _ in scan_docxtpl_occurrences(html)}
    assert "court_name" in vars_found
    context = {var: f"TEST_{var}" for var in get_manifest_variables("creditor_ul_general")}
    rendered = render_docxtpl(docx_path, context)
    out_html = rendered_docx_to_html(rendered)
    assert "TEST_court_name" in out_html
    assert "{{ court_name }}" not in out_html


def test_build_specs_from_manifest_variables():
    docx_path = DRAFT_DIR / "creditor_ul_general.docx"
    html = docx_to_preview_html(docx_path)
    occs = scan_docxtpl_placeholder_occurrences(html)
    placeholders = get_manifest_placeholders("creditor_ul_general")
    specs = build_specs_from_manifest_variables(
        html,
        occs,
        placeholders=placeholders,
        template_title="Тест",
    )
    assert len(specs) == len(occs)
    keys = {s.question_key for s in specs if s.marker == "{{ creditor_name }}"}
    assert keys == {"creditor_name"}
