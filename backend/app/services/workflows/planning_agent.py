"""Planning Agent - Agentic AI для планирования задач"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from langchain_core.prompts import ChatPromptTemplate
from app.services.llm_factory import create_llm
from app.models.workflow import WorkflowDefinition, WORKFLOW_TOOLS
import logging
import json
import re
import uuid

logger = logging.getLogger(__name__)


@dataclass
class SubGoal:
    """A sub-goal within the execution plan"""
    id: str
    description: str
    parent_goal_id: Optional[str] = None
    priority: int = 0


@dataclass
class PlanStep:
    """A step in the execution plan"""
    id: str
    name: str
    description: str
    step_type: str  # tool_call, analysis, validation, aggregation
    tool_name: Optional[str] = None
    tool_params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    expected_output: str = ""
    goal_id: Optional[str] = None
    estimated_duration_seconds: int = 60


@dataclass
class ExecutionPlan:
    """Complete execution plan"""
    goals: List[SubGoal]
    steps: List[PlanStep]
    estimated_total_duration_seconds: int = 0
    summary: str = ""


# Промпт для планирования
PLANNING_PROMPT = """Ты - AI-агент для юридического анализа. Твоя задача - создать план выполнения для заданной задачи.

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:
{user_task}

ДОСТУПНЫЕ ДОКУМЕНТЫ:
{documents_info}

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{available_tools}

ЗАДАЧА:
1. Определи высокоуровневые цели для выполнения задачи
2. Разбей каждую цель на конкретные шаги
3. Для каждого шага определи:
   - Какой инструмент использовать
   - Какие параметры передать
   - От каких других шагов он зависит
4. Оцени примерное время выполнения

ИНСТРУМЕНТЫ И ИХ ПРИМЕНЕНИЕ:
- tabular_review: Массовый анализ документов, извлечение данных в таблицу
- rag: Семантический поиск по документам, ответы на вопросы
- web_search: Поиск информации в интернете
- legal_db: Поиск в юридических базах данных
- playbook_check: Проверка документа на соответствие правилам
- summarize: Создание резюме
- extract_entities: Извлечение именованных сущностей (люди, организации, даты)
- document_draft: Создание черновика документа

Верни план в формате JSON:
{{
    "goals": [
        {{
            "id": "goal_1",
            "description": "Описание цели",
            "priority": 1
        }}
    ],
    "steps": [
        {{
            "id": "step_1",
            "name": "Название шага",
            "description": "Подробное описание",
            "step_type": "tool_call",
            "tool_name": "имя_инструмента",
            "tool_params": {{}},
            "depends_on": [],
            "expected_output": "Что ожидаем получить",
            "goal_id": "goal_1",
            "estimated_duration_seconds": 60
        }}
    ],
    "summary": "Краткое описание плана"
}}

