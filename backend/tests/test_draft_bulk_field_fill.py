"""Draft question-based fill: RAG + уникальные вопросы + подстановка."""
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.config import config
from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_field_retrieval import (
    filter_case_material_docs,
    is_editor_rag_file_id,
    resolve_bulk_case_file_ids,
    retrieve_bulk_document_context,
)
from app.services.draft_rag_query import build_bulk_rag_query
from app.services.draft_template_questions import (
    build_unique_fill_questions,
    extract_fill_question_answers,
    questions_needing_retry,
)
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
                fill_question="Какой ИНН кредитора?",
                what_to_find="ИНН кредитора",
                retrieval_query="ИНН кредитора",
                entity_role="creditor",
            ),
            TemplateFieldSpec(
                field_id="ph_001",
                marker="[СУММА]",
                start_offset=10,
                end_offset=16,
                semantic_label="Сумма",
                fill_question="Какова сумма требования?",
                what_to_find="сумма требования",
                retrieval_query="сумма требования",
            ),
        ],
        indexed_html=(
            '<p>ИНН <span data-draft-field="ph_000">[ИНН]</span> '
            'сумма <span data-draft-field="ph_001">[СУММА]</span></p>'
        ),
    )


def test_is_editor_rag_file_id():
    assert is_editor_rag_file_id("editor_doc_abc")
    assert is_editor_rag_file_id("editor_foo")
    assert not is_editor_rag_file_id("1c8694f4-6177-4d9c-a666-cc7517c4fc10")


def test_filter_case_material_docs_drops_editor_chunks():
    docs = [
        Document(page_content="договор", metadata={"file_id": "real-file-1"}),
        Document(page_content="черновик", metadata={"file_id": "editor_doc_draft-1"}),
    ]
    kept = filter_case_material_docs(docs)
    assert len(kept) == 1
    assert kept[0].metadata["file_id"] == "real-file-1"


def test_resolve_bulk_case_file_ids_strips_editor_from_attached():
    ids = resolve_bulk_case_file_ids(
        None,
        "case-1",
        ["file-a", "editor_doc_old", "file-b"],
    )
    assert ids == ["file-a", "file-b"]


def test_resolve_bulk_case_file_ids_loads_case_files_from_db():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        ("pdf-1",),
        ("pdf-2",),
        ("pdf-3",),
    ]
    with patch("app.utils.database.ensure_db_session_live"):
        ids = resolve_bulk_case_file_ids(mock_db, "case-1", None)
    assert ids == ["pdf-1", "pdf-2", "pdf-3"]


def test_retrieve_bulk_document_context_scopes_to_case_files():
    rag = MagicMock()
    rag.retrieve_context.return_value = [
        Document(page_content="акт приёма", metadata={"file_id": "pdf-1"}),
        Document(page_content="старый черновик", metadata={"file_id": "editor_doc_x"}),
    ]
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        ("pdf-1",),
        ("pdf-2",),
    ]
    with patch("app.utils.database.ensure_db_session_live"):
        ctx, meta = retrieve_bulk_document_context(
            rag_service=rag,
            case_id="case-1",
            query="ИНН кредитора",
            db=mock_db,
        )
    rag.retrieve_context.assert_called_once()
    call_kw = rag.retrieve_context.call_args.kwargs
    assert call_kw["file_ids"] == ["pdf-1", "pdf-2"]
    assert "акт приёма" in ctx
    assert "старый черновик" not in ctx
    assert meta["exclude_editor_docs"] is True
    expected_max = max(4000, int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 7000) or 7000))
    assert meta["max_chars"] == expected_max


def test_build_bulk_rag_query_uses_unique_questions():
    cat = _sample_catalog()
    unique = build_unique_fill_questions(cat.field_specs)
    q = build_bulk_rag_query(
        user_context="Составь заявление",
        template_label="Заявление",
        unique_questions=unique,
    )
    assert "Составь заявление" in q
    assert "Заявление" in q
    assert "ИНН кредитора" in q
    assert "сумма" in q.lower()


def test_questions_needing_retry_empty_and_low_conf():
    unique = build_unique_fill_questions(_sample_catalog().field_specs)
    keys = [q.question_key for q in unique]
    answers = {keys[0]: "7701", keys[1]: None}
    conf = {keys[0]: 0.2, keys[1]: 0.0}
    retry = questions_needing_retry(unique, answers, conf, max_questions=8)
    retry_keys = {q.question_key for q in retry}
    assert keys[0] in retry_keys
    assert keys[1] in retry_keys


def test_execute_catalog_field_fill_question_path():
    catalog = _sample_catalog()
    unique = build_unique_fill_questions(catalog.field_specs)
    q_inn = unique[0].question_key
    q_sum = unique[1].question_key
    with patch("app.services.draft_execute_service._fill_strategy", return_value="bulk"):
        with patch("app.services.draft_execute_service._bulk_fill_enabled", return_value=True):
            with patch(
                "app.services.draft_execute_service._targeted_retry_enabled", return_value=True
            ):
                with patch(
                    "app.services.draft_execute_service.retrieve_bulk_document_context"
                ) as mock_bulk_rag:
                    with patch(
                        "app.services.draft_execute_service.extract_fill_question_answers"
                    ) as mock_extract:
                        mock_bulk_rag.return_value = ("контекст дела " * 120, {"status": "ok"})
                        mock_extract.side_effect = [
                            (
                                {q_inn: "7701000000", q_sum: None},
                                {q_inn: 0.9, q_sum: 0.0},
                            ),
                            (
                                {q_sum: "1250000"},
                                {q_sum: 0.7},
                            ),
                        ]
                        html, stats = execute_catalog_field_fill(
                            rag_service=MagicMock(),
                            case_id="c1",
                            catalog=catalog,
                            db=MagicMock(),
                        )
    mock_bulk_rag.assert_called_once()
    assert mock_extract.call_count == 2
    assert "7701000000" in html
    assert "1250000" in html
    assert stats["fill_mode"] == "question_bulk"
    assert stats["questions_total"] == 2
    assert stats["fields_filled"] == 2
    assert stats["retry_questions"] == 1
    assert stats.get("retry_mode") == "shared_context_only"


def test_extract_fill_question_answers_parses_json():
    spec = _sample_catalog().field_specs[0]
    unique = build_unique_fill_questions([spec])
    qk = unique[0].question_key
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content=f'{{"answers": {{"{qk}": {{"value": "7701000000", "confidence": 0.95}}}}}}'
    )
    answers, conf = extract_fill_question_answers(
        unique,
        "В материалах указан ИНН 7701000000",
        llm=mock_llm,
    )
    assert answers[qk] == "7701000000"
    assert conf[qk] >= 0.9
