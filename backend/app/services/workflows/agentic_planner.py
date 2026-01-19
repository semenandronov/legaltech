"""
Agentic Planner - Качественная агентная архитектура для планирования задач.

Реализует:
- ReAct паттерн (Reasoning + Acting)
- Chain-of-Thought reasoning
- Self-reflection и self-correction
- Dynamic replanning на основе результатов
- Tool selection с объяснением выбора
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from app.services.llm_factory import create_llm
from app.models.workflow import WorkflowDefinition, WORKFLOW_TOOLS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import logging
import json
import re

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Типы задач для классификации"""
    DOCUMENT_ANALYSIS = "document_analysis"  # Анализ содержания документа
    RISK_CHECK = "risk_check"  # Проверка на риски
    DATA_EXTRACTION = "data_extraction"  # Извлечение данных
    QUESTION_ANSWERING = "question_answering"  # Ответ на вопрос
    COMPARISON = "comparison"  # Сравнение документов
    DOCUMENT_CREATION = "document_creation"  # Создание документа
    LEGAL_RESEARCH = "legal_research"  # Юридическое исследование
    FULL_REVIEW = "full_review"  # Полный анализ


@dataclass
class Thought:
    """Мысль агента (Chain-of-Thought)"""
    reasoning: str
    conclusion: str
    confidence: float = 0.8


@dataclass
class ToolSelection:
    """Выбор инструмента с обоснованием"""
    tool_name: str
    reason: str
    params: Dict[str, Any]
    expected_output: str
    priority: int = 1


@dataclass
class AgenticPlan:
    """План с агентным мышлением"""
    task_type: TaskType
    task_understanding: str
    reasoning_chain: List[Thought]
    tool_selections: List[ToolSelection]
    execution_order: List[List[str]]  # Группы параллельных шагов
    success_criteria: List[str]
    fallback_strategy: str


# Промпты для агентного мышления
TASK_UNDERSTANDING_PROMPT = """Ты - юридический AI-агент. Проанализируй задачу пользователя.

ЗАДАЧА: {user_task}

ДОКУМЕНТЫ:
{documents_info}

Ответь в формате JSON:
{{
    "task_type": "тип задачи из списка: document_analysis, risk_check, data_extraction, question_answering, comparison, document_creation, legal_research, full_review",
    "understanding": "Что именно хочет пользователь? Перефразируй задачу своими словами",
    "key_aspects": ["аспект1", "аспект2"],
    "required_outputs": ["что нужно получить в результате"],
    "complexity": "simple/medium/complex"
}}"""


TOOL_REASONING_PROMPT = """Ты - юридический AI-агент. Выбери инструменты для выполнения задачи.

ЗАДАЧА: {task_understanding}
ТИП ЗАДАЧИ: {task_type}
КЛЮЧЕВЫЕ АСПЕКТЫ: {key_aspects}

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_description}

ПРАВИЛА ВЫБОРА ИНСТРУМЕНТОВ:
1. summarize - ВСЕГДА используй первым для понимания документа (если не знаешь содержание)
2. extract_entities - для извлечения конкретных данных (даты, суммы, стороны)
3. rag - для ответа на КОНКРЕТНЫЙ вопрос по документам
4. playbook_check - для проверки на риски и соответствие правилам
5. tabular_review - для сравнения НЕСКОЛЬКИХ документов
6. legal_db - для поиска законов и судебной практики
7. document_draft - для создания нового документа

ТИПИЧНЫЕ КОМБИНАЦИИ:
- Анализ документа: summarize → extract_entities
- Проверка рисков: summarize → playbook_check
- Ответ на вопрос: rag
- Полный анализ: summarize → [extract_entities, playbook_check] → rag (если есть вопросы)

Ответь в формате JSON:
{{
    "reasoning": "Почему я выбираю эти инструменты...",
    "tools": [
        {{
            "tool_name": "имя",
            "reason": "почему этот инструмент нужен",
            "params": {{}},
            "expected_output": "что получим",
            "priority": 1,
            "depends_on": []
        }}
    ],
    "parallel_groups": [["step1", "step2"], ["step3"]],
    "success_criteria": ["критерий1", "критерий2"]
}}"""