ВАЖНО:
- Шаги должны быть конкретными и выполнимыми
- Правильно указывай зависимости между шагами
- Используй только доступные инструменты
- Оптимизируй план для параллельного выполнения где возможно"""


class PlanningAgent:
    """
    Agentic AI для планирования задач.
    
    Понимает natural language задачу и создаёт план выполнения
    с использованием доступных инструментов.
    """
    
    def __init__(self):
        """Initialize planning agent"""
        self.llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            # Use create_llm with use_rate_limiting=False for LangChain compatibility
            # RateLimitedLLMWrapper is not compatible with LangChain's | operator
            self.llm = create_llm(temperature=0.2, use_rate_limiting=False)
            logger.info("PlanningAgent: LLM initialized (without rate limiting wrapper)")
        except Exception as e:
            logger.warning(f"PlanningAgent: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def create_plan(
        self,
        user_task: str,
        available_documents: List[Dict[str, Any]],
        available_tools: List[str],
        workflow_definition: Optional[WorkflowDefinition] = None
    ) -> ExecutionPlan:
        """
        Create an execution plan for a user task
        
        Args:
            user_task: User's task in natural language
            available_documents: List of available documents
            available_tools: List of available tool names
            workflow_definition: Optional workflow definition with default plan
            
        Returns:
            ExecutionPlan with goals and steps
        """
        # If workflow has a default plan, use it as a template
        if workflow_definition and workflow_definition.default_plan:
            return self._adapt_default_plan(
                workflow_definition.default_plan,
                user_task,
                available_documents
            )
        
        # Otherwise, generate a new plan using LLM
        return await self._generate_plan_with_llm(
            user_task,
            available_documents,
            available_tools
        )
    
    def _adapt_default_plan(
        self,
        default_plan: Dict[str, Any],
        user_task: str,
        documents: List[Dict[str, Any]]
    ) -> ExecutionPlan:
        """Adapt a default plan template to the specific task"""
        goals = []
        steps = []
        
        # Convert goals
        for goal_data in default_plan.get("goals", []):
            if isinstance(goal_data, str):
                goal = SubGoal(
                    id=f"goal_{len(goals) + 1}",
                    description=goal_data,
                    priority=len(goals)
                )
            else:
                goal = SubGoal(
                    id=goal_data.get("id", f"goal_{len(goals) + 1}"),
                    description=goal_data.get("description", ""),
                    priority=goal_data.get("priority", len(goals))
                )
            goals.append(goal)
        
        # Convert steps
        file_ids = [d.get("id") for d in documents if d.get("id")]
        
        for i, step_data in enumerate(default_plan.get("steps", [])):
            step_id = step_data.get("id", f"step_{i + 1}")
            tool_name = step_data.get("tool")
            
            # Build tool params based on tool type
            tool_params = step_data.get("tool_params", {})
            
            # Auto-inject file_ids for document-related tools
            document_tools = ["tabular_review", "rag", "summarize", "extract_entities", "playbook_check"]
            if tool_name in document_tools and file_ids:
                if "file_ids" not in tool_params:
                    tool_params["file_ids"] = file_ids
            
            step = PlanStep(
                id=step_id,
                name=step_data.get("name", f"Step {i + 1}"),
                description=step_data.get("description", ""),
                step_type="tool_call" if tool_name else "analysis",
                tool_name=tool_name,
                tool_params=tool_params,
                depends_on=step_data.get("depends_on", []),
                expected_output=step_data.get("expected_output", ""),
                goal_id=step_data.get("goal_id"),
                estimated_duration_seconds=step_data.get("estimated_duration_seconds", 60)
            )
            steps.append(step)
        
        # Calculate total duration
        total_duration = sum(s.estimated_duration_seconds for s in steps)
        
        return ExecutionPlan(
            goals=goals,
            steps=steps,
            estimated_total_duration_seconds=total_duration,
            summary=f"План на основе шаблона: {len(steps)} шагов для выполнения задачи"
        )
    
    async def _generate_plan_with_llm(
        self,
        user_task: str,
        documents: List[Dict[str, Any]],
        available_tools: List[str]
    ) -> ExecutionPlan:
        """Generate a plan using LLM"""
        if not self.llm:
            raise ValueError("LLM not initialized")
        
        # Format documents info
        docs_info = self._format_documents_info(documents)
        
        # Format tools info
        tools_info = self._format_tools_info(available_tools)
        
        # Create prompt
        prompt = ChatPromptTemplate.from_template(PLANNING_PROMPT)
        chain = prompt | self.llm
        
        # Generate plan
        response = await chain.ainvoke({
            "user_task": user_task,
            "documents_info": docs_info,
            "available_tools": tools_info
        })
        
        # Parse response
        return self._parse_plan_response(response.content, documents)
    
    def _format_documents_info(self, documents: List[Dict[str, Any]]) -> str:
        """Format documents for the prompt"""
        if not documents:
            return "Документы не предоставлены"
        
        lines = [f"Всего документов: {len(documents)}"]
        
        for i, doc in enumerate(documents[:20]):  # Limit to first 20
            name = doc.get("filename", doc.get("name", f"Document {i+1}"))
            doc_type = doc.get("type", "unknown")
            lines.append(f"- {name} ({doc_type})")
        
        if len(documents) > 20:
            lines.append(f"... и ещё {len(documents) - 20} документов")
        
        return "\n".join(lines)
    
    def _format_tools_info(self, available_tools: List[str]) -> str:
        """Format tools info for the prompt"""
        lines = []
        
        tool_descriptions = {t["name"]: t["description"] for t in WORKFLOW_TOOLS}
        
        for tool in available_tools:
            desc = tool_descriptions.get(tool, "")
            lines.append(f"- {tool}: {desc}")
        
        return "\n".join(lines)
    
    def _parse_plan_response(
        self,
        response: str,
        documents: List[Dict[str, Any]]
    ) -> ExecutionPlan:
        """Parse LLM response into ExecutionPlan"""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                raise ValueError("No JSON found in response")
            
            data = json.loads(json_match.group())
            
            # Parse goals
            goals = []
            for goal_data in data.get("goals", []):
                goal = SubGoal(
                    id=goal_data.get("id", f"goal_{len(goals) + 1}"),
                    description=goal_data.get("description", ""),
                    priority=goal_data.get("priority", len(goals))
                )
                goals.append(goal)
            
            # Parse steps
            steps = []
            file_ids = [d.get("id") for d in documents if d.get("id")]
            
            for i, step_data in enumerate(data.get("steps", [])):
                tool_params = step_data.get("tool_params", {})
                tool_name = step_data.get("tool_name")
                
                # Auto-inject file_ids for document-related tools
                document_tools = ["tabular_review", "rag", "summarize", "extract_entities", "playbook_check"]
                if tool_name in document_tools and file_ids:
                    if "file_ids" not in tool_params:
                        tool_params["file_ids"] = file_ids
                
                step = PlanStep(
                    id=step_data.get("id", f"step_{i + 1}"),
                    name=step_data.get("name", f"Step {i + 1}"),
                    description=step_data.get("description", ""),
                    step_type=step_data.get("step_type", "tool_call"),
                    tool_name=tool_name,
                    tool_params=tool_params,
                    depends_on=step_data.get("depends_on", []),
                    expected_output=step_data.get("expected_output", ""),
                    goal_id=step_data.get("goal_id"),
                    estimated_duration_seconds=step_data.get("estimated_duration_seconds", 60)
                )
                steps.append(step)
            
            # Calculate total duration
            total_duration = sum(s.estimated_duration_seconds for s in steps)
            
            return ExecutionPlan(
                goals=goals,
                steps=steps,
                estimated_total_duration_seconds=total_duration,
                summary=data.get("summary", "")
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse plan response: {e}")
            raise ValueError(f"Failed to parse planning response: {e}")
    
    async def refine_plan(
        self,
        current_plan: ExecutionPlan,
        feedback: str,
        completed_steps: List[str]
    ) -> ExecutionPlan:
        """
        Refine a plan based on feedback or intermediate results
        
        Args:
            current_plan: Current execution plan
            feedback: Feedback or new information
            completed_steps: List of completed step IDs
            
        Returns:
            Refined ExecutionPlan
        """
        # Filter out completed steps
        remaining_steps = [
            s for s in current_plan.steps 
            if s.id not in completed_steps
        ]
        
        # Update dependencies
        for step in remaining_steps:
            step.depends_on = [
                d for d in step.depends_on 
                if d not in completed_steps
            ]
        
        # For now, just return the filtered plan
        # In a full implementation, we would use LLM to refine based on feedback
        return ExecutionPlan(
            goals=current_plan.goals,
            steps=remaining_steps,
            estimated_total_duration_seconds=sum(s.estimated_duration_seconds for s in remaining_steps),
            summary=current_plan.summary
        )
    
    def validate_plan(self, plan: ExecutionPlan) -> List[str]:
        """
        Validate a plan for consistency
        
        Args:
            plan: Execution plan to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not plan.steps:
            errors.append("План не содержит шагов")
            return errors
        
        step_ids = {s.id for s in plan.steps}
        
        for step in plan.steps:
            # Check dependencies exist
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"Шаг {step.id} зависит от несуществующего шага {dep}")
            
            # Check for circular dependencies
            if step.id in step.depends_on:
                errors.append(f"Шаг {step.id} зависит сам от себя")
            
            # Check tool validity
            if step.step_type == "tool_call" and not step.tool_name:
                errors.append(f"Шаг {step.id} типа tool_call не имеет инструмента")
        
        # Check for unreachable steps (circular dependency chains)
        # Simple check: ensure there's at least one step with no dependencies
        steps_without_deps = [s for s in plan.steps if not s.depends_on]
        if not steps_without_deps:
            errors.append("Нет начального шага без зависимостей")
        
        return errors
    
    def plan_to_dict(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Convert ExecutionPlan to dictionary"""
        return {
            "goals": [
                {
                    "id": g.id,
                    "description": g.description,
                    "parent_goal_id": g.parent_goal_id,
                    "priority": g.priority
                }
                for g in plan.goals
            ],
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "step_type": s.step_type,
                    "tool_name": s.tool_name,
                    "tool_params": s.tool_params,
                    "depends_on": s.depends_on,
                    "expected_output": s.expected_output,
                    "goal_id": s.goal_id,
                    "estimated_duration_seconds": s.estimated_duration_seconds
                }
                for s in plan.steps
            ],
            "estimated_total_duration_seconds": plan.estimated_total_duration_seconds,
            "summary": plan.summary
        }

