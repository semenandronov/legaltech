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
PLANNING_PROMPT = """Ты - AI-агент для юридического анализа документов. Создай оптимальный план выполнения задачи.

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:
{user_task}

ДОСТУПНЫЕ ДОКУМЕНТЫ:
{documents_info}

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{available_tools}

═══════════════════════════════════════════════════════════════
КОГДА КАКОЙ ИНСТРУМЕНТ ИСПОЛЬЗОВАТЬ:
═══════════════════════════════════════════════════════════════

1. **summarize** - ПЕРВЫЙ ШАГ для понимания документов
   - Используй когда: нужно понять содержание, получить обзор, краткое изложение
   - Параметры: {{"style": "brief"}} или {{"style": "detailed"}}
   - Примеры задач: "что в документе", "о чём договор", "краткое содержание"

2. **extract_entities** - Извлечение структурированных данных
   - Используй когда: нужны конкретные данные (даты, суммы, стороны, адреса)
   - Параметры: {{"entity_types": ["person", "organization", "date", "money", "address"]}}
   - Примеры задач: "кто стороны", "какие даты", "какие суммы"

3. **rag** - Поиск ответов на конкретные вопросы
   - Используй когда: нужен ответ на конкретный вопрос по документам
   - Параметры: {{"query": "конкретный вопрос", "top_k": 5}}
   - Примеры задач: "найди пункт о...", "что говорится о...", "есть ли упоминание..."

4. **playbook_check** - Проверка на соответствие правилам
   - Используй когда: нужно проверить договор на риски, соответствие стандартам
   - Параметры: {{"playbook_id": "default"}} или без параметров
   - Примеры задач: "проверь договор", "найди риски", "соответствует ли стандартам"

5. **tabular_review** - Сравнительный анализ нескольких документов
   - Используй когда: нужно сравнить документы, создать таблицу данных
   - Параметры: {{"columns": ["Параметр1", "Параметр2"]}}
   - Примеры задач: "сравни договоры", "создай таблицу", "извлеки данные в таблицу"

6. **legal_db** - Поиск в правовых базах
   - Используй когда: нужны ссылки на законы, судебную практику
   - Параметры: {{"query": "тема поиска"}}
   - Примеры задач: "какой закон регулирует", "судебная практика по..."

7. **document_draft** - Создание документа
   - Используй когда: нужно создать новый документ на основе анализа
   - Параметры: {{"document_type": "тип", "context": "контекст"}}
   - Примеры задач: "составь ответ", "напиши заключение", "подготовь документ"

═══════════════════════════════════════════════════════════════
ТИПИЧНЫЕ СЦЕНАРИИ (выбери подходящий):
═══════════════════════════════════════════════════════════════

СЦЕНАРИЙ A - "Анализ документа" (что в документе, о чём он):
1. summarize → получить общее понимание
2. extract_entities → извлечь ключевые данные

СЦЕНАРИЙ B - "Проверка договора на риски":
1. summarize → понять тип и содержание
2. playbook_check → проверить на соответствие правилам
3. extract_entities → извлечь ключевые условия

СЦЕНАРИЙ C - "Ответ на конкретный вопрос":
1. rag → найти релевантную информацию

СЦЕНАРИЙ D - "Полный анализ договора":
1. summarize → общее понимание
2. extract_entities → стороны, даты, суммы (параллельно с п.3)
3. playbook_check → проверка на риски (параллельно с п.2)
4. rag → ответы на специфические вопросы (если есть)

СЦЕНАРИЙ E - "Сравнение документов":
1. tabular_review → сравнительная таблица

═══════════════════════════════════════════════════════════════

Верни план СТРОГО в формате JSON (без markdown, без комментариев):
{{
    "goals": [
        {{"id": "goal_1", "description": "Описание цели", "priority": 1}}
    ],
    "steps": [
        {{
            "id": "step_1",
            "name": "Название шага",
            "description": "Что делаем и зачем",
            "step_type": "tool_call",
            "tool_name": "имя_инструмента",
            "tool_params": {{}},
            "depends_on": [],
            "expected_output": "Что получим",
            "goal_id": "goal_1",
            "estimated_duration_seconds": 30
        }}
    ],
    "summary": "Краткое описание плана"
}}

ПРАВИЛА:
1. Выбери ПОДХОДЯЩИЙ сценарий или создай свой
2. НЕ используй инструменты, которые не нужны для задачи
3. Шаги без зависимостей могут выполняться параллельно
4. Верни ТОЛЬКО JSON, без текста до или после"""


