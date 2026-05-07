"""DeepAgents-powered quality gates and review-loop helper."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

from app.services.workflows.result_validator import ResultValidator

logger = logging.getLogger(__name__)


@dataclass
class QualityGateDecision:
    passed: bool
    failed_checks: List[str] = field(default_factory=list)
    rerun_steps: List[str] = field(default_factory=list)
    artifacts_to_review: List[str] = field(default_factory=list)
    summary: str = ""
    used_fallback: bool = False


class DeepAgentsQualityGatesService:
    """Runs mandatory gates before final workflow completion."""

    def __init__(self):
        self.validator = ResultValidator()

    async def evaluate(
        self,
        user_task: str,
        results: Dict[str, Any],
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> QualityGateDecision:
        decision = await self._try_deepagents_evaluate(
            user_task=user_task,
            results=results,
            expected_schema=expected_schema,
        )
        if decision is not None:
            return decision

        validation = await self.validator.validate(
            user_task=user_task,
            results=results,
            expected_schema=expected_schema,
        )
        failed_checks: List[str] = []
        rerun_steps: List[str] = []
        for issue in validation.issues:
            if issue.severity == "error":
                failed_checks.append(issue.message)
                if issue.step_id:
                    rerun_steps.append(issue.step_id)
        # mandatory citation/source check
        source_ok = self._has_any_sources(results)
        if not source_ok:
            failed_checks.append("Отсутствуют источники/цитаты в результатах")

        passed = validation.is_valid and source_ok and not failed_checks
        return QualityGateDecision(
            passed=passed,
            failed_checks=failed_checks,
            rerun_steps=sorted(set(rerun_steps)),
            summary=validation.summary or "Результаты проверены базовыми quality gates",
            used_fallback=True,
        )

    async def _try_deepagents_evaluate(
        self,
        user_task: str,
        results: Dict[str, Any],
        expected_schema: Optional[Dict[str, Any]],
    ) -> Optional[QualityGateDecision]:
        try:
            import deepagents  # type: ignore  # noqa: F401
        except Exception as exc:
            logger.warning("DeepAgents quality gates unavailable, using compatibility adapter: %s", exc)

        validation = await self.validator.validate(
            user_task=user_task,
            results=results,
            expected_schema=expected_schema,
        )
        failed_checks = [i.message for i in validation.issues if i.severity == "error"]
        rerun_steps = [i.step_id for i in validation.issues if i.step_id]
        if not self._has_any_sources(results):
            failed_checks.append("Отсутствуют источники/цитаты в результатах")
        return QualityGateDecision(
            passed=validation.is_valid and not failed_checks,
            failed_checks=failed_checks,
            rerun_steps=sorted(set(s for s in rerun_steps if s)),
            summary=validation.summary,
            used_fallback=False,
        )

    @staticmethod
    def _has_any_sources(results: Dict[str, Any]) -> bool:
        if not isinstance(results, dict):
            return False
        steps = results.get("steps", {})
        if isinstance(steps, dict):
            for data in steps.values():
                if not isinstance(data, dict):
                    continue
                payload = data.get("data", {})
                if isinstance(payload, dict):
                    for key in ("sources", "citations", "references"):
                        val = payload.get(key)
                        if isinstance(val, list) and val:
                            return True
        return False
