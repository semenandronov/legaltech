"""Case card metadata intent + deterministic answers."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.models.case import Case
from app.services.chat.case_metadata_service import (
    CaseMetadataKind,
    classify_case_metadata_intent,
    is_case_metadata_question,
    normalize_question_for_metadata,
    resolve_case_metadata_answer,
)


def test_typo_lkumentov_docs_count():
    q = "сколько лкументов загружено в дело"
    assert normalize_question_for_metadata(q) == "сколько документов загружено в дело"
    assert classify_case_metadata_intent(q) is CaseMetadataKind.DOCS_COUNT


@pytest.mark.parametrize(
    "question",
    [
        "сколько документов в деле",
        "количество документов в деле",
        "сколько файлов загружено в дело",
        "число документов в материалах дела",
    ],
)
def test_docs_count_phrasings(question):
    assert classify_case_metadata_intent(question) is CaseMetadataKind.DOCS_COUNT


@pytest.mark.parametrize(
    "question",
    [
        "о чем документы кратко",
        "краткое содержание документов",
        "обзор документов в деле",
    ],
)
def test_overview_not_metadata(question):
    assert classify_case_metadata_intent(question) is None


def test_resolve_docs_count_answer():
    db = MagicMock()
    case = Case(
        id="case-1",
        title="Test",
        num_documents=4,
        status="active",
        created_at=datetime(2024, 1, 15),
    )
    db.query.return_value.filter.return_value.first.return_value = case

    reply = resolve_case_metadata_answer(
        db, case_id="case-1", question="сколько лкументов загружено в дело"
    )
    assert reply is not None
    assert reply.kind is CaseMetadataKind.DOCS_COUNT
    assert "4" in reply.content
    assert "документ" in reply.content.lower()
    assert reply.citation["file_name"] == "Карточка дела"


def test_status_and_title():
    assert classify_case_metadata_intent("статус дела") is CaseMetadataKind.STATUS
    assert classify_case_metadata_intent("название дела") is CaseMetadataKind.TITLE


def test_is_case_metadata_question():
    assert is_case_metadata_question("сколько документов загружено")
    assert not is_case_metadata_question("о чем первый документ")
