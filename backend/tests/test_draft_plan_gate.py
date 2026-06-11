"""
Гейты Draft: direct document (default) vs legacy plan approval (DRAFT_PLAN_APPROVAL_ENABLED).
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


def test_route_by_mode_draft_direct_execute_by_default():
    from app.services.langchain_agents.graphs.chat_graph import route_by_mode

    state = {
        "mode": "draft",
        "editor_mode": False,
        "document_context": None,
        "draft_plan": None,
        "draft_approved": False,
        "messages": [HumanMessage(content="Напиши заявление")],
    }
    with patch(
        "app.services.langchain_agents.graphs.chat_graph._draft_plan_approval_enabled",
        return_value=False,
    ):
        assert route_by_mode(state) == "draft_execute"


def test_route_by_mode_draft_plan_path_when_approval_enabled_unapproved():
    from app.services.langchain_agents.graphs.chat_graph import route_by_mode

    state = {
        "mode": "draft",
        "editor_mode": False,
        "document_context": None,
        "draft_plan": {"title": "X"},
        "draft_approved": False,
        "messages": [HumanMessage(content="одобряю")],
    }
    with patch(
        "app.services.langchain_agents.graphs.chat_graph._draft_plan_approval_enabled",
        return_value=True,
    ):
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
    with patch(
        "app.services.langchain_agents.graphs.chat_graph._draft_plan_approval_enabled",
        return_value=True,
    ):
        assert route_by_mode(state) == "draft_execute"


def test_bootstrap_draft_plan_from_question():
    from app.services.langchain_agents.graphs.chat_graph import _bootstrap_draft_plan_from_state

    plan = _bootstrap_draft_plan_from_state(
        {
            "question": "Напиши заявление кредитора",
            "template_label": "заявление о банкротстве",
            "messages": [],
        }
    )
    assert plan["title"]
    assert plan["sections"]
    assert "заявление" in (plan.get("document_overview") or "").lower()


def test_create_initial_chat_state_draft_auto_approved():
    from app.services.langchain_agents.graphs.chat_graph import create_initial_chat_state

    with patch(
        "app.services.langchain_agents.graphs.chat_graph._draft_plan_approval_enabled",
        return_value=False,
    ):
        st = create_initial_chat_state(
            case_id="c1",
            user_id="u1",
            question="Напиши документ",
            mode="draft",
        )
    assert st["draft_approved"] is True
    assert st["waiting_for_approval"] is False


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
        with patch.object(ChatGraphService, "_get_or_create_graph", return_value=(graph, 0)):
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
        with patch.object(ChatGraphService, "_get_or_create_graph", return_value=(graph, 0)):
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
