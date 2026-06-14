"""Вопросы шаблона: группировка, ответы LLM, подстановка."""
from unittest.mock import MagicMock

from app.services.draft_field_fill import apply_field_values
from app.services.draft_template_indexer import inject_field_anchors, scan_placeholder_occurrences
from app.services.draft_template_questions import (
    assign_question_metadata,
    build_fill_question,
    build_unique_fill_questions,
    extract_fill_question_answers,
    propagate_answers_to_fields,
    question_key_for_fill_question,
    questions_needing_retry,
)
from app.services.draft_template_schemas import TemplateFieldSpec


def _creditor_name_specs(count: int = 3) -> list[TemplateFieldSpec]:
    specs = []
    for i in range(count):
        specs.append(
            TemplateFieldSpec(
                field_id=f"ph_{i:03d}",
                marker="[наименование кредитора]",
                occurrence_index=i,
                start_offset=i * 10,
                end_offset=i * 10 + 5,
                context_snippet="Кредитор:",
                entity_role="creditor",
                fill_question="Какое наименование кредитора?",
            )
        )
    return specs


def test_same_fill_question_gets_same_question_key():
    specs = _creditor_name_specs(4)
    finalized, unique = assign_question_metadata(specs)
    keys = {s.question_key for s in finalized}
    assert len(keys) == 1
    assert len(unique) == 1
    assert unique[0].occurrence_count == 4


def test_different_entity_roles_get_different_questions():
    specs = [
        TemplateFieldSpec(
            field_id="ph_000",
            marker="[ИНН]",
            entity_role="creditor",
            context_snippet="Кредитор",
        ),
        TemplateFieldSpec(
            field_id="ph_001",
            marker="[ИНН]",
            entity_role="debtor",
            context_snippet="Должник",
        ),
    ]
    unique = build_unique_fill_questions(specs)
    assert len(unique) == 2
    assert unique[0].fill_question != unique[1].fill_question


def test_propagate_one_answer_to_all_occurrences():
    specs = _creditor_name_specs(4)
    finalized, unique = assign_question_metadata(specs)
    qk = unique[0].question_key
    values, conf = propagate_answers_to_fields(
        finalized,
        {qk: "ООО «Вектор-М»"},
        {qk: 0.95},
    )
    assert all(v == "ООО «Вектор-М»" for v in values.values())
    assert len(values) == 4


def test_apply_propagated_values_in_html():
    html = "<p>A [наименование кредитора]</p><p>B [наименование кредитора]</p>"
    occs = scan_placeholder_occurrences(html)
    specs = []
    for i, o in enumerate(occs):
        specs.append(
            TemplateFieldSpec(
                field_id=f"ph_{i:03d}",
                marker=o.marker,
                occurrence_index=o.occurrence_index,
                start_offset=o.start_offset,
                end_offset=o.end_offset,
                entity_role="creditor",
                fill_question="Какое наименование кредитора?",
            )
        )
    finalized, unique = assign_question_metadata(specs)
    indexed = inject_field_anchors(html, finalized)
    qk = unique[0].question_key
    values, _ = propagate_answers_to_fields(finalized, {qk: "ООО «Вектор-М»"})
    out, n = apply_field_values(indexed, values)
    assert n == 2
    assert out.count("ООО «Вектор-М»") == 2
    assert "[наименование кредитора]" not in out


def test_extract_fill_question_answers_parses_json():
    specs = _creditor_name_specs(1)
    unique = build_unique_fill_questions(specs)
    qk = unique[0].question_key
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content=f'{{"answers": {{"{qk}": {{"value": "ООО «Вектор-М»", "confidence": 0.9}}}}}}'
    )
    answers, conf = extract_fill_question_answers(
        unique,
        "договор с Вектор-М",
        user_context="кредитор ООО Вектор-М",
        llm=mock_llm,
    )
    assert answers[qk] == "ООО «Вектор-М»"
    assert conf[qk] >= 0.9


def test_questions_needing_retry():
    specs = _creditor_name_specs(2)
    unique = build_unique_fill_questions(specs)
    qk = unique[0].question_key
    retry = questions_needing_retry(unique, {qk: None}, {qk: 0.0}, max_questions=5)
    assert len(retry) == 1


def test_build_fill_question_from_marker_and_role():
    spec = TemplateFieldSpec(
        field_id="ph_000",
        marker="[ИНН кредитора]",
        entity_role="creditor",
        context_snippet="таблица кредитор",
    )
    q = build_fill_question(spec)
    assert "ИНН" in q
    assert "кредитор" in q.lower()
    assert q.endswith("?")


def test_question_key_stable_for_same_text():
    a = question_key_for_fill_question("Какой ИНН кредитора?")
    b = question_key_for_fill_question("Какой ИНН кредитора?")
    assert a == b


def test_unify_semantic_duplicate_questions():
    from app.services.draft_template_questions import unify_semantic_duplicate_questions

    specs = _creditor_name_specs(3)
    specs[0] = specs[0].model_copy(update={"fill_question": "Какое полное наименование кредитора?"})
    specs[1] = specs[1].model_copy(update={"fill_question": "Наименование кредитора?"})
    specs[2] = specs[2].model_copy(update={"fill_question": "Какое наименование кредитора?"})
    unified = unify_semantic_duplicate_questions(specs)
    questions = {s.fill_question for s in unified}
    assert len(questions) == 1


def test_sanitize_rejects_generic_question():
    from app.services.draft_template_questions import sanitize_fill_question

    spec = TemplateFieldSpec(
        field_id="ph_000",
        marker="[ИНН кредитора]",
        entity_role="creditor",
        context_snippet="Кредитор",
    )
    q = sanitize_fill_question("Найти в материалах дела значение для поля", spec)
    assert "ИНН" in q
    assert q.endswith("?")


def test_audit_template_questions():
    from app.services.draft_template_questions import audit_template_questions

    specs = _creditor_name_specs(2)
    finalized, _ = assign_question_metadata(specs)
    audit = audit_template_questions(
        template_key="bankruptcy:test",
        template_title="Тест",
        specs=finalized,
    )
    assert audit.occurrences == 2
    assert audit.unique_questions == 1

