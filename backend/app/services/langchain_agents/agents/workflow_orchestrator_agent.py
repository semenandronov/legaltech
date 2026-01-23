"""
WorkflowOrchestratorAgent - агент для оркестрации сложных workflows.

Это агент (не узел), потому что:
1. Планирует шаги выполнения
2. Принимает решения о параллельном vs последовательном выполнении
3. Поддерживает HITL для одобрения плана
4. Может адаптировать план на основе результатов

Паттерн:
1. Анализ задачи
2. Генерация плана шагов
3. HITL для одобрения плана
4. Выполнение шагов (параллельно где возможно)
5. Мониторинг и адаптация
6. Синтез результатов
"""
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage, AIMessage
from app.services.llm_factory import create_llm, create_legal_llm
from app.services.rag_service import RAGService
from sqlalchemy.orm import Session
import logging
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """Шаг workflow."""
    id: str
    name: str
    description: str
    step_type: Literal["analysis", "extraction", "generation", "review", "custom"]
    dependencies: List[str] = field(default_factory=list)  # ID шагов, от которых зависит
    config: Dict[str, Any] = field(default_factory=dict)
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class WorkflowPlan:
    """План выполнения workflow."""
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    estimated_time_minutes: int = 0
    requires_approval: bool = True


@dataclass
class WorkflowOrchestratorConfig:
    """Конфигурация оркестратора."""
    workflow_id: str
    case_id: str
    user_id: str
    workflow_definition: Dict[str, Any]  # Определение workflow из БД
    max_parallel_steps: int = 3
    require_plan_approval: bool = True
    auto_adapt: bool = True  # Автоматическая адаптация при ошибках


