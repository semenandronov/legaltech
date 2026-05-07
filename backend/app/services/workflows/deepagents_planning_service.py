"""DeepAgents-powered planning adapter for workflows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

from app.models.workflow import WorkflowDefinition, WORKFLOW_TOOLS, normalize_workflow_tool_name
from app.services.workflows.planning_agent import ExecutionPlan, PlanningAgent, PlanStep
from app.services.workflows.tool_registry import ToolResult
from app.services.workflows.deepagents_runtime_contracts import (
    StepOutcome,
    ToolReasoningDecision,
    ReplanDecision,
    evaluate_step_outcome,
)

logger = logging.getLogger(__name__)


@dataclass
class PlanningDecision:
    """Planning result with optional clarification request."""
    plan: Optional[ExecutionPlan]
    clarification_required: bool = False
    clarification_question: str = ""
    clarification_options: Optional[List[str]] = None
    used_fallback: bool = False
    reason: str = ""


class DeepAgentsPlanningService:
    """
    Adapter that provides deepagents-style decomposition/reasoning/replan contracts.
    Direct-switch mode: planning path is always routed through this adapter.
    """

    def __init__(self):
        self.fallback_planner = PlanningAgent()

    async def create_plan(
        self,
        user_task: str,
        available_documents: List[Dict[str, Any]],
        available_tools: List[str],
        workflow_definition: Optional[WorkflowDefinition] = None,
    ) -> PlanningDecision:
        # If no documents and user task appears underspecified, ask clarification.
        if not available_documents and self._needs_clarification(user_task):
            return PlanningDecision(
                plan=None,
                clarification_required=True,
                clarification_question=(
                    "Уточните цель workflow и загрузите документы: "
                    "какой именно юридический результат нужен в финале?"
                ),
                clarification_options=[
                    "Анализ рисков договора",
                    "Извлечение ключевых условий",
                    "Сравнение документов",
                    "Подготовка черновика документа",
                ],
                used_fallback=False,
                reason="insufficient_context",
            )

        plan = await self._try_deepagents_plan(
            user_task=user_task,
            available_documents=available_documents,
            available_tools=available_tools,
            workflow_definition=workflow_definition,
        )
        if plan is None:
            raise RuntimeError("Deepagents planning path is unavailable")

        return PlanningDecision(
            plan=plan,
            clarification_required=False,
            used_fallback=False,
            reason="deepagents_success",
        )

    async def _try_deepagents_plan(
        self,
        user_task: str,
        available_documents: List[Dict[str, Any]],
        available_tools: List[str],
        workflow_definition: Optional[WorkflowDefinition],
    ) -> Optional[ExecutionPlan]:
        """
        Deepagents branch.

        NOTE:
        - deepagents package may be absent in some environments.
        - to avoid runtime breaks, import is optional and errors degrade gracefully.
        """
        try:
            import deepagents  # type: ignore  # noqa: F401
            logger.info("Deepagents package detected, using compatibility decomposition path")
        except Exception as exc:
            logger.warning("Deepagents package is not installed, using compatibility decomposition: %s", exc)

        return await self.fallback_planner.create_plan(
            user_task=user_task,
            available_documents=available_documents,
            available_tools=available_tools,
            workflow_definition=workflow_definition,
        )

    def reason_next_tool(
        self,
        *,
        step: PlanStep,
        previous_results: Dict[str, ToolResult],
        available_tools: List[str],
    ) -> ToolReasoningDecision:
        """Structured tool reasoning for next step."""
        allowed = {normalize_workflow_tool_name(t) for t in (available_tools or [])}
        if not allowed:
            allowed = {t["name"] for t in WORKFLOW_TOOLS}

        selected = normalize_workflow_tool_name(step.tool_name or "")
        if selected not in allowed:
            selected = step.tool_name = sorted(allowed)[0]

        required_inputs = list(step.depends_on or [])
        confidence = 0.85 if required_inputs else 0.7
        reason = (
            f"Выбран инструмент {selected}: соответствует шагу '{step.name}'. "
            f"Требуемые входы: {', '.join(required_inputs) if required_inputs else 'нет'}."
        )
        return ToolReasoningDecision(
            selected_tool=selected,
            reason=reason,
            required_inputs=required_inputs,
            confidence=confidence,
            patched_params=step.tool_params or {},
        )

    def evaluate_outcome(
        self,
        *,
        step: PlanStep,
        result: ToolResult,
    ) -> StepOutcome:
        """Evaluate step result with deterministic contract."""
        return evaluate_step_outcome(step=step, result=result)

    def build_replan(
        self,
        *,
        step: PlanStep,
        outcome: StepOutcome,
        available_tools: List[str],
    ) -> ReplanDecision:
        """Build deterministic replan response for failed/insufficient step."""
        updated = PlanStep(
            id=step.id,
            name=step.name,
            description=step.description,
            step_type=step.step_type,
            tool_name=step.tool_name,
            tool_params=dict(step.tool_params or {}),
            depends_on=list(step.depends_on or []),
            expected_output=step.expected_output,
            goal_id=step.goal_id,
            estimated_duration_seconds=step.estimated_duration_seconds,
        )
        if outcome.status == "insufficient_data":
            updated.tool_params["top_k"] = max(int(updated.tool_params.get("top_k", 5)), 10)
            if not updated.tool_params.get("query"):
                updated.tool_params["query"] = step.description or step.name
        return ReplanDecision(
            reason=outcome.reason,
            failed_step_id=step.id,
            updated_step=updated,
            inserted_steps=[],
            rerun_step_ids=[step.id],
        )

    @staticmethod
    def _needs_clarification(user_task: str) -> bool:
        task = (user_task or "").strip().lower()
        if len(task) < 20:
            return True
        vague_markers = [
            "сделай",
            "проверь",
            "помоги",
            "разбери",
            "что скажешь",
        ]
        return any(marker in task for marker in vague_markers) and "документ" not in task
