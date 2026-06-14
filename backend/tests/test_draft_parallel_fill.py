"""Тесты parallel unified fill pipeline."""
from unittest.mock import MagicMock, patch

from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_fill_pipeline import (
    merge_question_rag_context,
    overlay_deterministic_answers,
    representative_fields_for_questions,
)
from app.services.draft_template_questions import build_unique_fill_questions
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec


def _bankruptcy_catalog() -> TemplateFieldCatalogSnapshot:
    return TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:creditor_ul_general",
        engine="docxtpl",
        field_specs=[
            TemplateFieldSpec(
                field_id="v_creditor",
                marker="{{ creditor_name }}",
                start_offset=0,
                end_offset=1,
                variable="creditor_name",
                question_key="creditor_name",
                fill_question="Наименование кредитора?",
                retrieval_query="наименование кредитора",
            ),
            TemplateFieldSpec(
                field_id="v_debt",
                marker="{{ debt_main }}",
                start_offset=2,
                end_offset=3,
                variable="debt_main",
                question_key="debt_main",
                fill_question="Сумма основного долга?",
                retrieval_query="сумма основного долга",
            ),
            TemplateFieldSpec(
                field_id="v_doc_date",
                marker="{{ doc_date }}",
                start_offset=4,
                end_offset=5,
                variable="doc_date",
                question_key="doc_date",
                fill_question="Дата документа?",
                retrieval_query="дата документа",
            ),
        ],
        indexed_html="<p>{{ creditor_name }} {{ debt_main }} {{ doc_date }}</p>",
    )


def test_representative_fields_one_per_question():
    cat = _bankruptcy_catalog()
    unique = build_unique_fill_questions(cat.field_specs)
    reps = representative_fields_for_questions(unique, cat.field_specs)
    assert len(reps) == 3
    assert {r.variable for r in reps} == {"creditor_name", "debt_main", "doc_date"}


def test_merge_question_rag_context_labels():
    cat = _bankruptcy_catalog()
    unique = build_unique_fill_questions(cat.field_specs)
    rag = {
        "v_creditor": "ООО ТехноСфера — кредитор",
        "v_debt": "долг 3 000 000 руб.",
    }
    merged, meta = merge_question_rag_context(unique, rag)
    assert "[creditor_name]" in merged
    assert "ТехноСфера" in merged
    assert "[debt_main]" in merged
    assert meta["questions_with_context"] == 2
    assert "[doc_date]" not in merged


def test_overlay_deterministic_answers_prefers_calculator():
    answers = {"debt_main": "100", "doc_date": None}
    conf = {"debt_main": 0.5, "doc_date": 0.0}
    overlay_deterministic_answers(
        answers,
        conf,
        calculator_variables={"debt_main": "3000000", "debt_total": "3100000"},
        auto_defaults={"doc_date": "09.06.2026"},
    )
    assert answers["debt_main"] == "3000000"
    assert conf["debt_main"] >= 0.95
    assert answers["debt_total"] == "3100000"
    assert answers["doc_date"] == "09.06.2026"


@patch("app.services.draft_fill_pipeline.finalize_catalog_render")
@patch("app.services.draft_fill_pipeline.extract_variable_answers")
@patch("app.services.draft_fill_pipeline.attach_calculator_context_for_fill")
@patch("app.services.draft_fill_pipeline.retrieve_fields_parallel")
def test_execute_parallel_unified_fill_flow(
    mock_parallel,
    mock_calc,
    mock_extract,
    mock_finalize,
):
    catalog = _bankruptcy_catalog()
    mock_calc.side_effect = [
        (
            "ЗАПРОС: долг 3 млн\n\nКАЛЬКУЛЯТОР",
            {
                "calculator_applied": True,
                "calculator_variables": {
                    "debt_main": "3000000",
                    "debt_total": "3050000",
                    "debt_penalty": "50000",
                    "state_duty": "45000",
                },
            },
        ),
    ]
    mock_parallel.return_value = {
        "v_creditor": ("ООО ТехноСфера", {"status": "ok"}),
        "v_debt": ("сумма 3 000 000", {"status": "ok"}),
        "v_doc_date": ("", {"status": "no_snippets"}),
    }
    mock_extract.return_value = (
        {"creditor_name": "ООО «ТехноСфера»", "debt_main": None, "doc_date": None},
        {"creditor_name": 0.9, "debt_main": 0.0, "doc_date": 0.0},
    )
    mock_finalize.return_value = ("<p>filled</p>", {"fill_context": {}, "render_engine": "html_spans"})

    with patch("app.services.draft_execute_service._fill_strategy", return_value="parallel"):
        html, stats = execute_catalog_field_fill(
            rag_service=MagicMock(),
            case_id="case-1",
            catalog=catalog,
            db=MagicMock(),
            user_context="Составь заявление кредитора, долг 3 млн",
        )

    mock_parallel.assert_called_once()
    assert mock_extract.call_count == 1
    extract_args = mock_extract.call_args
    merged_ctx = extract_args[0][1]
    assert "[creditor_name]" in merged_ctx
    assert stats["fill_mode"] == "parallel_unified"
    assert stats["questions_filled"] >= 2
    assert html == "<p>filled</p>"