class WorkflowOrchestratorAgent:
    """
    Агент-оркестратор для сложных workflows.
    
    Управляет:
    - Планированием шагов
    - Параллельным выполнением независимых шагов
    - Адаптацией при ошибках
    - HITL для одобрения плана
    """
    
    def __init__(
        self,
        config: WorkflowOrchestratorConfig,
        db: Session,
        rag_service: RAGService = None
    ):
        """
        Инициализация оркестратора.
        
        Args:
            config: Конфигурация
            db: Database session
            rag_service: RAG service
        """
        self.config = config
        self.db = db
        self.rag_service = rag_service
        self.llm = create_legal_llm(use_rate_limiting=False)
        
        # План и состояние
        self.plan: Optional[WorkflowPlan] = None
        self.results: Dict[str, Any] = {}
        self.is_approved: bool = False
        
        logger.info(f"[WorkflowOrchestrator] Initialized for workflow {config.workflow_id}")
    
    def _analyze_workflow_definition(self) -> Dict[str, Any]:
        """
        Анализ определения workflow.
        
        Returns:
            Структурированный анализ workflow
        """
        definition = self.config.workflow_definition
        
        return {
            "name": definition.get("name", "Unnamed Workflow"),
            "description": definition.get("description", ""),
            "steps_count": len(definition.get("steps", [])),
            "has_parallel_steps": self._detect_parallel_opportunities(definition),
            "estimated_complexity": self._estimate_complexity(definition)
        }
    
    def _detect_parallel_opportunities(self, definition: Dict[str, Any]) -> bool:
        """Определить, есть ли возможности для параллельного выполнения."""
        steps = definition.get("steps", [])
        if len(steps) < 2:
            return False
        
        # Проверяем, есть ли шаги без зависимостей друг от друга
        for i, step in enumerate(steps):
            deps = step.get("dependencies", [])
            if not deps or not any(d in [s.get("id") for s in steps[:i]] for d in deps):
                # Этот шаг может выполняться параллельно с предыдущими
                return True
        
        return False
    
    def _estimate_complexity(self, definition: Dict[str, Any]) -> Literal["low", "medium", "high"]:
        """Оценить сложность workflow."""
        steps = definition.get("steps", [])
        
        if len(steps) <= 2:
            return "low"
        elif len(steps) <= 5:
            return "medium"
        else:
            return "high"
    
    async def generate_plan(self) -> WorkflowPlan:
        """
        Сгенерировать план выполнения workflow.
        
        Returns:
            План выполнения
        """
        logger.info(f"[WorkflowOrchestrator] Generating plan for workflow {self.config.workflow_id}")
        
        definition = self.config.workflow_definition
        analysis = self._analyze_workflow_definition()
        
        # Преобразуем шаги из определения в WorkflowStep
        steps = []
        for step_def in definition.get("steps", []):
            step = WorkflowStep(
                id=step_def.get("id", f"step_{len(steps)}"),
                name=step_def.get("name", "Unnamed Step"),
                description=step_def.get("description", ""),
                step_type=step_def.get("type", "custom"),
                dependencies=step_def.get("dependencies", []),
                config=step_def.get("config", {})
            )
            steps.append(step)
        
        # Оптимизируем порядок для параллельного выполнения
        optimized_steps = self._optimize_step_order(steps)
        
        # Оцениваем время
        estimated_time = self._estimate_execution_time(optimized_steps)
        
        self.plan = WorkflowPlan(
            workflow_id=self.config.workflow_id,
            name=analysis["name"],
            description=analysis["description"],
            steps=optimized_steps,
            estimated_time_minutes=estimated_time,
            requires_approval=self.config.require_plan_approval
        )
        
        logger.info(f"[WorkflowOrchestrator] Plan generated: {len(optimized_steps)} steps, ~{estimated_time} min")
        return self.plan
    
    def _optimize_step_order(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """
        Оптимизировать порядок шагов для параллельного выполнения.
        
        Использует топологическую сортировку с учётом зависимостей.
        """
        # Простая реализация: сохраняем порядок, но группируем независимые шаги
        step_ids = {s.id for s in steps}
        
        # Проверяем корректность зависимостей
        for step in steps:
            invalid_deps = [d for d in step.dependencies if d not in step_ids]
            if invalid_deps:
                logger.warning(f"[WorkflowOrchestrator] Step {step.id} has invalid dependencies: {invalid_deps}")
                step.dependencies = [d for d in step.dependencies if d in step_ids]
        
        return steps
    
    def _estimate_execution_time(self, steps: List[WorkflowStep]) -> int:
        """Оценить время выполнения в минутах."""
        # Базовые оценки по типу шага
        time_estimates = {
            "analysis": 3,
            "extraction": 5,
            "generation": 4,
            "review": 2,
            "custom": 3
        }
        
        total_time = 0
        for step in steps:
            total_time += time_estimates.get(step.step_type, 3)
        
        # Учитываем параллельное выполнение (грубая оценка)
        if len(steps) > 2:
            total_time = int(total_time * 0.7)  # ~30% экономия на параллельности
        
        return max(1, total_time)
    
    def get_plan_for_approval(self) -> Dict[str, Any]:
        """
        Получить план для одобрения пользователем.
        
        Returns:
            Словарь с информацией о плане для UI
        """
        if not self.plan:
            return {"error": "План не сгенерирован"}
        
        return {
            "workflow_id": self.plan.workflow_id,
            "name": self.plan.name,
            "description": self.plan.description,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "type": s.step_type,
                    "dependencies": s.dependencies
                }
                for s in self.plan.steps
            ],
            "estimated_time_minutes": self.plan.estimated_time_minutes,
            "requires_approval": self.plan.requires_approval
        }
    
    def approve_plan(self, approved: bool = True, modifications: Dict[str, Any] = None):
        """
        Одобрить или отклонить план.
        
        Args:
            approved: Одобрен ли план
            modifications: Модификации к плану (опционально)
        """
        if not self.plan:
            raise ValueError("План не сгенерирован")
        
        if modifications:
            # Применяем модификации
            for step_id, mods in modifications.items():
                for step in self.plan.steps:
                    if step.id == step_id:
                        if "skip" in mods and mods["skip"]:
                            step.status = "skipped"
                        if "config" in mods:
                            step.config.update(mods["config"])
        
        self.is_approved = approved
        logger.info(f"[WorkflowOrchestrator] Plan {'approved' if approved else 'rejected'}")
    
    async def execute_step(self, step: WorkflowStep) -> Dict[str, Any]:
        """
        Выполнить один шаг workflow.
        
        Args:
            step: Шаг для выполнения
        
        Returns:
            Результат выполнения
        """
        logger.info(f"[WorkflowOrchestrator] Executing step: {step.name}")
        
        step.status = "running"
        
        try:
            # Получаем результаты зависимых шагов
            dependency_results = {
                dep_id: self.results.get(dep_id, {})
                for dep_id in step.dependencies
            }
            
            # Выполняем шаг в зависимости от типа
            if step.step_type == "analysis":
                result = await self._execute_analysis_step(step, dependency_results)
            elif step.step_type == "extraction":
                result = await self._execute_extraction_step(step, dependency_results)
            elif step.step_type == "generation":
                result = await self._execute_generation_step(step, dependency_results)
            elif step.step_type == "review":
                result = await self._execute_review_step(step, dependency_results)
            else:
                result = await self._execute_custom_step(step, dependency_results)
            
            step.status = "completed"
            step.result = result
            self.results[step.id] = result
            
            logger.info(f"[WorkflowOrchestrator] Step {step.name} completed")
            return result
            
        except Exception as e:
            logger.error(f"[WorkflowOrchestrator] Step {step.name} failed: {e}", exc_info=True)
            step.status = "failed"
            step.error = str(e)
            
            if self.config.auto_adapt:
                # Пытаемся адаптироваться к ошибке
                return await self._handle_step_failure(step, e)
            else:
                raise
    
    async def _execute_analysis_step(
        self,
        step: WorkflowStep,
        dependency_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выполнить шаг анализа."""
        analysis_type = step.config.get("analysis_type", "general")
        
        # Получаем контекст из RAG
        context = ""
        if self.rag_service:
            docs = self.rag_service.retrieve_context(
                case_id=self.config.case_id,
                query=step.description,
                k=10,
                db=self.db
            )
            if docs:
                context = self.rag_service.format_sources_for_prompt(docs, max_context_chars=6000)
        
        # Формируем промпт
        prompt = f"""Проведи анализ для шага: {step.name}

ОПИСАНИЕ ЗАДАЧИ:
{step.description}

КОНТЕКСТ ИЗ ДОКУМЕНТОВ:
{context}

РЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ ШАГОВ:
{json.dumps(dependency_results, ensure_ascii=False, indent=2)}

Дай структурированный анализ в формате JSON:
{{
    "findings": ["находка 1", "находка 2"],
    "summary": "краткое резюме",
    "recommendations": ["рекомендация 1"]
}}
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        from app.services.langchain_agents.utils import extract_json_from_response
        result = extract_json_from_response(response_text)
        
        return result or {"raw_response": response_text}
    
    async def _execute_extraction_step(
        self,
        step: WorkflowStep,
        dependency_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выполнить шаг извлечения данных."""
        # Используем TabularExtractionAgent если нужно извлечение в таблицу
        extraction_type = step.config.get("extraction_type", "general")
        
        if extraction_type == "tabular":
            from app.services.langchain_agents.agents.tabular_extraction_agent import (
                TabularExtractionAgent,
                TabularExtractionConfig,
                ExtractionColumn
            )
            
            columns = [
                ExtractionColumn(
                    id=col["id"],
                    label=col.get("label", col["id"]),
                    column_type=col.get("type", "text"),
                    prompt=col.get("prompt", "")
                )
                for col in step.config.get("columns", [])
            ]
            
            config = TabularExtractionConfig(
                review_id=step.config.get("review_id", step.id),
                case_id=self.config.case_id,
                user_id=self.config.user_id,
                columns=columns,
                file_ids=step.config.get("file_ids", []),
                enable_hitl=False  # В workflow не используем HITL на уровне шага
            )
            
            agent = TabularExtractionAgent(config, self.db, self.rag_service)
            result = await agent.extract_all()
            return result
        else:
            # Общее извлечение
            prompt = f"""Извлеки информацию для шага: {step.name}

ОПИСАНИЕ:
{step.description}

РЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ ШАГОВ:
{json.dumps(dependency_results, ensure_ascii=False, indent=2)}

Верни извлечённые данные в формате JSON.
"""
            
            response = self.llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            from app.services.langchain_agents.utils import extract_json_from_response
            result = extract_json_from_response(response_text)
            
            return result or {"raw_response": response_text}
    
    async def _execute_generation_step(
        self,
        step: WorkflowStep,
        dependency_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выполнить шаг генерации документа."""
        template_id = step.config.get("template_id")
        
        prompt = f"""Сгенерируй документ для шага: {step.name}

ОПИСАНИЕ:
{step.description}

ДАННЫЕ ИЗ ПРЕДЫДУЩИХ ШАГОВ:
{json.dumps(dependency_results, ensure_ascii=False, indent=2)}

Сгенерируй содержимое документа.
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Сохраняем документ если указано
        if step.config.get("save_document", False):
            from app.services.document_editor_service import DocumentEditorService
            
            doc_service = DocumentEditorService(self.db)
            document = doc_service.create_document(
                case_id=self.config.case_id,
                user_id=self.config.user_id,
                title=step.config.get("document_title", step.name),
                content=content
            )
            
            return {
                "document_id": str(document.id),
                "title": document.title,
                "content_preview": content[:500]
            }
        
        return {"content": content}
    
    async def _execute_review_step(
        self,
        step: WorkflowStep,
        dependency_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выполнить шаг ревью."""
        prompt = f"""Проведи ревью для шага: {step.name}

ОПИСАНИЕ:
{step.description}

ДАННЫЕ ДЛЯ РЕВЬЮ:
{json.dumps(dependency_results, ensure_ascii=False, indent=2)}

Оцени качество и дай рекомендации в формате JSON:
{{
    "quality_score": 0-100,
    "issues": ["проблема 1"],
    "recommendations": ["рекомендация 1"],
    "approved": true/false
}}
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        from app.services.langchain_agents.utils import extract_json_from_response
        result = extract_json_from_response(response_text)
        
        return result or {"raw_response": response_text}
    
    async def _execute_custom_step(
        self,
        step: WorkflowStep,
        dependency_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выполнить кастомный шаг."""
        # Проверяем, есть ли handler в конфиге
        handler_name = step.config.get("handler")
        
        if handler_name:
            # Пытаемся найти и вызвать handler
            try:
                from app.services.workflows.step_handlers import get_step_handler
                handler = get_step_handler(handler_name)
                if handler:
                    return await handler(step, dependency_results, self.db, self.rag_service)
            except ImportError:
                logger.warning(f"[WorkflowOrchestrator] Handler {handler_name} not found")
        
        # Fallback к LLM
        prompt = f"""Выполни шаг: {step.name}

ОПИСАНИЕ:
{step.description}

КОНФИГУРАЦИЯ:
{json.dumps(step.config, ensure_ascii=False, indent=2)}

ДАННЫЕ ИЗ ПРЕДЫДУЩИХ ШАГОВ:
{json.dumps(dependency_results, ensure_ascii=False, indent=2)}

Выполни задачу и верни результат в формате JSON.
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        from app.services.langchain_agents.utils import extract_json_from_response
        result = extract_json_from_response(response_text)
        
        return result or {"raw_response": response_text}
    
    async def _handle_step_failure(
        self,
        step: WorkflowStep,
        error: Exception
    ) -> Dict[str, Any]:
        """Обработать ошибку шага с адаптацией."""
        logger.info(f"[WorkflowOrchestrator] Adapting to failure in step {step.name}")
        
        # Пробуем альтернативный подход
        prompt = f"""Шаг "{step.name}" завершился с ошибкой: {str(error)}

Предложи альтернативный способ выполнения задачи:
{step.description}

Если задачу невозможно выполнить, верни частичный результат или объясни проблему.
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "status": "adapted",
            "original_error": str(error),
            "adaptation": response_text
        }
    
    async def execute(self) -> Dict[str, Any]:
        """
        Выполнить весь workflow.
        
        Returns:
            Финальные результаты
        """
        if not self.plan:
            await self.generate_plan()
        
        if self.plan.requires_approval and not self.is_approved:
            return {
                "status": "awaiting_approval",
                "plan": self.get_plan_for_approval()
            }
        
        logger.info(f"[WorkflowOrchestrator] Starting execution of {len(self.plan.steps)} steps")
        
        # Группируем шаги по уровням зависимостей для параллельного выполнения
        execution_levels = self._group_steps_by_level()
        
        for level, steps in enumerate(execution_levels):
            logger.info(f"[WorkflowOrchestrator] Executing level {level}: {[s.name for s in steps]}")
            
            # Фильтруем пропущенные шаги
            steps_to_execute = [s for s in steps if s.status != "skipped"]
            
            if len(steps_to_execute) > 1:
                # Параллельное выполнение
                tasks = [self.execute_step(step) for step in steps_to_execute]
                await asyncio.gather(*tasks, return_exceptions=True)
            elif steps_to_execute:
                # Последовательное выполнение
                await self.execute_step(steps_to_execute[0])
        
        # Синтезируем финальный результат
        final_result = self._synthesize_results()
        
        logger.info(f"[WorkflowOrchestrator] Workflow completed")
        return final_result
    
    def _group_steps_by_level(self) -> List[List[WorkflowStep]]:
        """Группировать шаги по уровням зависимостей."""
        levels = []
        completed_ids = set()
        remaining_steps = list(self.plan.steps)
        
        while remaining_steps:
            # Находим шаги, все зависимости которых уже выполнены
            current_level = []
            for step in remaining_steps[:]:
                if all(dep in completed_ids for dep in step.dependencies):
                    current_level.append(step)
                    remaining_steps.remove(step)
            
            if not current_level:
                # Циклическая зависимость или ошибка
                logger.error(f"[WorkflowOrchestrator] Cannot resolve dependencies for: {[s.id for s in remaining_steps]}")
                current_level = remaining_steps
                remaining_steps = []
            
            levels.append(current_level)
            completed_ids.update(s.id for s in current_level)
        
        return levels
    
    def _synthesize_results(self) -> Dict[str, Any]:
        """Синтезировать финальные результаты."""
        completed_steps = [s for s in self.plan.steps if s.status == "completed"]
        failed_steps = [s for s in self.plan.steps if s.status == "failed"]
        skipped_steps = [s for s in self.plan.steps if s.status == "skipped"]
        
        return {
            "workflow_id": self.config.workflow_id,
            "status": "completed" if not failed_steps else "completed_with_errors",
            "summary": {
                "total_steps": len(self.plan.steps),
                "completed": len(completed_steps),
                "failed": len(failed_steps),
                "skipped": len(skipped_steps)
            },
            "results": self.results,
            "errors": [
                {"step": s.name, "error": s.error}
                for s in failed_steps
            ] if failed_steps else None
        }



