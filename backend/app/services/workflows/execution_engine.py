"""Execution Engine - движок выполнения Workflow"""
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from app.models.workflow import WorkflowExecution, WorkflowStep, WorkflowDefinition
from app.services.workflows.planning_agent import ExecutionPlan, PlanStep, PlanningAgent
from app.services.workflows.tool_registry import ToolRegistry, ToolResult
from datetime import datetime
import logging
import asyncio
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ExecutionEvent:
    """Event emitted during workflow execution"""
    event_type: str  # started, step_started, step_completed, step_failed, completed, failed
    execution_id: str
    step_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    progress_percent: int = 0
    message: str = ""


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
                
                # Execute ready steps in parallel
                tasks = []
                for step in ready_steps:
                    task = self._execute_step(
                        step=step,
                        step_record=step_records[step.id],
                        execution=execution,
                        previous_results=step_results
                    )
                    tasks.append((step, task))
                
                # Wait for all parallel steps
                for step, task in tasks:
                    yield ExecutionEvent(
                        event_type="step_started",
                        execution_id=execution_id,
                        step_id=step.id,
                        message=f"Выполнение шага: {step.name}",
                        progress_percent=int((len(completed_steps) / total_steps) * 100)
                    )
                    
                    try:
                        result = await task
                        step_results[step.id] = result
                        completed_steps.add(step.id)
                        
                        # Update execution progress
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
                        
                    except Exception as e:
                        logger.error(f"Step {step.id} failed: {e}")
                        completed_steps.add(step.id)  # Mark as done (failed)
                        
                        execution.total_steps_failed = (execution.total_steps_failed or 0) + 1
                        self.db.commit()
                        
                        yield ExecutionEvent(
                            event_type="step_failed",
                            execution_id=execution_id,
                            step_id=step.id,
                            data={"error": str(e)},
                            message=f"Ошибка в шаге: {step.name}"
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
            
            # Generate summary
            summary = await self._generate_summary(step_results, plan)
            execution.summary = summary
            
            # Mark as completed
            execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.progress_percent = 100
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="completed",
                execution_id=execution_id,
                data={"results": aggregated_results, "artifacts": artifacts},
                message="Workflow успешно завершён",
                progress_percent=100
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
                data={"error": str(e)},
                message=f"Ошибка выполнения: {str(e)}"
            )
    
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
                "previous_results": {
                    k: v.data for k, v in previous_results.items()
                }
            }
            
            # Execute tool
            if step.tool_name:
                result = await self.tool_registry.execute_tool(
                    tool_name=step.tool_name,
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
                elif artifact_type in ["report", "document"]:
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
            # Planning phase
            yield ExecutionEvent(
                event_type="planning",
                execution_id=execution.id,
                message="Создание плана выполнения..."
            )
            
            plan = await self.planning_agent.create_plan(
                user_task=execution.user_task,
                available_documents=documents,
                available_tools=definition.available_tools or [],
                workflow_definition=definition
            )
            
            # Validate plan
            errors = self.planning_agent.validate_plan(plan)
            if errors:
                raise ValueError(f"Invalid plan: {'; '.join(errors)}")
            
            yield ExecutionEvent(
                event_type="plan_created",
                execution_id=execution.id,
                data={"plan": self.planning_agent.plan_to_dict(plan)},
                message=f"План создан: {len(plan.steps)} шагов"
            )
            
            # Execute plan
            async for event in self.execute(execution, plan):
                yield event
                
        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)
            self.db.commit()
            
            yield ExecutionEvent(
                event_type="failed",
                execution_id=execution.id,
                data={"error": str(e)},
                message=f"Ошибка: {str(e)}"
            )
    
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

