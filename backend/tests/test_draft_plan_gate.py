"""
Модульные проверки гейтов Draft: план обязателен, одобрение только через resume/state.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage


def _mock_db_with_case(db: MagicMock, *, case_id: str = "c1", user_id: str = "u1") -> None:
    case_row = MagicMock()
    case_row.id = case_id
    case_row.user_id = user_id
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = case_row
    db.query.return_value = q


def test_route_by_mode_draft_requires_explicit_draft_approved_for_execute():
    from app.services.langchain_agents.graphs.chat_graph import route_by_mode

    state = {
        "mode": "draft",
        "editor_mode": False,
        "document_context": None,
        "draft_plan": {"title": "X"},
        "draft_approved": False,
        "messages": [HumanMessage(content="одобряю")],
    }
    assert route_by_mode(state) == "draft"


def test_route_by_mode_draft_execute_when_plan_and_approved():
    from app.services.langchain_agents.graphs.chat_graph import route_by_mode

    state = {
        "mode": "draft",
        "editor_mode": False,
        "document_context": None,
        "draft_plan": {"title": "X"},
        "draft_approved": True,
        "messages": [HumanMessage(content="одобряю")],
    }
    assert route_by_mode(state) == "draft_execute"


def test_route_by_mode_draft_over_editor_when_document_context_set():
    from app.services.langchain_agents.graphs.chat_graph import route_by_mode

    state = {
        "mode": "draft",
        "editor_mode": True,
        "document_context": "some doc text",
        "draft_plan": {"title": "X"},
        "draft_approved": False,
        "messages": [],
    }
    assert route_by_mode(state) == "draft"


def test_resume_draft_rejects_without_plan_and_waiting():
    from app.services.langchain_agents.chat_graph_service import ChatGraphService
    from app.models.user import User

    db = MagicMock()
    _mock_db_with_case(db, case_id="c1", user_id="u1")
    svc = ChatGraphService(db=db, rag_service=MagicMock(), document_processor=MagicMock())

    graph = MagicMock()
    st = MagicMock()
    st.values = {"draft_plan": {"t": 1}, "waiting_for_approval": False}
    graph.aget_state = AsyncMock(return_value=st)
    graph.astream = AsyncMock()

    user = User(id="u1", email="a@b.c", password="x")

    async def _collect():
        out = []
        with patch.object(ChatGraphService, "_get_or_create_graph", return_value=graph):
            async for line in svc.resume_draft(
                case_id="c1",
                thread_id="t1",
                approved=True,
                user=user,
            ):
                out.append(line)
        return out

    out = asyncio.run(_collect())
    assert any("plan_not_ready" in x for x in out)
    graph.astream.assert_not_called()


def test_resume_draft_proceeds_when_plan_and_waiting():
    from app.services.langchain_agents.chat_graph_service import ChatGraphService
    from app.models.user import User

    db = MagicMock()
    _mock_db_with_case(db, case_id="c1", user_id="u1")
    svc = ChatGraphService(db=db, rag_service=MagicMock(), document_processor=MagicMock())

    graph = MagicMock()
    st = MagicMock()
    st.values = {"draft_plan": {"t": 1}, "waiting_for_approval": True}
    graph.aget_state = AsyncMock(return_value=st)

    async def _empty_astream(*args, **kwargs):
        if False:  # pragma: no cover
            yield {}

    graph.astream = AsyncMock(side_effect=_empty_astream)

    user = User(id="u1", email="a@b.c", password="x")

    async def _collect():
        lines = []
        with patch.object(ChatGraphService, "_get_or_create_graph", return_value=graph):
            with patch(
                "app.services.langchain_agents.utils.state_editing.update_state",
                new_callable=AsyncMock,
            ):
                async for line in svc.resume_draft(
                    case_id="c1",
                    thread_id="t1",
                    approved=True,
                    user=user,
                ):
                    lines.append(line)
        return lines

    lines = asyncio.run(_collect())
    graph.astream.assert_called_once()
    assert not any("plan_not_ready" in x for x in lines)
