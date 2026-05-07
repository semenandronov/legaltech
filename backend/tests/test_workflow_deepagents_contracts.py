"""Contract tests for deepagents workflow integration."""
from datetime import datetime
import asyncio

from app.routes.workflow_agentic import event_to_dict
from app.services.workflows.execution_engine import ExecutionEvent
from app.services.workflows.deepagents_planning_service import DeepAgentsPlanningService
from app.services.workflows.deepagents_quality_gates_service import DeepAgentsQualityGatesService
from app.services.workflows.planning_agent import PlanStep
from app.services.workflows.tool_registry import ToolResult
from app.services.workflows.deepagents_runtime_contracts import evaluate_step_outcome


def test_event_to_dict_contains_progress_alias():
    event = ExecutionEvent(
        event_type="hitl_pause",
        execution_id="exec_1",
        step_id="step_1",
        data={"required_action": "clarify_task"},
        timestamp=datetime.utcnow(),
        progress_percent=42,
        message="pause",
    )
    payload = event_to_dict(event)
    assert payload["type"] == "hitl_pause"
    assert payload["event_type"] == "hitl_pause"
    assert payload["progress"] == 42
    assert payload["progress_percent"] == 42


def test_planning_service_requests_clarification_for_vague_task_without_docs():
    service = DeepAgentsPlanningService()
    decision = service._needs_clarification("сделай анализ")
    assert decision is True


def test_quality_gate_service_detects_missing_sources():
    service = DeepAgentsQualityGatesService()
    decision = asyncio.run(
        service.evaluate(
            user_task="Проверить договор",
            results={"steps": {"step_1": {"success": True, "data": {"summary": "ok"}}}},
            expected_schema=None,
        )
    )
    assert decision.passed is False
    assert any("источники" in msg.lower() for msg in decision.failed_checks)


def test_tool_reasoning_selects_allowed_tool():
    service = DeepAgentsPlanningService()
    step = PlanStep(
        id="s1",
        name="answer",
        description="answer question",
        step_type="tool_call",
        tool_name="rag",
        tool_params={"query": "что в документе"},
        depends_on=[],
    )
    decision = service.reason_next_tool(
        step=step,
        previous_results={},
        available_tools=["rag", "summarize"],
    )
    assert decision.selected_tool == "rag"
    assert decision.confidence > 0
    assert "Выбран инструмент" in decision.reason


def test_replan_builds_rerun_decision_for_insufficient_data():
    service = DeepAgentsPlanningService()
    step = PlanStep(
        id="s1",
        name="fetch",
        description="fetch details",
        step_type="tool_call",
        tool_name="rag",
        tool_params={"query": "пункт о штрафах", "top_k": 3},
        depends_on=[],
    )
    outcome = evaluate_step_outcome(
        step=step,
        result=ToolResult(success=True, data={"extraction_status": "in_progress"}),
    )
    replan = service.build_replan(
        step=step,
        outcome=outcome,
        available_tools=["rag", "summarize"],
    )
    assert replan.failed_step_id == "s1"
    assert replan.rerun_step_ids == ["s1"]
    assert replan.updated_step is not None
    assert replan.updated_step.tool_params["top_k"] >= 10


def test_event_to_dict_keeps_reasoning_payload():
    event = ExecutionEvent(
        event_type="tool_reasoned",
        execution_id="exec_2",
        step_id="step_2",
        data={
            "selected_tool": "rag",
            "decision_reason": "test reason",
            "required_inputs": ["step_1"],
            "confidence": 0.9,
        },
        timestamp=datetime.utcnow(),
        progress_percent=50,
        message="reasoned",
    )
    payload = event_to_dict(event)
    assert payload["type"] == "tool_reasoned"
    assert payload["data"]["selected_tool"] == "rag"
    assert payload["data"]["decision_reason"] == "test reason"


def test_terminal_event_payload_keeps_run_stats_contract():
    event = ExecutionEvent(
        event_type="completed",
        execution_id="exec_3",
        step_id=None,
        data={
            "summary": "ok",
            "artifacts": {"documents": [], "tables": [], "reports": [], "checks": []},
            "error": None,
            "run_stats": {
                "deepagents_steps": 2,
                "total_llm_calls": 4,
                "total_tokens_used": 1200,
                "forced_finalize": False,
            },
        },
        timestamp=datetime.utcnow(),
        progress_percent=100,
        message="done",
    )
    payload = event_to_dict(event)
    assert payload["type"] == "completed"
    assert payload["data"]["summary"] == "ok"
    assert "run_stats" in payload["data"]
    assert payload["data"]["run_stats"]["total_llm_calls"] == 4
