from __future__ import annotations

from app.services.chat.history_service import ChatHistoryService
from app.models.case import ChatMessage


def test_history_service_updates_evidence(db_session, test_case):
    svc = ChatHistoryService(db_session)
    session_id = svc.get_or_create_session(test_case.id)
    placeholder = svc.create_assistant_placeholder(case_id=test_case.id, session_id=session_id)

    evidence = {"citations": [{"source_type": "court_practice", "quote_anchor": "А40-1/2020"}]}
    ok = svc.update_assistant_message(
        message_id=placeholder.id,
        content="Ответ с источниками",
        source_references=[{"legacy": True}],
        evidence=evidence,
    )
    assert ok is True

    row = db_session.query(ChatMessage).filter(ChatMessage.id == placeholder.id).first()
    assert row is not None
    assert row.content == "Ответ с источниками"
    assert row.evidence == evidence

