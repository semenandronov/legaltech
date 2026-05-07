"""Runtime contracts for deepagents workflow execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.workflows.planning_agent import PlanStep
from app.services.workflows.tool_registry import ToolResult


@dataclass
class StepOutcome:
    """Structured evaluation of a step result."""
    status: str  # ok | failed | insufficient_data
    reason: str = ""
    missing_inputs: List[str] = field(default_factory=list)
    acceptance_criteria_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolReasoningDecision:
    """Decision payload for selecting/adjusting next tool."""
    selected_tool: str
    reason: str
    required_inputs: List[str] = field(default_factory=list)
    confidence: float = 0.0
    patched_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplanDecision:
    """Replan payload for dynamic graph updates."""
    reason: str
    failed_step_id: str
    updated_step: Optional[PlanStep] = None
    inserted_steps: List[PlanStep] = field(default_factory=list)
    rerun_step_ids: List[str] = field(default_factory=list)


@dataclass
class ReviewIterationResult:
    """Result of one quality review iteration."""
    iteration: int
    passed: bool
    failed_checks: List[str] = field(default_factory=list)
    rerun_steps: List[str] = field(default_factory=list)


def evaluate_step_outcome(
    *,
    step: PlanStep,
    result: ToolResult,
) -> StepOutcome:
    """Minimal deterministic step outcome contract."""
    if not result.success:
        return StepOutcome(
            status="failed",
            reason=result.error or f"step {step.id} failed",
            acceptance_criteria_result={"tool_success": False},
        )

    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("extraction_status") == "in_progress":
        return StepOutcome(
            status="insufficient_data",
            reason="tool returned in_progress state",
            missing_inputs=["finalized_extraction_results"],
            acceptance_criteria_result={"tool_success": True, "has_final_data": False},
        )

    return StepOutcome(
        status="ok",
        reason="step completed",
        acceptance_criteria_result={"tool_success": True},
    )
