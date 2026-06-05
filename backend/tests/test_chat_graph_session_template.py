"""ChatGraphService: editor skips draft template."""
from unittest.mock import MagicMock, patch

from app.services.langchain_agents.chat_graph_service import ChatGraphService


def test_resolve_template_context_skips_for_case_chat():
    svc = ChatGraphService(db=MagicMock(), rag_service=MagicMock())
    with patch(
        "app.services.draft_template_context.resolve_draft_template_context"
    ) as mock_resolve:
        ctx, label, key = svc._resolve_template_context(
            question="какой инн у ооо нв-строй",
            draft_mode=False,
            document_context=None,
        )
    mock_resolve.assert_not_called()
    assert ctx == ""
    assert label is None
    assert key is None


def test_resolve_template_context_skips_for_editor():
    svc = ChatGraphService(db=MagicMock(), rag_service=MagicMock())
    with patch(
        "app.services.draft_template_context.resolve_draft_template_context"
    ) as mock_resolve:
        ctx, label, key = svc._resolve_template_context(
            question="ИНН?",
            draft_mode=False,
            document_context="документ в редакторе",
        )
    mock_resolve.assert_not_called()
    assert ctx == ""
    assert label is None
    assert key is None
