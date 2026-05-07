"""Execution Engine - движок выполнения Workflow"""
from typing import List, Dict, Any, Optional, AsyncIterator
from sqlalchemy.orm import Session
from app.models.workflow import WorkflowExecution, WorkflowStep, WorkflowDefinition, WORKFLOW_TOOLS
from app.models.workflow import normalize_workflow_tool_name
from app.services.workflows.planning_agent import ExecutionPlan, PlanStep, PlanningAgent
from app.services.workflows.tool_registry import ToolRegistry, ToolResult
from app.services.workflows.events import ExecutionEvent
from app.services.workflows.deepagents_planning_service import DeepAgentsPlanningService
from app.services.workflows.deepagents_quality_gates_service import DeepAgentsQualityGatesService
from app.services.workflows.deepagents_runtime_contracts import ReviewIterationResult
from app.services.workflows.deepagents_harness import (
    WorkflowDeepAgentsContext,
    WorkflowDeepAgentsHarness,
)
from app.services.workflows.deepagents_stream_bridge import stream_parts_to_events
from app.services.llm_factory import create_llm
from app.services.observability.langfuse_service import (
    create_trace_context,
    end_trace,
    get_prompt_text,
    trace_event,
    set_active_trace_context,
    reset_active_trace_context,
)
from app.config import config
from datetime import datetime
import logging
import asyncio

