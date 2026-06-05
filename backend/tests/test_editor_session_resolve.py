"""Editor session id resolution and graph entry routing."""
from app.services.chat.editor_session import (
    editor_session_id,
    is_editor_session_id,
    new_editor_chat_session_id,
    resolve_editor_chat_session_id,
)
from app.services.langchain_agents.graphs.chat_graph import route_graph_entry


def test_is_editor_session_id():
    assert is_editor_session_id("editor:u1:c1:doc1")
    assert not is_editor_session_id("case-session-1")


def test_resolve_editor_default_session():
    sid = resolve_editor_chat_session_id(
        user_id="u1",
        case_id="c1",
        document_id="doc1",
        requested_session_id=None,
    )
    assert sid == "editor:u1:c1:doc1"


def test_resolve_editor_accepts_matching_session():
    custom = new_editor_chat_session_id(
        user_id="u1",
        case_id="c1",
        document_id="doc1",
    )
    resolved = resolve_editor_chat_session_id(
        user_id="u1",
        case_id="c1",
        document_id="doc1",
        requested_session_id=custom,
    )
    assert resolved == custom


def test_resolve_editor_rejects_foreign_session():
    foreign = "editor:other:c1:doc1"
    resolved = resolve_editor_chat_session_id(
        user_id="u1",
        case_id="c1",
        document_id="doc1",
        requested_session_id=foreign,
    )
    assert resolved == "editor:u1:c1:doc1"


def test_route_graph_entry_skips_manage_memory_for_editor():
    state = {
        "document_context": "doc text",
        "editor_mode": "ask",
        "messages": [{"role": "user", "content": "hi"}] * 5,
    }
    assert route_graph_entry(state) == "mode_router"


def test_route_graph_entry_uses_manage_memory_for_case_chat():
    state = {
        "document_context": None,
        "editor_mode": None,
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert route_graph_entry(state) == "manage_memory"
