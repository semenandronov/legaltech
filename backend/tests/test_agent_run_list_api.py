"""List agent runs by case_id."""
from unittest.mock import MagicMock

import pytest

from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_runs.repository import AgentRunRepository


def test_list_for_case_orders_newest_first():
    db = MagicMock()
    repo = AgentRunRepository(db)

    case = MagicMock()
    case.id = "case-1"
    db.query.return_value.filter.return_value.first.return_value = case

    run_a = AgentRun(id="a", case_id="case-1", user_id="u1", thread_id="t1", user_task="task a", status=AgentRunStatus.COMPLETED)
    run_b = AgentRun(id="b", case_id="case-1", user_id="u1", thread_id="t2", user_task="task b", status=AgentRunStatus.RUNNING)
    db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        run_b,
        run_a,
    ]

    rows = repo.list_for_case("case-1", "u1", limit=10)
    assert len(rows) == 2
    assert rows[0].id == "b"
