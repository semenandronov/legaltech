from __future__ import annotations

from app.services.chat.reference_resolver import (
    ReferenceKind,
    classify_reference_intent,
    evidence_matches_case_numbers,
    extract_referenced_case_numbers,
)


def test_classify_case_number_only():
    intent = classify_reference_intent("А19-23660/2017")
    assert intent.kind is ReferenceKind.CASE_NUMBER
    assert "А19-23660/2017" in intent.case_numbers or intent.case_numbers


def test_classify_explicit_recap():
    intent = classify_reference_intent("повтори про то дело")
    assert intent.kind in (ReferenceKind.EXPLICIT_RECAP, ReferenceKind.DEICTIC)


def test_classify_deictic():
    intent = classify_reference_intent("а что с презумпцией в том деле?")
    assert intent.kind is ReferenceKind.DEICTIC
    assert intent.should_resolve


def test_classify_ordinal():
    intent = classify_reference_intent("расскажи подробнее про первое дело")
    assert intent.kind is ReferenceKind.ORDINAL_CASE
    assert intent.ordinal_index == 0


def test_classify_new_question_not_reference():
    intent = classify_reference_intent(
        "Субсидиарная ответственность за непередачу бухгалтерской документации "
        "должника при банкротстве: какие позиции ВС РФ?"
    )
    assert intent.kind is ReferenceKind.NONE


def test_extract_case_numbers():
    nums = extract_referenced_case_numbers("интересует дело А03-8991/2021 и А19-23660/2017")
    assert len(nums) >= 2


def test_evidence_matches_case_numbers():
    evidence = {
        "case_numbers": ["А19-23660/2017"],
        "citations": [{"source_type": "court_practice", "file_name": "А19-23660/2017"}],
    }
    assert evidence_matches_case_numbers(
        evidence,
        targets=["А19-23660/2017"],
        content="",
    )
