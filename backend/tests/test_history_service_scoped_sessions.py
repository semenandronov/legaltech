"""Sessions list must exclude scoped chat namespaces (editor/tabular/operations)."""

from unittest.mock import MagicMock, patch

from app.services.chat.history_service import (
    _NON_CASE_ASSISTANT_SESSION_PREFIXES,
    _exclude_scoped_chat_sessions,
)


def test_non_case_assistant_prefixes_include_operations():
    assert "operations:%" in _NON_CASE_ASSISTANT_SESSION_PREFIXES
    assert "editor:%" in _NON_CASE_ASSISTANT_SESSION_PREFIXES
    assert "tabular:%" in _NON_CASE_ASSISTANT_SESSION_PREFIXES


def test_exclude_scoped_chat_sessions_applies_all_prefixes():
    query = MagicMock()
    chain = query
    chain.filter = MagicMock(return_value=chain)

    result = _exclude_scoped_chat_sessions(query)

    assert result is chain
    assert chain.filter.call_count == len(_NON_CASE_ASSISTANT_SESSION_PREFIXES)