SELF_REFLECTION_PROMPT = """Проверь свой план на ошибки.

ЗАДАЧА: {task_understanding}
ПЛАН: {plan}

Вопросы для проверки:
1. Все ли аспекты задачи покрыты?
2. Нет ли лишних шагов?
3. Правильный ли порядок выполнения?
4. Есть ли зависимости между шагами?

Ответь в формате JSON:
{{
    "is_valid": true/false,
    "issues": ["проблема1", "проблема2"],
    "suggestions": ["предложение1"],
    "corrected_plan": null или исправленный план
}}"""


class AgenticPlanner:
    """
    Агентный планировщик с Chain-of-Thought reasoning.
    
    Использует ReAct паттерн:
    1. Reason - понять задачу
    2. Act - выбрать действия
    3. Reflect - проверить план
    """
    
    def __init__(self):
        """Initialize agentic planner"""
        self.llm = None
        self._init_llm()
        
        # Описания инструментов
        self.tool_descriptions = {
            "summarize": {
                "name": "summarize",
                "description": "Создаёт краткое или детальное резюме документа",
                "when_to_use": "Когда нужно понять содержание документа, получить обзор",
                "params": {"style": "brief или detailed"},
                "output": "Текстовое резюме документа"
            },
            "extract_entities": {
                "name": "extract_entities",
                "description": "Извлекает структурированные данные: имена, даты, суммы, адреса",
                "when_to_use": "Когда нужны конкретные данные из документа",
                "params": {"entity_types": ["person", "organization", "date", "money", "address"]},
                "output": "JSON со списком сущностей по типам"
            },
            "rag": {
                "name": "rag",
                "description": "Семантический поиск и ответ на вопрос по документам",
                "when_to_use": "Когда есть конкретный вопрос, на который нужен ответ",
                "params": {"query": "вопрос", "top_k": 5},
                "output": "Ответ на вопрос с цитатами из документов"
            },
            "playbook_check": {
                "name": "playbook_check",
                "description": "Проверяет документ на соответствие правилам и выявляет риски",
                "when_to_use": "Когда нужно проверить договор на риски, соответствие стандартам",
                "params": {},
                "output": "Список найденных проблем и рекомендаций"
            },
            "tabular_review": {
                "name": "tabular_review",
                "description": "Создаёт сравнительную таблицу из нескольких документов",
                "when_to_use": "Когда нужно сравнить несколько документов по параметрам",
                "params": {"columns": ["список колонок"]},
                "output": "Таблица с данными из документов"
            },
            "legal_db": {
                "name": "legal_db",
                "description": "Поиск в правовых базах данных",
                "when_to_use": "Когда нужны ссылки на законы, судебную практику",
                "params": {"query": "тема поиска"},
                "output": "Релевантные правовые нормы и практика"
            },
            "document_draft": {
                "name": "document_draft",
                "description": "Создаёт черновик документа на основе контекста",
                "when_to_use": "Когда нужно создать новый документ",
                "params": {"document_type": "тип документа", "context": "контекст"},
                "output": "Текст документа"
            }
        }
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
            logger.info("AgenticPlanner: LLM initialized")
        except Exception as e:
            logger.warning(f"AgenticPlanner: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def create_plan(
        self,
        user_task: str,
        documents: List[Dict[str, Any]],
        available_tools: List[str],
        workflow_definition: Optional[WorkflowDefinition] = None
    ) -> AgenticPlan:
        """
        Создать план с агентным мышлением.
        
        Args:
            user_task: Задача пользователя
            documents: Доступные документы
            available_tools: Доступные инструменты
            workflow_definition: Опциональное определение workflow
            
        Returns:
            AgenticPlan с reasoning chain
        """
        # Если есть default_plan в definition, адаптируем его
        if workflow_definition and workflow_definition.default_plan:
            return self._adapt_default_plan(
                workflow_definition.default_plan,
                user_task,
                documents
            )
        
        # Step 1: Understand the task (Reason)
        task_understanding = await self._understand_task(user_task, documents)
        
        # Step 2: Select tools (Act)
        tool_selections, execution_order, success_criteria = await self._select_tools(
            task_understanding,
            documents,
            available_tools
        )
        
        # Step 3: Self-reflection (Reflect)
        plan = AgenticPlan(
            task_type=task_understanding["task_type"],
            task_understanding=task_understanding["understanding"],
            reasoning_chain=[
                Thought(
                    reasoning=f"Понимание задачи: {task_understanding['understanding']}",
                    conclusion=f"Тип задачи: {task_understanding['task_type'].value}",
                    confidence=0.9
                )
            ],
            tool_selections=tool_selections,
            execution_order=execution_order,
            success_criteria=success_criteria,
            fallback_strategy="При ошибке использовать summarize для базового анализа"
        )
        
        # Validate and potentially correct
        validated_plan = await self._validate_and_correct(plan, user_task)
        
        return validated_plan
    
    async def _understand_task(
        self,
        user_task: str,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Понять задачу пользователя"""
        if not self.llm:
            return self._fallback_understanding(user_task)
        
        docs_info = self._format_documents(documents)
        
        prompt = ChatPromptTemplate.from_template(TASK_UNDERSTANDING_PROMPT)
        chain = prompt | self.llm
        
        try:
            response = await chain.ainvoke({
                "user_task": user_task,
                "documents_info": docs_info
            })
            
            content = response.content if hasattr(response, 'content') else str(response)
            data = self._parse_json(content)
            
            # Map task type
            task_type_str = data.get("task_type", "document_analysis")
            try:
                task_type = TaskType(task_type_str)
            except ValueError:
                task_type = TaskType.DOCUMENT_ANALYSIS
            
            return {
                "task_type": task_type,
                "understanding": data.get("understanding", user_task),
                "key_aspects": data.get("key_aspects", []),
                "required_outputs": data.get("required_outputs", []),
                "complexity": data.get("complexity", "medium")
            }
            
        except Exception as e:
            logger.warning(f"Task understanding failed: {e}")
            return self._fallback_understanding(user_task)
    
    def _fallback_understanding(self, user_task: str) -> Dict[str, Any]:
        """Fallback понимание задачи на основе ключевых слов"""
        task_lower = user_task.lower()
        
        # Определяем тип задачи по ключевым словам
        if any(w in task_lower for w in ["риск", "проверь", "проблем", "соответств"]):
            task_type = TaskType.RISK_CHECK
        elif any(w in task_lower for w in ["извлеч", "данные", "стороны", "дат", "сумм"]):
            task_type = TaskType.DATA_EXTRACTION
        elif any(w in task_lower for w in ["что", "какой", "где", "когда", "почему", "?"]):
            task_type = TaskType.QUESTION_ANSWERING
        elif any(w in task_lower for w in ["сравни", "различ", "общ"]):
            task_type = TaskType.COMPARISON
        elif any(w in task_lower for w in ["составь", "напиши", "создай", "подготовь"]):
            task_type = TaskType.DOCUMENT_CREATION
        elif any(w in task_lower for w in ["закон", "практик", "норм", "право"]):
            task_type = TaskType.LEGAL_RESEARCH
        elif any(w in task_lower for w in ["полн", "всё", "детальн", "подробн"]):
            task_type = TaskType.FULL_REVIEW
        else:
            task_type = TaskType.DOCUMENT_ANALYSIS
        
        return {
            "task_type": task_type,
            "understanding": user_task,
            "key_aspects": [],
            "required_outputs": [],
            "complexity": "medium"
        }
    
    async def _select_tools(
        self,
        task_understanding: Dict[str, Any],
        documents: List[Dict[str, Any]],
        available_tools: List[str]
    ) -> Tuple[List[ToolSelection], List[List[str]], List[str]]:
        """Выбрать инструменты с обоснованием"""
        task_type = task_understanding["task_type"]
        
        # Используем предопределённые паттерны для надёжности
        patterns = self._get_tool_patterns()
        
        if task_type in patterns:
            pattern = patterns[task_type]
            tool_selections = []
            file_ids = [d.get("id") for d in documents if d.get("id")]
            
            for i, tool_info in enumerate(pattern["tools"]):
                tool_name = tool_info["name"]
                if tool_name not in available_tools and tool_name in self.tool_descriptions:
                    continue
                
                params = tool_info.get("params", {}).copy()
                # Inject file_ids for document tools
                if tool_name in ["summarize", "extract_entities", "rag", "playbook_check", "tabular_review"]:
                    params["file_ids"] = file_ids
                
                tool_selections.append(ToolSelection(
                    tool_name=tool_name,
                    reason=tool_info.get("reason", ""),
                    params=params,
                    expected_output=tool_info.get("expected_output", ""),
                    priority=i + 1
                ))
            
            return (
                tool_selections,
                pattern.get("execution_order", [[t["name"] for t in pattern["tools"]]]),
                pattern.get("success_criteria", ["Задача выполнена"])
            )
        
        # Fallback: summarize
        file_ids = [d.get("id") for d in documents if d.get("id")]
        return (
            [ToolSelection(
                tool_name="summarize",
                reason="Базовый анализ документа",
                params={"file_ids": file_ids, "style": "brief"},
                expected_output="Краткое резюме",
                priority=1
            )],
            [["summarize"]],
            ["Получено резюме документа"]
        )
    
    def _get_tool_patterns(self) -> Dict[TaskType, Dict[str, Any]]:
        """Предопределённые паттерны инструментов для типов задач"""
        return {
            TaskType.DOCUMENT_ANALYSIS: {
                "tools": [
                    {
                        "name": "summarize",
                        "reason": "Получить общее понимание документа",
                        "params": {"style": "detailed"},
                        "expected_output": "Детальное резюме документа"
                    },
                    {
                        "name": "extract_entities",
                        "reason": "Извлечь ключевые данные",
                        "params": {"entity_types": ["person", "organization", "date", "money"]},
                        "expected_output": "Структурированные данные"
                    }
                ],
                "execution_order": [["summarize"], ["extract_entities"]],
                "success_criteria": ["Получено резюме", "Извлечены ключевые данные"]
            },
            TaskType.RISK_CHECK: {
                "tools": [
                    {
                        "name": "summarize",
                        "reason": "Понять тип и содержание документа",
                        "params": {"style": "brief"},
                        "expected_output": "Краткое резюме"
                    },
                    {
                        "name": "playbook_check",
                        "reason": "Проверить на риски и соответствие правилам",
                        "params": {},
                        "expected_output": "Список рисков и рекомендаций"
                    }
                ],
                "execution_order": [["summarize"], ["playbook_check"]],
                "success_criteria": ["Документ проанализирован", "Риски выявлены"]
            },
            TaskType.DATA_EXTRACTION: {
                "tools": [
                    {
                        "name": "extract_entities",
                        "reason": "Извлечь запрошенные данные",
                        "params": {"entity_types": ["person", "organization", "date", "money", "address"]},
                        "expected_output": "Структурированные данные"
                    }
                ],
                "execution_order": [["extract_entities"]],
                "success_criteria": ["Данные извлечены"]
            },
            TaskType.QUESTION_ANSWERING: {
                "tools": [
                    {
                        "name": "rag",
                        "reason": "Найти ответ на вопрос в документах",
                        "params": {"top_k": 5},
                        "expected_output": "Ответ с цитатами"
                    }
                ],
                "execution_order": [["rag"]],
                "success_criteria": ["Получен ответ на вопрос"]
            },
            TaskType.COMPARISON: {
                "tools": [
                    {
                        "name": "tabular_review",
                        "reason": "Создать сравнительную таблицу",
                        "params": {},
                        "expected_output": "Таблица сравнения"
                    }
                ],
                "execution_order": [["tabular_review"]],
                "success_criteria": ["Создана сравнительная таблица"]
            },
            TaskType.DOCUMENT_CREATION: {
                "tools": [
                    {
                        "name": "summarize",
                        "reason": "Понять контекст для создания документа",
                        "params": {"style": "brief"},
                        "expected_output": "Контекст"
                    },
                    {
                        "name": "document_draft",
                        "reason": "Создать документ",
                        "params": {},
                        "expected_output": "Черновик документа"
                    }
                ],
                "execution_order": [["summarize"], ["document_draft"]],
                "success_criteria": ["Документ создан"]
            },
            TaskType.LEGAL_RESEARCH: {
                "tools": [
                    {
                        "name": "summarize",
                        "reason": "Понять контекст вопроса",
                        "params": {"style": "brief"},
                        "expected_output": "Контекст"
                    },
                    {
                        "name": "legal_db",
                        "reason": "Найти релевантные правовые нормы",
                        "params": {},
                        "expected_output": "Правовые нормы и практика"
                    }
                ],
                "execution_order": [["summarize"], ["legal_db"]],
                "success_criteria": ["Найдены релевантные нормы"]
            },
            TaskType.FULL_REVIEW: {
                "tools": [
                    {
                        "name": "summarize",
                        "reason": "Получить общее понимание",
                        "params": {"style": "detailed"},
                        "expected_output": "Детальное резюме"
                    },
                    {
                        "name": "extract_entities",
                        "reason": "Извлечь все ключевые данные",
                        "params": {"entity_types": ["person", "organization", "date", "money", "address"]},
                        "expected_output": "Структурированные данные"
                    },
                    {
                        "name": "playbook_check",
                        "reason": "Проверить на риски",
                        "params": {},
                        "expected_output": "Список рисков"
                    }
                ],
                "execution_order": [["summarize"], ["extract_entities", "playbook_check"]],
                "success_criteria": ["Полный анализ выполнен", "Данные извлечены", "Риски проверены"]
            }
        }
    
    async def _validate_and_correct(
        self,
        plan: AgenticPlan,
        user_task: str
    ) -> AgenticPlan:
        """Валидация и коррекция плана"""
        # Базовая валидация
        if not plan.tool_selections:
            # Добавить fallback
            plan.tool_selections = [ToolSelection(
                tool_name="summarize",
                reason="Fallback: базовый анализ",
                params={"style": "brief"},
                expected_output="Резюме документа",
                priority=1
            )]
            plan.execution_order = [["summarize"]]
        
        return plan
    
    def _format_documents(self, documents: List[Dict[str, Any]]) -> str:
        """Форматировать информацию о документах"""
        if not documents:
            return "Документы не загружены"
        
        lines = []
        for doc in documents:
            name = doc.get("filename", doc.get("name", "Без имени"))
            doc_type = doc.get("type", "unknown")
            lines.append(f"- {name} (тип: {doc_type})")
        
        return "\n".join(lines)
    
    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Парсинг JSON из ответа LLM"""
        # Попробовать найти JSON блок
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Попробовать найти { }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass
        
        return {}
    
    def _adapt_default_plan(
        self,
        default_plan: Dict[str, Any],
        user_task: str,
        documents: List[Dict[str, Any]]
    ) -> AgenticPlan:
        """Адаптировать default_plan из workflow definition"""
        file_ids = [d.get("id") for d in documents if d.get("id")]
        
        tool_selections = []
        for i, step in enumerate(default_plan.get("steps", [])):
            tool_name = step.get("tool_name") or step.get("tool")
            params = step.get("tool_params", step.get("params", {})).copy()
            
            # Inject file_ids
            if tool_name in ["summarize", "extract_entities", "rag", "playbook_check", "tabular_review"]:
                if "file_ids" not in params:
                    params["file_ids"] = file_ids
            
            tool_selections.append(ToolSelection(
                tool_name=tool_name,
                reason=step.get("description", ""),
                params=params,
                expected_output=step.get("expected_output", ""),
                priority=i + 1
            ))
        
        return AgenticPlan(
            task_type=TaskType.DOCUMENT_ANALYSIS,
            task_understanding=user_task,
            reasoning_chain=[Thought(
                reasoning="Использую предопределённый план workflow",
                conclusion="План адаптирован под документы",
                confidence=0.95
            )],
            tool_selections=tool_selections,
            execution_order=[[ts.tool_name for ts in tool_selections]],
            success_criteria=["План выполнен"],
            fallback_strategy="Использовать summarize"
        )
    
    def plan_to_execution_plan(self, agentic_plan: AgenticPlan) -> Dict[str, Any]:
        """Конвертировать AgenticPlan в формат ExecutionPlan"""
        from app.services.workflows.planning_agent import ExecutionPlan, PlanStep, SubGoal
        
        goals = [SubGoal(
            id="goal_1",
            description=agentic_plan.task_understanding,
            priority=1
        )]
        
        steps = []
        for i, ts in enumerate(agentic_plan.tool_selections):
            steps.append(PlanStep(
                id=f"step_{i + 1}",
                name=f"{ts.tool_name}: {ts.reason[:50]}",
                description=ts.reason,
                step_type="tool_call",
                tool_name=ts.tool_name,
                tool_params=ts.params,
                depends_on=[],  # TODO: build from execution_order
                expected_output=ts.expected_output,
                goal_id="goal_1",
                estimated_duration_seconds=30
            ))
        
        return ExecutionPlan(
            goals=goals,
            steps=steps,
            estimated_total_duration_seconds=len(steps) * 30,
            summary=f"План: {agentic_plan.task_type.value}"
        )