import psycopg

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Движок выполнения Workflow.
    
    Выполняет план с использованием инструментов.
    Поддерживает:
    - Параллельное выполнение независимых шагов
    - Streaming событий для real-time прогресса
    - Обработку ошибок и retry
    - Валидацию результатов
    """
    
    def __init__(self, db: Session):
        """Initialize execution engine"""
        self.db = db
        self.tool_registry = ToolRegistry(db)
        self.planning_agent = PlanningAgent()
        self.deep_planning = DeepAgentsPlanningService()
        self.quality_gates = DeepAgentsQualityGatesService()

    def _build_document_requirements(
        self,
        definition: Optional[WorkflowDefinition],
        user_task: str
    ) -> Dict[str, Any]:
        """Build a compact guidance payload when document intake is missing."""
        workflow_name = (
            definition.display_name
            if definition and getattr(definition, "display_name", None)
            else "workflow"
        )
        return {
            "reason": "documents_required",
            "required_action": "upload_documents",
            "minimum_documents": 1,
            "workflow_name": workflow_name,
            "hint": (
                "Для продолжения загрузите хотя бы один документ и перезапустите workflow. "
                "Без исходных материалов правовые выводы будут ненадежны."
            ),
            "task_preview": (user_task or "")[:280],
        }

    def _get_runtime_state(self, execution: WorkflowExecution) -> Dict[str, Any]:
        cfg = execution.input_config or {}
        runtime = cfg.get("deepagents_runtime")
        if not isinstance(runtime, dict):
            runtime = {}
        return runtime

    def _set_runtime_state(self, execution: WorkflowExecution, runtime_state: Dict[str, Any]) -> None:
        cfg = dict(execution.input_config or {})
        cfg["deepagents_runtime"] = runtime_state
        execution.input_config = cfg

    def _pause_for_hitl(
        self,
        execution: WorkflowExecution,
        *,
        question: str,
        required_action: str,
        source: str,
        options: Optional[List[str]] = None,
        artifacts_to_review: Optional[List[str]] = None,
    ) -> ExecutionEvent:
        runtime = self._get_runtime_state(execution)
        runtime["hitl"] = {
            "paused": True,
            "question": question,
            "required_action": required_action,
            "source": source,
            "options": options or [],
            "artifacts_to_review": artifacts_to_review or [],
            "paused_at": datetime.utcnow().isoformat(),
        }
        self._set_runtime_state(execution, runtime)
        execution.status = "waiting_for_lawyer"
        execution.status_message = question
        self.db.commit()
        return ExecutionEvent(
            event_type="hitl_pause",
            execution_id=execution.id,
            data={
                "required_action": required_action,
                "question": question,
                "options": options or [],
                "artifacts_to_review": artifacts_to_review or [],
                "source": source,
            },
            message=question,
            progress_percent=execution.progress_percent or 0,
        )

    def _terminal_payload(
        self,
        *,
        summary: Optional[str],
        artifacts: Optional[Dict[str, Any]],
        error: Optional[str] = None,
        results: Optional[Dict[str, Any]] = None,
        run_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "summary": summary or "",
            "artifacts": artifacts or {},
            "error": error,
        }
        if results is not None:
            payload["results"] = results
        if run_stats is not None:
            payload["run_stats"] = run_stats
        return payload
    
    async def execute(
        self,
        execution: WorkflowExecution,
        plan: ExecutionPlan
    ) -> AsyncIterator[ExecutionEvent]:
        """
        Execute a workflow plan with streaming events
        
        Args:
            execution: WorkflowExecution record
            plan: ExecutionPlan to execute
            
        Yields:
            ExecutionEvents for each step
        """
        execution_id = execution.id
        trace_ctx = create_trace_context(
            name="workflow_execute",
            trace_id=f"wf-{execution_id}",
            user_id=str(execution.user_id),
            session_id=execution_id,
            metadata={
                "workflow_definition_id": execution.definition_id,
                "case_id": execution.case_id,
                "path": "classic",
                "steps_total": len(plan.steps),
            },
        )
        trace_token = set_active_trace_context(trace_ctx)
        
        try:
            # Update status to executing
            execution.status = "executing"
            execution.started_at = datetime.utcnow()
            execution.execution_plan = self.planning_agent.plan_to_dict(plan)
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="started",
                execution_id=execution_id,
                message=f"Начало выполнения workflow: {len(plan.steps)} шагов",
                progress_percent=0
            )
            
            # Create step records
            step_records = {}
            for i, step in enumerate(plan.steps):
                step_record = WorkflowStep(
                    execution_id=execution_id,
                    step_id=step.id,
                    sequence_number=i,
                    step_name=step.name,
                    step_type=step.step_type,
                    description=step.description,
                    tool_name=step.tool_name,
                    tool_params=step.tool_params,
                    depends_on=step.depends_on,
                    status="pending"
                )
                self.db.add(step_record)
                step_records[step.id] = step_record
            
            self.db.commit()
            
            # Execute steps
            completed_steps = set()
            step_results = {}
            total_steps = len(plan.steps)
            
            while len(completed_steps) < total_steps:
                # Find steps that can be executed (all dependencies satisfied)
                ready_steps = []
                for step in plan.steps:
                    if step.id in completed_steps:
                        continue
                    
                    if all(dep in completed_steps for dep in step.depends_on):
                        ready_steps.append(step)
                
                if not ready_steps:
                    # Deadlock - no steps can be executed
                    raise RuntimeError("Workflow deadlock: no steps can be executed")
                
                # Execute ready steps sequentially to enforce deterministic data flow.
                for step in ready_steps:
                    tool_decision = self.deep_planning.reason_next_tool(
                        step=step,
                        previous_results=step_results,
                        available_tools=execution.definition.available_tools if execution.definition else [],
                    )
                    if tool_decision.selected_tool:
                        step.tool_name = tool_decision.selected_tool
                    if tool_decision.patched_params:
                        step.tool_params = tool_decision.patched_params
                        step_records[step.id].tool_params = tool_decision.patched_params
                    self.db.commit()

                    yield ExecutionEvent(
                        event_type="tool_reasoned",
                        execution_id=execution_id,
                        step_id=step.id,
                        data={
                            "selected_tool": tool_decision.selected_tool,
                            "decision_reason": tool_decision.reason,
                            "required_inputs": tool_decision.required_inputs,
                            "confidence": tool_decision.confidence,
                        },
                        message=tool_decision.reason,
                        progress_percent=int((len(completed_steps) / total_steps) * 100)
                    )
                    trace_event(
                        name="workflow_step_started",
                        metadata={"execution_id": execution_id, "step_id": step.id, "tool": step.tool_name},
                    )

                    yield ExecutionEvent(
                        event_type="step_started",
                        execution_id=execution_id,
                        step_id=step.id,
                        message=f"Выполнение шага: {step.name}",
                        progress_percent=int((len(completed_steps) / total_steps) * 100)
                    )
                    
                    try:
                        result = await self._execute_step(
                            step=step,
                            step_record=step_records[step.id],
                            execution=execution,
                            previous_results=step_results
                        )
                        step_results[step.id] = result
                        outcome = self.deep_planning.evaluate_outcome(step=step, result=result)
                        if outcome.status in {"failed", "insufficient_data"}:
                            replan = self.deep_planning.build_replan(
                                step=step,
                                outcome=outcome,
                                available_tools=execution.definition.available_tools if execution.definition else [],
                            )
                            yield ExecutionEvent(
                                event_type="replan_started",
                                execution_id=execution_id,
                                step_id=step.id,
                                data={
                                    "reason": replan.reason,
                                    "missing_inputs": outcome.missing_inputs,
                                    "acceptance_criteria_result": outcome.acceptance_criteria_result,
                                },
                                message=f"Replanning после шага {step.name}",
                                progress_percent=int((len(completed_steps) / total_steps) * 100)
                            )
                            if replan.updated_step:
                                step.tool_name = replan.updated_step.tool_name
                                step.tool_params = replan.updated_step.tool_params
                                step_records[step.id].tool_name = replan.updated_step.tool_name
                                step_records[step.id].tool_params = replan.updated_step.tool_params
                            for inserted in replan.inserted_steps:
                                if inserted.id in step_records:
                                    continue
                                inserted_record = WorkflowStep(
                                    execution_id=execution_id,
                                    step_id=inserted.id,
                                    sequence_number=len(step_records),
                                    step_name=inserted.name,
                                    step_type=inserted.step_type,
                                    description=inserted.description,
                                    tool_name=inserted.tool_name,
                                    tool_params=inserted.tool_params,
                                    depends_on=inserted.depends_on,
                                    status="pending",
                                )
                                self.db.add(inserted_record)
                                step_records[inserted.id] = inserted_record
                                plan.steps.append(inserted)
                            self.db.commit()
                            total_steps = len(plan.steps)
                            yield ExecutionEvent(
                                event_type="replan_applied",
                                execution_id=execution_id,
                                step_id=step.id,
                                data={
                                    "rerun_step_ids": replan.rerun_step_ids,
                                    "inserted_steps": [s.id for s in replan.inserted_steps],
                                    "updated_step": replan.updated_step.id if replan.updated_step else None,
                                },
                                message="Replan применен, шаг будет выполнен повторно",
                                progress_percent=int((len(completed_steps) / total_steps) * 100)
                            )
                            continue

                        completed_steps.add(step.id)
                        execution.progress_percent = int((len(completed_steps) / total_steps) * 100)
                        execution.current_step_id = step.id
                        execution.total_steps_completed = len(completed_steps)
                        self.db.commit()

                        yield ExecutionEvent(
                            event_type="step_completed",
                            execution_id=execution_id,
                            step_id=step.id,
                            data={"success": result.success, "summary": result.output_summary},
                            message=f"Шаг завершён: {step.name}",
                            progress_percent=execution.progress_percent
                        )
                        trace_event(
                            name="workflow_step_completed",
                            metadata={
                                "execution_id": execution_id,
                                "step_id": step.id,
                                "success": bool(result.success),
                                "tool": step.tool_name,
                            },
                        )
                    except Exception as e:
                        logger.error(f"Step {step.id} failed: {e}")
                        yield ExecutionEvent(
                            event_type="step_failed",
                            execution_id=execution_id,
                            step_id=step.id,
                            data={"error": str(e)},
                            message=f"Ошибка в шаге: {step.name}",
                            progress_percent=execution.progress_percent or 0,
                        )
            
            # All steps completed - generate summary
            execution.status = "generating_report"
            self.db.commit()
            
            # Aggregate results
            aggregated_results = self._aggregate_results(step_results)
            execution.results = aggregated_results
            
            # Collect artifacts
            artifacts = self._collect_artifacts(step_results)
            execution.artifacts = artifacts

            # Mandatory quality gates before final completion with review loop.
            review_limit = 3
            iteration = 0
            quality_gates_unresolved = False
            while True:
                execution.status = "validating"
                self.db.commit()
                yield ExecutionEvent(
                    event_type="quality_gate_started",
                    execution_id=execution_id,
                    message="Запуск quality gates перед финализацией",
                    progress_percent=min(execution.progress_percent or 0, 95),
                )
                gate_decision = await self.quality_gates.evaluate(
                    user_task=execution.user_task,
                    results=aggregated_results,
                    expected_schema=execution.definition.output_schema if execution.definition else None,
                )
                review_result = ReviewIterationResult(
                    iteration=iteration,
                    passed=gate_decision.passed,
                    failed_checks=gate_decision.failed_checks,
                    rerun_steps=gate_decision.rerun_steps,
                )
                if review_result.passed:
                    yield ExecutionEvent(
                        event_type="review_iteration_passed",
                        execution_id=execution_id,
                        data={"review_iteration": iteration},
                        message="Quality review loop пройден",
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    break

                yield ExecutionEvent(
                    event_type="review_iteration_failed",
                    execution_id=execution_id,
                    data={
                        "review_iteration": iteration,
                        "failed_checks": review_result.failed_checks,
                        "rerun_steps": review_result.rerun_steps,
                    },
                    message=gate_decision.summary or "Quality gates не пройдены",
                    progress_percent=min(execution.progress_percent or 0, 95),
                )

                if iteration >= review_limit:
                    if config.WORKFLOW_DEEPAGENTS_HITL_ENABLED:
                        yield self._pause_for_hitl(
                            execution,
                            question=(
                                "Требуется проверка юриста: quality gates не пройдены после review loop. "
                                "Подтвердите продолжение или уточните корректировки."
                            ),
                            required_action="review_quality_gates",
                            source="quality_gates",
                            options=["Подтвердить и продолжить", "Запросить дополнительную переработку"],
                            artifacts_to_review=review_result.rerun_steps,
                        )
                        return
                    logger.warning(
                        "Quality gates not passed after review loop; completing with warnings (HITL disabled)."
                    )
                    yield ExecutionEvent(
                        event_type="status",
                        execution_id=execution_id,
                        message="Автопроверка quality gates не пройдена; финализируем с предупреждением (HITL отключён).",
                        data={
                            "failed_checks": review_result.failed_checks,
                            "quality_gates_unresolved": True,
                        },
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    quality_gates_unresolved = True
                    break

                if review_result.rerun_steps:
                    plan_by_id = {s.id: s for s in plan.steps}
                    yield ExecutionEvent(
                        event_type="review_iteration_started",
                        execution_id=execution_id,
                        data={
                            "review_iteration": iteration,
                            "rerun_steps": review_result.rerun_steps,
                        },
                        message=f"Запуск review loop итерации {iteration + 1}",
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    for step_id in review_result.rerun_steps:
                        step = plan_by_id.get(step_id)
                        step_record = step_records.get(step_id)
                        if not step or not step_record:
                            continue
                        try:
                            rerun_result = await self._execute_step(
                                step=step,
                                step_record=step_record,
                                execution=execution,
                                previous_results=step_results,
                            )
                            step_results[step_id] = rerun_result
                        except Exception:
                            pass
                    aggregated_results = self._aggregate_results(step_results)
                    execution.results = aggregated_results
                    artifacts = self._collect_artifacts(step_results)
                    execution.artifacts = artifacts
                    self.db.commit()
                iteration += 1
            
            # Generate summary
            summary = await self._generate_summary(step_results, plan)
            execution.summary = summary
            run_stats = {
                "total_steps": len(plan.steps),
                "completed_steps": len(completed_steps),
                "total_llm_calls": int(execution.total_llm_calls or 0),
                "total_tokens_used": int(execution.total_tokens_used or 0),
            }
            
            # Mark as completed (or completed_with_errors if quality gates did not pass and HITL is off)
            if quality_gates_unresolved:
                execution.status = "completed_with_errors"
                execution.error_message = (
                    "Quality gates не пройдены после review loop; требуется ручная проверка результата."
                )
            else:
                execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.progress_percent = 100
            self.db.commit()

            terminal_event = (
                "completed_with_errors"
                if quality_gates_unresolved
                else "completed"
            )
            terminal_message = (
                "Workflow завершён с предупреждением: quality gates не пройдены, проверьте результат."
                if quality_gates_unresolved
                else "Workflow успешно завершён"
            )
            yield ExecutionEvent(
                event_type=terminal_event,
                execution_id=execution_id,
                data=self._terminal_payload(
                    summary=summary,
                    artifacts=artifacts,
                    results=aggregated_results,
                    run_stats=run_stats,
                ),
                message=terminal_message,
                progress_percent=100,
            )
            end_trace(
                trace_ctx,
                status="success",
                output_payload={"summary": summary},
                metadata={"terminal_event": terminal_event},
            )
            
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            
            execution.status = "failed"
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="failed",
                execution_id=execution_id,
                data=self._terminal_payload(
                    summary=execution.summary,
                    artifacts=execution.artifacts,
                    error=str(e),
                    run_stats={
                        "total_llm_calls": int(execution.total_llm_calls or 0),
                        "total_tokens_used": int(execution.total_tokens_used or 0),
                    },
                ),
                message=f"Ошибка выполнения: {str(e)}",
                progress_percent=execution.progress_percent or 0,
            )
            end_trace(trace_ctx, status="error", error=str(e))
        finally:
            reset_active_trace_context(trace_token)
    
    async def _execute_step(
        self,
        step: PlanStep,
        step_record: WorkflowStep,
        execution: WorkflowExecution,
        previous_results: Dict[str, ToolResult]
    ) -> ToolResult:
        """Execute a single step"""
        step_record.status = "running"
        step_record.started_at = datetime.utcnow()
        self.db.commit()
        
        try:
            # Build context
            context = {
                "user_id": execution.user_id,
                "case_id": execution.case_id,
                "execution_id": execution.id,
                "step_id": step.id,
                "legal_research": bool((execution.input_config or {}).get("legal_research", False)),
                "previous_results": {
                    k: v.data for k, v in previous_results.items()
                }
            }
            
            # Execute tool
            if step.tool_name:
                canonical_tool_name = normalize_workflow_tool_name(step.tool_name)
                result = await self.tool_registry.execute_tool(
                    tool_name=canonical_tool_name,
                    params=step.tool_params,
                    context=context
                )
            else:
                # Non-tool step (analysis, validation)
                result = ToolResult(
                    success=True,
                    data={"message": "Step completed"},
                    output_summary="Non-tool step completed"
                )
            
            # Update step record
            step_record.status = "completed" if result.success else "failed"
            step_record.result = result.data
            step_record.output_summary = result.output_summary
            step_record.error = result.error
            step_record.completed_at = datetime.utcnow()
            step_record.duration_seconds = int((step_record.completed_at - step_record.started_at).total_seconds())
            step_record.llm_calls = result.llm_calls
            step_record.tokens_used = result.tokens_used
            
            # Update execution metrics
            execution.total_llm_calls = (execution.total_llm_calls or 0) + result.llm_calls
            execution.total_tokens_used = (execution.total_tokens_used or 0) + result.tokens_used
            
            self.db.commit()
            
            return result
            
        except Exception as e:
            step_record.status = "failed"
            step_record.error = str(e)
            step_record.completed_at = datetime.utcnow()
            self.db.commit()
            raise
    
    def _aggregate_results(self, step_results: Dict[str, ToolResult]) -> Dict[str, Any]:
        """Aggregate results from all steps"""
        aggregated = {
            "steps": {},
            "summary_data": {}
        }
        
        for step_id, result in step_results.items():
            aggregated["steps"][step_id] = {
                "success": result.success,
                "data": result.data,
                "summary": result.output_summary
            }
            
            # Extract key data for summary
            if result.data:
                if isinstance(result.data, dict):
                    for key in ["summary", "results", "entities", "by_type"]:
                        if key in result.data:
                            aggregated["summary_data"][f"{step_id}_{key}"] = result.data[key]
        
        return aggregated
    
    def _collect_artifacts(self, step_results: Dict[str, ToolResult]) -> Dict[str, List[Dict[str, Any]]]:
        """Collect artifacts from all steps"""
        artifacts = {
            "reports": [],
            "tables": [],
            "documents": [],
            "checks": []
        }
        
        for step_id, result in step_results.items():
            for artifact in result.artifacts:
                artifact_type = artifact.get("type", "other")
                
                if artifact_type == "tabular_review":
                    artifacts["tables"].append(artifact)
                elif artifact_type == "playbook_check":
                    artifacts["checks"].append(artifact)
                elif artifact_type in ["report", "document", "document_draft"]:
                    artifacts["documents"].append(artifact)
        
        return artifacts

    def _collect_artifacts_from_deepagents_results(
        self,
        step_results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Collect artifacts from DeepAgents runtime step payloads."""
        artifacts = {
            "reports": [],
            "tables": [],
            "documents": [],
            "checks": []
        }

        for _, step_payload in (step_results or {}).items():
            if not isinstance(step_payload, dict):
                continue
            result = step_payload.get("result")
            if not isinstance(result, dict):
                continue
            for artifact in result.get("artifacts", []) or []:
                if not isinstance(artifact, dict):
                    continue
                artifact_type = artifact.get("type", "other")
                if artifact_type == "tabular_review":
                    artifacts["tables"].append(artifact)
                elif artifact_type == "playbook_check":
                    artifacts["checks"].append(artifact)
                elif artifact_type in ["report", "document", "document_draft"]:
                    artifacts["documents"].append(artifact)

        return artifacts
    
    async def _generate_summary(
        self,
        step_results: Dict[str, ToolResult],
        plan: ExecutionPlan
    ) -> str:
        """Generate execution summary"""
        summary_parts = [
            f"Выполнено шагов: {len(step_results)}",
            f"Успешных: {sum(1 for r in step_results.values() if r.success)}",
            f"С ошибками: {sum(1 for r in step_results.values() if not r.success)}",
            "",
            "Результаты по шагам:"
        ]
        
        for step in plan.steps:
            if step.id in step_results:
                result = step_results[step.id]
                status = "✓" if result.success else "✗"
                summary_parts.append(f"  {status} {step.name}: {result.output_summary[:100]}")
        
        return "\n".join(summary_parts)
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancel a running execution
        
        Args:
            execution_id: Execution ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        execution = self.db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution_id
        ).first()
        
        if not execution:
            return False
        
        if execution.status not in ["pending", "planning", "executing"]:
            return False
        
        execution.status = "cancelled"
        execution.completed_at = datetime.utcnow()
        execution.error_message = "Cancelled by user"
        
        # Cancel pending steps
        for step in execution.steps:
            if step.status == "pending":
                step.status = "cancelled"
        
        self.db.commit()
        
        logger.info(f"Cancelled workflow execution: {execution_id}")
        return True

    async def resume_execution_with_human_input(
        self,
        execution: WorkflowExecution,
        *,
        answer: str,
        approved: Optional[bool] = None,
    ) -> ExecutionEvent:
        """Resume a HITL-paused execution with lawyer input."""
        runtime = self._get_runtime_state(execution)
        hitl_state = runtime.get("hitl", {})
        if not hitl_state.get("paused"):
            raise ValueError("Execution is not paused for HITL")

        hitl_state["paused"] = False
        hitl_state["answered_at"] = datetime.utcnow().isoformat()
        hitl_state["answer"] = answer
        if approved is not None:
            hitl_state["approved"] = approved
        runtime["hitl"] = hitl_state
        self._set_runtime_state(execution, runtime)

        execution.status = "planning" if hitl_state.get("source") == "planning" else "executing"
        execution.status_message = "Получен ответ юриста, выполнение возобновлено"
        self.db.commit()

        return ExecutionEvent(
            event_type="hitl_resume",
            execution_id=execution.id,
            data={
                "answer": answer,
                "approved": approved,
                "source": hitl_state.get("source"),
                "required_action": hitl_state.get("required_action"),
            },
            message="Workflow возобновлен после ответа юриста",
            progress_percent=execution.progress_percent or 0,
        )
    
    async def start_workflow(
        self,
        definition: WorkflowDefinition,
        user_task: str,
        user_id: str,
        case_id: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
        input_config: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecution:
        """
        Start a new workflow execution
        
        Args:
            definition: Workflow definition
            user_task: User's task in natural language
            user_id: User ID
            case_id: Optional case ID
            file_ids: Optional list of file IDs
            input_config: Optional additional configuration
            
        Returns:
            Created WorkflowExecution
        """
        # Create execution record
        execution = WorkflowExecution(
            definition_id=definition.id,
            case_id=case_id,
            user_id=user_id,
            user_task=user_task,
            input_config=input_config,
            selected_file_ids=file_ids,
            status="planning"
        )
        
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        
        logger.info(f"Created workflow execution: {execution.id}")
        
        return execution
    
    async def plan_and_execute(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        documents: List[Dict[str, Any]]
    ) -> AsyncIterator[ExecutionEvent]:
        """
        Plan and execute a workflow
        
        Args:
            execution: WorkflowExecution record
            definition: Workflow definition
            documents: Available documents
            
        Yields:
            ExecutionEvents
        """
        try:
            trace_ctx = create_trace_context(
                name="workflow_plan_and_execute",
                trace_id=f"wf-da-{execution.id}",
                user_id=str(execution.user_id),
                session_id=execution.id,
                metadata={
                    "workflow_definition_id": definition.id if definition else None,
                    "case_id": execution.case_id,
                    "path": "deepagents",
                    "documents_count": len(documents or []),
                },
            )
            trace_token = set_active_trace_context(trace_ctx)
            if not documents:
                execution.status = "waiting_for_lawyer"
                execution.status_message = (
                    "Ожидание документов: для запуска workflow требуется минимум один документ."
                )
                self.db.commit()
                yield ExecutionEvent(
                    event_type="waiting_for_lawyer",
                    execution_id=execution.id,
                    data=self._build_document_requirements(definition, execution.user_task),
                    message="Workflow приостановлен: добавьте документы для продолжения.",
                    progress_percent=0,
                )
                return

            # Mark execution as active before heavy DeepAgents initialization.
            execution.status = "executing"
            execution.started_at = execution.started_at or datetime.utcnow()
            execution.status_message = "Инициализация DeepAgents runtime..."
            execution.progress_percent = max(int(execution.progress_percent or 0), 1)
            self.db.commit()
            yield ExecutionEvent(
                event_type="started",
                execution_id=execution.id,
                message="Запуск DeepAgents workflow",
                progress_percent=execution.progress_percent,
            )
            yield ExecutionEvent(
                event_type="status",
                execution_id=execution.id,
                message=execution.status_message,
                progress_percent=execution.progress_percent,
            )

            # DeepAgents harness execution (streaming LangGraph graph)
            docs_hint = "\n".join(
                [f"- {d.get('filename', 'document')} (id={d.get('id')})" for d in documents[:20]]
            )
            configured_steps = None
            definition_config = getattr(definition, "config", None)
            if isinstance(definition_config, dict):
                configured_steps = definition_config.get("steps")
            if not configured_steps and isinstance(getattr(definition, "default_plan", None), dict):
                configured_steps = definition.default_plan.get("steps")
            if not configured_steps and isinstance(getattr(definition, "available_tools", None), list):
                configured_steps = [
                    {"tool": tool_name}
                    for tool_name in definition.available_tools
                    if tool_name
                ]
            ordered_tools_hint = ""
            if isinstance(configured_steps, list) and configured_steps:
                ordered_tool_names = [
                    str(step.get("tool")).strip()
                    for step in configured_steps
                    if isinstance(step, dict) and step.get("tool")
                ]
                if ordered_tool_names:
                    ordered_tools_hint = (
                        "\nСтрогий порядок инструментов для этого workflow (не пропускай и не меняй местами):\n- "
                        + "\n- ".join(ordered_tool_names)
                        + "\n"
                    )
            fallback_system_prompt = (
                "Ты — юридический workflow-агент. "
                "Тебе доступны ТОЛЬКО инструменты: rag, summarize, extract_entities, tabular_review, "
                "playbook_check, legal_db, document_draft. "
                "Никакие другие инструменты и действия запрещены.\n\n"
                f"Доступные документы (используй их id в параметрах file_ids/file_id):\n{docs_hint}\n\n"
                f"{ordered_tools_hint}"
                "Работай по шагам: сначала декомпозируй задачу, затем выполняй инструменты последовательно. "
                "Выполняй только один шаг за раз: не запускай следующий, пока текущий шаг не завершен успешно или явно не помечен как failed. "
                "После каждого шага используй результаты предыдущих шагов для следующего решения. "
                "Если задача состоит из нескольких независимых подзадач, разрешено выполнять их отдельными ветками, "
                "НО перед завершением обязательно сделай шаг синтеза: собери все результаты веток в единый вывод. "
                "Финал workflow должен содержать итоговый юридический документ (инструмент document_draft) на основе всех собранных данных. "
                "Если данных недостаточно или шаг не удался — перепланируйся и попробуй другой подход/параметры. "
                "Перед финалом сделай review результата на качество и источники; при провале — исправь и повтори.\n"
            )
            prompt_version = config.LANGFUSE_PROMPT_VERSION if config.LANGFUSE_PROMPT_VERSION > 0 else None
            system_prompt = get_prompt_text(
                prompt_name="workflow_deepagents_system_prompt",
                fallback=fallback_system_prompt,
                variables={
                    "docs_hint": docs_hint,
                    "ordered_tools_hint": ordered_tools_hint,
                },
                label=config.LANGFUSE_PROMPT_LABEL or None,
                version=prompt_version,
            )

            ctx = WorkflowDeepAgentsContext(
                user_id=execution.user_id,
                case_id=execution.case_id,
                execution_id=execution.id,
                previous_results={},
                legal_research=bool((execution.input_config or {}).get("legal_research", False)),
            )
            harness = WorkflowDeepAgentsHarness(self.tool_registry, ctx)
            deepagents_step_results: Dict[str, Any] = {}
            execution.status_message = "Подготовка LLM/агента для DeepAgents..."
            self.db.commit()
            yield ExecutionEvent(
                event_type="status",
                execution_id=execution.id,
                message=execution.status_message,
                progress_percent=max(int(execution.progress_percent or 1), 2),
            )
            deepagents_model = create_llm(temperature=0.2, use_rate_limiting=False)

            deepagents_checkpointer = None
            if config.WORKFLOW_DEEPAGENTS_CHECKPOINTER_ENABLED:
                execution.status_message = "Инициализация LangGraph checkpoint (PostgreSQL)..."
                self.db.commit()
                yield ExecutionEvent(
                    event_type="status",
                    execution_id=execution.id,
                    message=execution.status_message,
                    progress_percent=max(int(execution.progress_percent or 1), 2),
                )
                try:
                    from app.utils.checkpointer_setup import get_async_postgres_checkpointer

                    deepagents_checkpointer = await get_async_postgres_checkpointer()
                except Exception as exc:
                    logger.warning(
                        "DeepAgents: async Postgres checkpointer unavailable: %s",
                        exc,
                        exc_info=True,
                    )
                if deepagents_checkpointer is None:
                    from langgraph.checkpoint.memory import MemorySaver

                    deepagents_checkpointer = MemorySaver()
                    logger.warning(
                        "DeepAgents: using MemorySaver fallback (no AsyncPostgresSaver); "
                        "checkpoint state is process-local only."
                    )

            review_limit = 3
            failed_checks: List[str] = []
            forced_finalize = False
            deepagents_qg_unresolved = False
            for iteration in range(review_limit + 1):
                if iteration == 0:
                    execution.status_message = "DeepAgents начал выполнение шагов..."
                    self.db.commit()
                    yield ExecutionEvent(
                        event_type="status",
                        execution_id=execution.id,
                        message=execution.status_message,
                        progress_percent=max(int(execution.progress_percent or 1), 3),
                    )
                if iteration > 0:
                    yield ExecutionEvent(
                        event_type="review_iteration_started",
                        execution_id=execution.id,
                        data={"review_iteration": iteration, "failed_checks": failed_checks[:20]},
                        message=f"DeepAgents: переработка после quality gates (итерация {iteration})",
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )

                user_message = execution.user_task
                if failed_checks:
                    user_message = (
                        f"{execution.user_task}\n\n"
                        "Quality gates не пройдены. Исправь результат и при необходимости повторно вызови инструменты.\n"
                        f"Проваленные проверки:\n- " + "\n- ".join(failed_checks[:20])
                    )

                # Guardrails against endless internal tool loops in DeepAgents runtime.
                max_tool_steps_per_iteration = 24
                max_iteration_seconds = 240
                tool_steps_in_iteration = 0
                iteration_timeout_hit = False
                iteration_step_limit_hit = False

                for _checkpoint_stream_attempt in range(2):
                    agent = harness.create_agent(
                        system_prompt=system_prompt,
                        model=deepagents_model,
                        checkpointer=deepagents_checkpointer,
                    )

                    async def _parts() -> AsyncIterator[dict]:
                        async for part in agent.astream(
                            {"messages": [{"role": "user", "content": user_message}]},
                            stream_mode=["updates", "custom"],
                            config={
                                "configurable": {
                                    "thread_id": execution.id,
                                    "checkpoint_ns": "workflow_deepagents",
                                }
                            },
                            subgraphs=True,
                            version="v2",
                        ):
                            yield part
                            await asyncio.sleep(0)

                    try:
                        async with asyncio.timeout(max_iteration_seconds):
                            async for event in stream_parts_to_events(execution_id=execution.id, parts=_parts()):
                                if event.event_type in {"step_completed", "step_failed"} and isinstance(event.data, dict):
                                    tool_steps_in_iteration += 1
                                    tool_name = event.data.get("tool")
                                    tool_result = event.data.get("result")
                                    if tool_name and tool_result is not None and event.step_id:
                                        deepagents_step_results[event.step_id] = {
                                            "tool": tool_name,
                                            "result": tool_result,
                                        }
                                        # Make step outputs available to subsequent tool calls (e.g., document_draft).
                                        ctx.previous_results[event.step_id] = tool_result
                                        execution.results = {"steps": deepagents_step_results}
                                        self.db.commit()
                                    if tool_steps_in_iteration >= max_tool_steps_per_iteration:
                                        iteration_step_limit_hit = True
                                        yield ExecutionEvent(
                                            event_type="status",
                                            execution_id=execution.id,
                                            message=(
                                                "Достигнут лимит шагов DeepAgents в одной итерации. "
                                                "Останавливаю цикл и перехожу к финализации результата."
                                            ),
                                            data={
                                                "reason": "deepagents_step_limit",
                                                "tool_steps_in_iteration": tool_steps_in_iteration,
                                                "limit": max_tool_steps_per_iteration,
                                            },
                                            progress_percent=min(execution.progress_percent or 0, 95),
                                        )
                                        break
                                yield event
                        break
                    except TimeoutError:
                        iteration_timeout_hit = True
                        yield ExecutionEvent(
                            event_type="status",
                            execution_id=execution.id,
                            message=(
                                "DeepAgents превысил лимит времени итерации. "
                                "Останавливаю цикл и перехожу к финализации результата."
                            ),
                            data={
                                "reason": "deepagents_iteration_timeout",
                                "timeout_seconds": max_iteration_seconds,
                            },
                            progress_percent=min(execution.progress_percent or 0, 95),
                        )
                        break
                    except psycopg.OperationalError as pg_exc:
                        if (
                            _checkpoint_stream_attempt == 0
                            and config.WORKFLOW_DEEPAGENTS_CHECKPOINTER_ENABLED
                        ):
                            logger.warning(
                                "DeepAgents: checkpoint Postgres I/O failed (%s), resetting pool and retrying stream once",
                                pg_exc,
                            )
                            from app.utils.checkpointer_setup import (
                                get_async_postgres_checkpointer,
                                reset_async_postgres_checkpointer,
                            )

                            await reset_async_postgres_checkpointer()
                            deepagents_checkpointer = await get_async_postgres_checkpointer()
                            continue
                        raise

                # Hard guardrail: workflow must end with a synthesized draft.
                has_final_draft = any(
                    isinstance(v, dict) and v.get("tool") == "document_draft"
                    for v in deepagents_step_results.values()
                )
                if not has_final_draft:
                    draft_step_id = f"da_step_{len(deepagents_step_results) + 1}_final_draft"
                    yield ExecutionEvent(
                        event_type="step_started",
                        execution_id=execution.id,
                        step_id=draft_step_id,
                        data={"tool": "document_draft", "reason": "final_synthesis_guardrail"},
                        message="Запуск обязательного финального шага: сборка итогового документа",
                    )
                    draft_result = await self.tool_registry.execute_tool(
                        tool_name="document_draft",
                        params={
                            "document_type": "custom",
                            "title": f"Итоговый документ по workflow: {definition.display_name}",
                            "instructions": (
                                "Собери единый итоговый юридический документ на базе результатов всех предыдущих шагов. "
                                "Отрази выводы, риски, источники и рекомендуемые действия."
                            ),
                            "variables": {
                                "user_task": execution.user_task,
                                "workflow_definition": definition.display_name,
                                "step_results": deepagents_step_results,
                            },
                        },
                        context={
                            "user_id": execution.user_id,
                            "case_id": execution.case_id,
                            "execution_id": execution.id,
                            "previous_results": ctx.previous_results,
                        },
                    )
                    draft_payload = {
                        "success": bool(draft_result.success),
                        "data": draft_result.data,
                        "error": draft_result.error,
                        "output_summary": draft_result.output_summary,
                        "artifacts": draft_result.artifacts or [],
                        "llm_calls": int(draft_result.llm_calls or 0),
                        "tokens_used": int(draft_result.tokens_used or 0),
                    }
                    deepagents_step_results[draft_step_id] = {
                        "tool": "document_draft",
                        "result": draft_payload,
                    }
                    ctx.previous_results[draft_step_id] = draft_payload
                    execution.results = {"steps": deepagents_step_results}
                    self.db.commit()
                    if draft_result.success:
                        yield ExecutionEvent(
                            event_type="step_completed",
                            execution_id=execution.id,
                            step_id=draft_step_id,
                            data={
                                "success": True,
                                "summary": draft_result.output_summary,
                                "tool": "document_draft",
                                "result": draft_payload,
                            },
                            message="Финальный документ успешно собран",
                        )
                    else:
                        yield ExecutionEvent(
                            event_type="step_failed",
                            execution_id=execution.id,
                            step_id=draft_step_id,
                            data={
                                "error": draft_result.error or "document_draft_failed",
                                "tool": "document_draft",
                                "result": draft_payload,
                            },
                            message="Ошибка при обязательной финальной сборке документа",
                        )

                if iteration_step_limit_hit or iteration_timeout_hit:
                    forced_finalize = True
                    yield ExecutionEvent(
                        event_type="status",
                        execution_id=execution.id,
                        message="Принудительная финализация workflow после защитного остановa цикла DeepAgents.",
                        data={
                            "reason": "forced_finalize_after_deepagents_guardrail",
                            "iteration": iteration,
                            "step_limit_hit": iteration_step_limit_hit,
                            "timeout_hit": iteration_timeout_hit,
                        },
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    break

                execution.status = "validating"
                self.db.commit()
                yield ExecutionEvent(
                    event_type="quality_gate_started",
                    execution_id=execution.id,
                    message="Запуск quality gates (DeepAgents path)",
                    progress_percent=min(execution.progress_percent or 0, 95),
                )
                gate_decision = await self.quality_gates.evaluate(
                    user_task=execution.user_task,
                    results={"steps": deepagents_step_results},
                    expected_schema=definition.output_schema,
                )
                if gate_decision.passed:
                    yield ExecutionEvent(
                        event_type="review_iteration_passed",
                        execution_id=execution.id,
                        data={"review_iteration": iteration},
                        message="Quality review loop пройден (DeepAgents)",
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    break

                failed_checks = gate_decision.failed_checks or ["quality_gates_failed"]
                yield ExecutionEvent(
                    event_type="review_iteration_failed",
                    execution_id=execution.id,
                    data={"review_iteration": iteration, "failed_checks": failed_checks},
                    message=gate_decision.summary or "Quality gates не пройдены",
                    progress_percent=min(execution.progress_percent or 0, 95),
                )
                if iteration >= review_limit:
                    if config.WORKFLOW_DEEPAGENTS_HITL_ENABLED:
                        yield self._pause_for_hitl(
                            execution,
                            question=(
                                "Требуется проверка юриста: quality gates не пройдены после review loop (DeepAgents). "
                                "Подтвердите продолжение или уточните корректировки."
                            ),
                            required_action="review_quality_gates",
                            source="quality_gates",
                            options=["Подтвердить и продолжить", "Запросить дополнительную переработку"],
                            artifacts_to_review=[],
                        )
                        return
                    logger.warning(
                        "DeepAgents: quality gates not passed after review loop; completing with warnings (HITL disabled)."
                    )
                    yield ExecutionEvent(
                        event_type="status",
                        execution_id=execution.id,
                        message="Автопроверка quality gates не пройдена; финализируем с предупреждением (HITL отключён).",
                        data={
                            "failed_checks": failed_checks,
                            "quality_gates_unresolved": True,
                        },
                        progress_percent=min(execution.progress_percent or 0, 95),
                    )
                    deepagents_qg_unresolved = True
                    break

            # Mark execution completed
            execution.artifacts = self._collect_artifacts_from_deepagents_results(deepagents_step_results)
            if not execution.summary:
                doc_count = len((execution.artifacts or {}).get("documents", []))
                table_count = len((execution.artifacts or {}).get("tables", []))
                report_count = len((execution.artifacts or {}).get("reports", []))
                execution.summary = (
                    f"Workflow завершён. Документы: {doc_count}, "
                    f"таблицы: {table_count}, отчеты: {report_count}"
                )
            if deepagents_qg_unresolved:
                execution.status = "completed_with_errors"
                execution.error_message = (
                    "DeepAgents: quality gates не пройдены после review loop; требуется ручная проверка результата."
                )
            else:
                execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.progress_percent = 100
            self.db.commit()
            run_stats = {
                "deepagents_steps": len(deepagents_step_results),
                "forced_finalize": bool(forced_finalize),
                "quality_gates_unresolved": bool(deepagents_qg_unresolved),
                "total_llm_calls": int(execution.total_llm_calls or 0),
                "total_tokens_used": int(execution.total_tokens_used or 0),
            }
            deepagents_terminal = (
                "completed_with_errors"
                if deepagents_qg_unresolved
                else "completed"
            )
            deepagents_terminal_message = (
                "Workflow завершён с предупреждением (DeepAgents): quality gates не пройдены, проверьте результат."
                if deepagents_qg_unresolved
                else "Workflow успешно завершён (DeepAgents)"
            )
            yield ExecutionEvent(
                event_type=deepagents_terminal,
                execution_id=execution.id,
                data=self._terminal_payload(
                    summary=execution.summary,
                    artifacts=execution.artifacts,
                    results=execution.results or {},
                    run_stats=run_stats,
                ),
                message=deepagents_terminal_message,
                progress_percent=100,
            )
            end_trace(
                trace_ctx,
                status="success",
                output_payload={"summary": execution.summary or ""},
                metadata={"terminal_event": deepagents_terminal},
            )
                
        except Exception as e:
            logger.error(
                "DeepAgents plan_and_execute failed for execution %s: %s",
                execution.id,
                e,
                exc_info=True,
            )
            execution.status = "failed"
            execution.error_message = str(e)
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="failed",
                execution_id=execution.id,
                data=self._terminal_payload(
                    summary=execution.summary,
                    artifacts=execution.artifacts,
                    error=str(e),
                    results=execution.results or {},
                    run_stats={
                        "deepagents_steps": len(deepagents_step_results),
                        "total_llm_calls": int(execution.total_llm_calls or 0),
                        "total_tokens_used": int(execution.total_tokens_used or 0),
                    },
                ),
                message=f"Ошибка: {str(e)}",
                progress_percent=execution.progress_percent or 0,
            )
            end_trace(trace_ctx, status="error", error=str(e))
        finally:
            reset_active_trace_context(trace_token)
    
    async def execute_with_supervisor(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        documents: List[Dict[str, Any]]
    ) -> AsyncIterator[ExecutionEvent]:
        """
        Execute workflow using SupervisorAgent architecture.
        
        Использует паттерн "Субагенты" из LangChain:
        - Классификация намерения пользователя
        - Автоматический выбор агентов
        - Параллельное выполнение
        - Синтез результатов
        
        Args:
            execution: WorkflowExecution record
            definition: Workflow definition
            documents: Available documents
            
        Yields:
            ExecutionEvents
        """
        # Выбираем реализацию: LangGraph (предпочтительно) или базовый Supervisor
        use_langgraph = True  # Можно сделать настраиваемым
        
        if use_langgraph:
            async for event in self._execute_with_langgraph(execution, definition, documents):
                yield event
        else:
            async for event in self._execute_with_basic_supervisor(execution, definition, documents):
                yield event
    
    async def _execute_with_langgraph(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        documents: List[Dict[str, Any]]
    ) -> AsyncIterator[ExecutionEvent]:
        """
        Execute using LangGraph-based Supervisor.
        
        Преимущества:
        - Многоуровневая обработка ошибок
        - State-driven error management
        - Чекпоинты для персистентности
        - Bounded retries и graceful degradation
        """
        try:
            from app.services.workflows.langgraph_supervisor import LangGraphSupervisor, SupervisorConfig
            
            # Конфигурация
            config = SupervisorConfig(
                max_retries=3,
                max_steps=50,
                enable_checkpoints=True
            )
            
            supervisor = LangGraphSupervisor(self.db, config)
            
            # Extract file_ids
            file_ids = execution.selected_file_ids or []
            if not file_ids and documents:
                file_ids = [d.get("id") for d in documents if d.get("id")]
            
            # Update execution status
            execution.status = "executing"
            execution.started_at = datetime.utcnow()
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="started",
                execution_id=execution.id,
                message="Запуск LangGraph Supervisor..."
            )
            
            # Execute with LangGraph supervisor
            async for event in supervisor.execute(
                user_task=execution.user_task,
                file_ids=file_ids,
                documents=documents,
                execution_id=execution.id,
                thread_id=execution.id  # Используем execution_id как thread_id для чекпоинтов
            ):
                event_type = event.get("type", "status")
                
                if event_type == "node_completed":
                    node = event.get("node", "")
                    data = event.get("data", {})
                    
                    yield ExecutionEvent(
                        event_type="step_completed",
                        execution_id=execution.id,
                        step_id=node,
                        data=data,
                        message=f"Узел {node} завершён"
                    )
                    
                elif event_type == "completed":
                    result = event.get("result", {})
                    
                    execution.results = result
                    execution.status = "completed"
                    execution.completed_at = datetime.utcnow()
                    execution.progress_percent = 100
                    self.db.commit()
                    
                    yield ExecutionEvent(
                        event_type="completed",
                        execution_id=execution.id,
                        data=result,
                        message="Workflow успешно завершён",
                        progress_percent=100
                    )
                    
                elif event_type == "error":
                    execution.status = "failed"
                    execution.error_message = event.get("error")
                    self.db.commit()
                    
                    yield ExecutionEvent(
                        event_type="failed",
                        execution_id=execution.id,
                        data={"error": event.get("error")},
                        message=event.get("message", "")
                    )
                    
                else:
                    yield ExecutionEvent(
                        event_type=event_type,
                        execution_id=execution.id,
                        data=event,
                        message=event.get("message", "")
                    )
                    
        except Exception as e:
            logger.error(f"LangGraph execution failed: {e}", exc_info=True)
            
            execution.status = "failed"
            execution.error_message = str(e)
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="failed",
                execution_id=execution.id,
                data={"error": str(e)},
                message=f"Ошибка: {str(e)}"
            )
    
    async def _execute_with_basic_supervisor(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        documents: List[Dict[str, Any]]
    ) -> AsyncIterator[ExecutionEvent]:
        """
        Execute using basic SupervisorAgent (fallback).
        """
        try:
            from app.services.workflows.supervisor_agent import SupervisorAgent
            
            supervisor = SupervisorAgent(self.db)
            
            # Extract file_ids
            file_ids = execution.selected_file_ids or []
            if not file_ids and documents:
                file_ids = [d.get("id") for d in documents if d.get("id")]
            
            # Update execution status
            execution.status = "executing"
            execution.started_at = datetime.utcnow()
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="started",
                execution_id=execution.id,
                message="Запуск Supervisor Agent..."
            )
            
            # Execute with supervisor
            results = {}
            async for event in supervisor.execute(
                user_task=execution.user_task,
                documents=documents,
                file_ids=file_ids,
                workflow_definition=definition
            ):
                # Convert supervisor events to ExecutionEvents
                event_type = event.get("type", "status")
                
                if event_type == "intent_classified":
                    yield ExecutionEvent(
                        event_type="planning",
                        execution_id=execution.id,
                        data={"intent": event.get("intent")},
                        message=event.get("message", "")
                    )
                    
                elif event_type == "plan_created":
                    yield ExecutionEvent(
                        event_type="plan_created",
                        execution_id=execution.id,
                        data={"phases": event.get("phases")},
                        message=event.get("message", "")
                    )
                    
                elif event_type == "phase_started":
                    yield ExecutionEvent(
                        event_type="step_started",
                        execution_id=execution.id,
                        data={"agents": event.get("agents")},
                        message=event.get("message", ""),
                        progress_percent=int((event.get("phase", 1) - 1) * 25)
                    )
                    
                elif event_type == "agent_completed":
                    results[event.get("agent")] = event
                    yield ExecutionEvent(
                        event_type="step_completed",
                        execution_id=execution.id,
                        step_id=event.get("agent"),
                        data={
                            "success": event.get("success"),
                            "summary": event.get("summary")
                        },
                        message=f"Агент {event.get('agent')} завершён"
                    )
                    
                elif event_type == "completed":
                    # Store results
                    execution.results = event.get("result", {})
                    execution.status = "completed"
                    execution.completed_at = datetime.utcnow()
                    execution.progress_percent = 100
                    self.db.commit()
                    
                    yield ExecutionEvent(
                        event_type="completed",
                        execution_id=execution.id,
                        data=event.get("result", {}),
                        message="Workflow успешно завершён",
                        progress_percent=100
                    )
                    
                elif event_type == "error":
                    execution.status = "failed"
                    execution.error_message = event.get("error")
                    self.db.commit()
                    
                    yield ExecutionEvent(
                        event_type="failed",
                        execution_id=execution.id,
                        data={"error": event.get("error")},
                        message=event.get("message", "")
                    )
                    
                else:
                    # Pass through other events
                    yield ExecutionEvent(
                        event_type=event_type,
                        execution_id=execution.id,
                        data=event,
                        message=event.get("message", "")
                    )
                    
        except Exception as e:
            logger.error(f"Supervisor execution failed: {e}", exc_info=True)
            
            execution.status = "failed"
            execution.error_message = str(e)
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="failed",
                execution_id=execution.id,
                data={"error": str(e)},
                message=f"Ошибка: {str(e)}"
            )