class PlanningAgent:
    """
    Agentic AI для планирования задач.
    
    Понимает natural language задачу и создаёт план выполнения
    с использованием доступных инструментов.
    
    Использует AgenticPlanner для качественного планирования с:
    - Классификацией типа задачи
    - Предопределёнными паттернами инструментов
    - Chain-of-Thought reasoning
    """
    
    def __init__(self):
        """Initialize planning agent"""
        self.llm = None
        self.agentic_planner = None
        self._init_llm()
        self._init_agentic_planner()
    
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
    
    def _init_agentic_planner(self):
        """Initialize AgenticPlanner for better task understanding"""
        try:
            from app.services.workflows.agentic_planner import AgenticPlanner
            self.agentic_planner = AgenticPlanner()
            logger.info("PlanningAgent: AgenticPlanner initialized")
        except Exception as e:
            logger.warning(f"PlanningAgent: Failed to initialize AgenticPlanner: {e}")
            self.agentic_planner = None
    
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
        
        # Use AgenticPlanner for better task understanding (preferred)
        if self.agentic_planner:
            try:
                agentic_plan = await self.agentic_planner.create_plan(
                    user_task=user_task,
                    documents=available_documents,
                    available_tools=available_tools,
                    workflow_definition=workflow_definition
                )
                
                # Convert to ExecutionPlan
                return self._convert_agentic_plan(agentic_plan, available_documents)
                
            except Exception as e:
                logger.warning(f"AgenticPlanner failed, falling back to LLM: {e}")
        
        # Fallback: generate plan using LLM
        return await self._generate_plan_with_llm(
            user_task,
            available_documents,
            available_tools
        )
    
    def _convert_agentic_plan(
        self,
        agentic_plan,
        documents: List[Dict[str, Any]]
    ) -> ExecutionPlan:
        """Convert AgenticPlan to ExecutionPlan"""
        file_ids = [d.get("id") for d in documents if d.get("id")]
        
        goals = [SubGoal(
            id="goal_1",
            description=agentic_plan.task_understanding,
            priority=1
        )]
        
        steps = []
        for i, ts in enumerate(agentic_plan.tool_selections):
            # Ensure file_ids are in params for document tools
            params = ts.params.copy() if ts.params else {}
            document_tools = ["summarize", "extract_entities", "rag", "playbook_check", "tabular_review"]
            if ts.tool_name in document_tools and file_ids:
                if "file_ids" not in params:
                    params["file_ids"] = file_ids
            
            steps.append(PlanStep(
                id=f"step_{i + 1}",
                name=ts.tool_name,
                description=ts.reason,
                step_type="tool_call",
                tool_name=ts.tool_name,
                tool_params=params,
                depends_on=[],
                expected_output=ts.expected_output,
                goal_id="goal_1",
                estimated_duration_seconds=30
            ))
        
        # Build dependencies from execution_order
        if agentic_plan.execution_order and len(agentic_plan.execution_order) > 1:
            step_by_tool = {s.tool_name: s for s in steps}
            for group_idx, group in enumerate(agentic_plan.execution_order[1:], 1):
                prev_group = agentic_plan.execution_order[group_idx - 1]
                for tool_name in group:
                    if tool_name in step_by_tool:
                        step_by_tool[tool_name].depends_on = [
                            step_by_tool[t].id for t in prev_group 
                            if t in step_by_tool
                        ]
        
        logger.info(f"AgenticPlanner created plan: {agentic_plan.task_type.value} with {len(steps)} steps")
        
        return ExecutionPlan(
            goals=goals,
            steps=steps,
            estimated_total_duration_seconds=len(steps) * 30,
            summary=f"План ({agentic_plan.task_type.value}): {agentic_plan.task_understanding[:100]}"
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
            # Try multiple strategies to extract JSON
            data = None
            
            # Strategy 1: Find JSON block between ```json and ```
            json_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
            if json_block_match:
                try:
                    data = json.loads(json_block_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Strategy 2: Find outermost { } pair more carefully
            if data is None:
                # Find the first { and last }
                first_brace = response.find('{')
                last_brace = response.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    json_str = response[first_brace:last_brace + 1]
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try to fix common issues
                        # Remove trailing commas before } or ]
                        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                        # Fix unquoted keys (simple cases)
                        json_str = re.sub(r'(\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError:
                            pass
            
            # Strategy 3: Original regex approach
            if data is None:
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    data = json.loads(json_match.group())
            
            if data is None:
                logger.error(f"No valid JSON found in response: {response[:500]}...")
                raise ValueError("No valid JSON found in response")
            
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
            logger.warning("Creating fallback plan with summarize step")
            
            # Create a simple fallback plan
            file_ids = [d.get("id") for d in documents if d.get("id")]
            return ExecutionPlan(
                goals=[SubGoal(
                    id="goal_1",
                    description="Анализ документов",
                    priority=1
                )],
                steps=[PlanStep(
                    id="step_1",
                    name="Суммаризация документов",
                    description="Создание краткого резюме загруженных документов",
                    step_type="tool_call",
                    tool_name="summarize",
                    tool_params={"file_ids": file_ids, "style": "brief"},
                    depends_on=[],
                    expected_output="Краткое резюме документов",
                    goal_id="goal_1",
                    estimated_duration_seconds=60
                )],
                estimated_total_duration_seconds=60,
                summary="Fallback план: суммаризация документов"
            )
    
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

