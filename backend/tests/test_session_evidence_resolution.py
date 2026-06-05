from __future__ import annotations

from app.services.chat.evidence_bundle import build_evidence_bundle
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.session_evidence_resolution import resolve_session_evidence_reply


def _court_practice_citations(case_number: str) -> list[dict]:
    return [
        {
            "source_type": "court_practice",
            "file_name": case_number,
            "quote": f"Дело {case_number}",
            "quote_anchor": case_number,
        }
    ]


def test_resolve_by_case_number_in_case_chat(db_session, test_case):
    svc = ChatHistoryService(db_session)
    session_id = svc.get_or_create_session(test_case.id)

    evidence_a = build_evidence_bundle(
        citations=_court_practice_citations("А19-23660/2017"),
    )
    evidence_b = build_evidence_bundle(
        citations=_court_practice_citations("А03-8991/2021"),
    )

    svc.save_user_message(case_id=test_case.id, content="практика 1", session_id=session_id)
    ph1 = svc.create_assistant_placeholder(case_id=test_case.id, session_id=session_id)
    svc.update_assistant_message(
        message_id=ph1.id,
        content="Карточка по А19-23660/2017",
        evidence=evidence_a,
    )

    svc.save_user_message(case_id=test_case.id, content="практика 2", session_id=session_id)
    ph2 = svc.create_assistant_placeholder(case_id=test_case.id, session_id=session_id)
    svc.update_assistant_message(
        message_id=ph2.id,
        content="Карточка по А03-8991/2021",
        evidence=evidence_b,
    )

    reply = resolve_session_evidence_reply(
        db_session,
        scope="case",
        case_id=test_case.id,
        session_id=session_id,
        question="А19-23660/2017",
    )
    assert reply is not None
    assert reply.resolution_kind == "case_number"
    assert "А19-23660/2017" in reply.content
    assert len(reply.citations) >= 1


def test_resolve_explicit_recap_latest(db_session, test_case):
    svc = ChatHistoryService(db_session)
    session_id = svc.get_or_create_session(test_case.id)

    evidence = build_evidence_bundle(citations=_court_practice_citations("А40-1/2020"))
    svc.save_user_message(case_id=test_case.id, content="вопрос", session_id=session_id)
    ph = svc.create_assistant_placeholder(case_id=test_case.id, session_id=session_id)
    svc.update_assistant_message(
        message_id=ph.id,
        content="Последний ответ с практикой",
        evidence=evidence,
    )

    reply = resolve_session_evidence_reply(
        db_session,
        scope="case",
        case_id=test_case.id,
        session_id=session_id,
        question="напомни что ты писал",
    )
    assert reply is not None
    assert reply.content == "Последний ответ с практикой"
