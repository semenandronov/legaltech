"""
Autonomous Chat Agent - Автономный агент с динамическим планированием

Ключевые особенности:
1. ПОНИМАНИЕ: Глубокий анализ запроса пользователя
2. ПЛАНИРОВАНИЕ: Создание плана под КОНКРЕТНУЮ задачу (не выбор из готовых)
3. ВЫПОЛНЕНИЕ: Динамическое выполнение шагов (инструменты ИЛИ кастомные LLM-запросы)
4. СИНТЕЗ: Объединение результатов в связный ответ

Агент НЕ ограничен фиксированным набором инструментов.
Он может решить ЛЮБУЮ задачу, создавая план под неё.
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from sqlalchemy.orm import Session
import logging
import json
import asyncio

from app.services.chat.events import SSESerializer
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Сложность задачи"""
    SIMPLE = "simple"           # Простой вопрос — быстрый путь
    MODERATE = "moderate"       # Средняя сложность — 2-3 шага
    COMPLEX = "complex"         # Сложная задача — полное планирование


class StepType(Enum):
    """Тип шага в плане"""
    SEARCH = "search"                   # Поиск в документах
    SUMMARIZE = "summarize"             # Суммаризация
    EXTRACT = "extract"                 # Извлечение сущностей
    ANALYZE = "analyze"                 # Анализ (риски, противоречия)
    COMPARE = "compare"                 # Сравнение
    GENERATE = "generate"               # Генерация текста
    LEGAL_RESEARCH = "legal_research"   # Поиск в правовых базах
    WEB_SEARCH = "web_search"           # Веб-поиск
    CUSTOM = "custom"                   # Кастомный LLM-запрос


@dataclass
class PlanStep:
    """Шаг плана выполнения"""
    step_id: int
    step_type: StepType
    description: str                    # Что нужно сделать
    instruction: str                    # Инструкция для LLM
    query: Optional[str] = None         # Запрос для поиска (если нужен)
    depends_on: List[int] = field(default_factory=list)  # Зависимости от других шагов
    params: Dict[str, Any] = field(default_factory=dict)  # Дополнительные параметры


@dataclass
class ExecutionPlan:
    """План выполнения задачи"""
    task_understanding: str             # Понимание задачи
    complexity: TaskComplexity          # Оценка сложности
    steps: List[PlanStep]               # Шаги плана
    expected_output: str                # Ожидаемый формат ответа


@dataclass
class StepResult:
    """Результат выполнения шага"""
    step_id: int
    success: bool
    content: str
    sources: List[str] = field(default_factory=list)


class AutonomousChatAgent:
    """
    Автономный агент с динамическим планированием.
    
    В отличие от ReActChatAgent с фиксированными инструментами,
    этот агент:
    1. Анализирует задачу
    2. Создаёт КАСТОМНЫЙ план под неё
    3. Выполняет план динамически
    4. Может решить ЛЮБУЮ задачу
    """
    
    def __init__(
        self,
        case_id: str,
        db: Session,
        rag_service: RAGService,
        current_user: Optional[User] = None,
        # Пользовательские переключатели
        legal_research: bool = False,
        deep_think: bool = False,
        web_search: bool = False,
        chat_history: Optional[List[Dict[str, str]]] = None
    ):
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        self.chat_history = chat_history or []
        
        # Создаём LLM
        self.llm = self._create_llm()
        
        # Кэш результатов шагов
        self.step_results: Dict[int, StepResult] = {}
        
        logger.info(
            f"[AutonomousAgent] Initialized for case {case_id} "
            f"(deep_think={deep_think}, legal_research={legal_research}, web_search={web_search})"
        )
    
    def _create_llm(self):
        """Создать LLM"""
        from app.services.llm_factory import create_legal_llm
        from app.config import config
        
        if self.deep_think:
            model = config.GIGACHAT_PRO_MODEL or "GigaChat-Pro"
            return create_legal_llm(model=model, temperature=0.2)
        return create_legal_llm(temperature=0.1)
    
    async def handle(self, question: str) -> AsyncGenerator[str, None]:
        """
        Обработать запрос пользователя
        
        ВСЕГДА использует FULL PATH (4 фазы планирования):
        1. UNDERSTANDING — глубокое понимание запроса
        2. PLANNING — создание кастомного плана под задачу
        3. EXECUTION — динамическое выполнение шагов
        4. SYNTHESIS — синтез ответа из результатов
        
        Агент САМ планирует под каждую задачу, не ограничен фиксированными инструментами.
        """
        try:
            logger.info(f"[AutonomousAgent] Processing: {question[:100]}...")
            
            # ===== ФАЗА 1: ПОНИМАНИЕ =====
            yield SSESerializer.reasoning(
                phase="understanding",
                step=1,
                total_steps=4,
                content="Анализирую ваш запрос..."
            )
            
            understanding = await self._understand_request(question)
            
            yield SSESerializer.reasoning(
                phase="understanding",
                step=1,
                total_steps=4,
                content=f"Понял задачу: {understanding['summary']}"
            )
            
            # ===== ФАЗА 2: ПЛАНИРОВАНИЕ =====
            yield SSESerializer.reasoning(
                phase="planning",
                step=2,
                total_steps=4,
                content="Создаю план выполнения..."
            )
            
            plan = await self._create_plan(question, understanding)
            
            yield SSESerializer.reasoning(
                phase="planning",
                step=2,
                total_steps=4,
                content=f"План готов: {len(plan.steps)} шагов ({plan.complexity.value})"
            )
            
            # ===== ФАЗА 3: ВЫПОЛНЕНИЕ =====
            yield SSESerializer.reasoning(
                phase="execution",
                step=3,
                total_steps=4,
                content="Выполняю план..."
            )
            
            async for event in self._execute_plan(plan):
                yield event
            
            # ===== ФАЗА 4: СИНТЕЗ =====
            yield SSESerializer.reasoning(
                phase="synthesis",
                step=4,
                total_steps=4,
                content="Формирую ответ..."
            )
            
            answer = await self._synthesize_answer(question, plan)
            
            # Стримим финальный ответ
            yield SSESerializer.text_delta(answer)
            
            logger.info(f"[AutonomousAgent] Completed successfully (FULL PATH)")
            
        except Exception as e:
            logger.error(f"[AutonomousAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки: {str(e)}")
    
    # =========================================================================
    # ФАЗА 1: ПОНИМАНИЕ
    # =========================================================================
    
    async def _understand_request(self, question: str) -> Dict[str, Any]:
        """
        Глубокое понимание запроса пользователя.
        
        Определяет:
        - Что именно хочет пользователь
        - Какой тип задачи (вопрос, анализ, сравнение, генерация)
        - Какие данные нужны
        - Какой формат ответа ожидается
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем контекст о деле
        case_context = await self._get_case_context()
        
        prompt = f"""Проанализируй запрос пользователя и определи:

ЗАПРОС: {question}

КОНТЕКСТ ДЕЛА:
{case_context}

ИСТОРИЯ ЧАТА (последние сообщения):
{self._format_chat_history()}

Ответь в JSON формате:
{{
    "summary": "Краткое описание что хочет пользователь (1 предложение)",
    "task_type": "question|analysis|comparison|generation|search|overview",
    "requires_all_documents": true/false,
    "requires_legal_research": true/false,
    "requires_web_search": true/false,
    "key_entities": ["сущности которые нужно найти"],
    "expected_output_format": "описание ожидаемого формата ответа",
    "complexity": "simple|moderate|complex",
    "reasoning": "почему такая оценка сложности"
}}

Отвечай ТОЛЬКО JSON, без markdown."""

        response = self.llm.invoke([
            SystemMessage(content="Ты эксперт по анализу юридических запросов. Отвечай только в JSON формате."),
            HumanMessage(content=prompt)
        ])
        
        try:
            # Парсим JSON
            content = response.content if hasattr(response, 'content') else str(response)
            # Убираем возможные markdown-обёртки
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            understanding = json.loads(content)
            logger.info(f"[AutonomousAgent] Understanding: {understanding.get('summary', 'N/A')}")
            return understanding
            
        except json.JSONDecodeError as e:
            logger.warning(f"[AutonomousAgent] Failed to parse understanding: {e}")
            # Fallback
            return {
                "summary": question[:100],
                "task_type": "question",
                "requires_all_documents": False,
                "requires_legal_research": self.legal_research,
                "requires_web_search": self.web_search,
                "key_entities": [],
                "expected_output_format": "текстовый ответ",
                "complexity": "moderate",
                "reasoning": "не удалось определить"
            }
    
    async def _get_case_context(self) -> str:
        """Получить контекст о деле (список документов)"""
        try:
            from app.models.case import File as FileModel, Case
            
            # Информация о деле
            case = self.db.query(Case).filter(Case.id == self.case_id).first()
            case_info = f"Дело: {case.name if case else 'Неизвестно'}\n"
            
            # Список файлов
            files = self.db.query(FileModel).filter(
                FileModel.case_id == self.case_id
            ).all()
            
            if files:
                case_info += f"Документов: {len(files)}\n"
                case_info += "Файлы:\n"
                for f in files[:10]:  # Первые 10
                    case_info += f"- {f.filename} ({f.file_type or 'unknown'})\n"
                if len(files) > 10:
                    case_info += f"... и ещё {len(files) - 10} файлов\n"
            else:
                case_info += "Документов: 0\n"
            
            return case_info
            
        except Exception as e:
            logger.warning(f"[AutonomousAgent] Failed to get case context: {e}")
            return "Контекст дела недоступен"
    
    def _format_chat_history(self) -> str:
        """Форматировать историю чата"""
        if not self.chat_history:
            return "История пуста"
        
        formatted = []
        for msg in self.chat_history[-5:]:  # Последние 5
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            formatted.append(f"{role}: {content}")
        
        return "\n".join(formatted)
    
    # =========================================================================
    # ФАЗА 2: ПЛАНИРОВАНИЕ
    # =========================================================================
    
    async def _create_plan(self, question: str, understanding: Dict[str, Any]) -> ExecutionPlan:
        """
        Создать план выполнения под КОНКРЕТНУЮ задачу.
        
        План создаётся динамически, не из готовых шаблонов.
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Определяем доступные возможности
        capabilities = self._get_available_capabilities()
        
        prompt = f"""Создай план выполнения задачи.

ЗАДАЧА: {question}

ПОНИМАНИЕ ЗАДАЧИ:
{json.dumps(understanding, ensure_ascii=False, indent=2)}

ДОСТУПНЫЕ ВОЗМОЖНОСТИ:
{capabilities}

ПРАВИЛА ПЛАНИРОВАНИЯ:
1. Каждый шаг должен быть КОНКРЕТНЫМ и ВЫПОЛНИМЫМ
2. Шаги могут зависеть друг от друга (depends_on)
3. Используй минимум шагов для решения задачи
4. Для обзорных вопросов ОБЯЗАТЕЛЬНО включи работу со ВСЕМИ документами
5. Если нужно сравнение — сначала собери данные, потом сравнивай

Ответь в JSON формате:
{{
    "steps": [
        {{
            "step_id": 1,
            "step_type": "search|summarize|extract|analyze|compare|generate|legal_research|web_search|custom",
            "description": "Что делает этот шаг",
            "instruction": "Детальная инструкция для выполнения",
            "query": "поисковый запрос если нужен",
            "depends_on": [],
            "params": {{}}
        }}
    ],
    "expected_output": "описание ожидаемого результата"
}}

Отвечай ТОЛЬКО JSON."""

        response = self.llm.invoke([
            SystemMessage(content="Ты эксперт по планированию юридических задач. Создавай оптимальные планы."),
            HumanMessage(content=prompt)
        ])
        
        try:
            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            plan_data = json.loads(content)
            
            # Создаём объекты шагов
            steps = []
            for step_data in plan_data.get("steps", []):
                step = PlanStep(
                    step_id=step_data.get("step_id", len(steps) + 1),
                    step_type=StepType(step_data.get("step_type", "custom")),
                    description=step_data.get("description", ""),
                    instruction=step_data.get("instruction", ""),
                    query=step_data.get("query"),
                    depends_on=step_data.get("depends_on", []),
                    params=step_data.get("params", {})
                )
                steps.append(step)
            
            # Определяем сложность
            complexity = TaskComplexity(understanding.get("complexity", "moderate"))
            
            plan = ExecutionPlan(
                task_understanding=understanding.get("summary", ""),
                complexity=complexity,
                steps=steps,
                expected_output=plan_data.get("expected_output", "")
            )
            
            logger.info(f"[AutonomousAgent] Created plan with {len(steps)} steps")
            return plan
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[AutonomousAgent] Failed to parse plan: {e}, using fallback")
            return self._create_fallback_plan(question, understanding)
    
    def _get_available_capabilities(self) -> str:
        """Получить описание доступных возможностей"""
        caps = """
1. SEARCH (search) — Поиск в документах дела
   - Может искать по ключевым словам, фразам, темам
   - Параметр k: количество результатов (5-100)

2. SUMMARIZE (summarize) — Суммаризация
   - Может суммаризировать один документ или все документы
   - Параметр: all_documents=true для Map-Reduce по всем

3. EXTRACT (extract) — Извлечение сущностей
   - Даты, суммы, имена, организации
   - Параметр: entity_types (dates, amounts, persons, organizations)

4. ANALYZE (analyze) — Анализ
   - Риски, противоречия, сильные/слабые стороны
   - Параметр: analysis_type (risks, contradictions, strengths, weaknesses)

5. COMPARE (compare) — Сравнение
   - Сравнение документов, позиций, условий
   - Параметр: compare_what (documents, positions, conditions)

6. GENERATE (generate) — Генерация текста
   - Создание текста на основе анализа
   - Параметр: output_type (summary, arguments, recommendations)

7. CUSTOM (custom) — Кастомный запрос
   - Любой запрос к LLM с контекстом из документов
   - Используй когда другие типы не подходят
"""
        
        if self.legal_research:
            caps += """
8. LEGAL_RESEARCH (legal_research) — Поиск в правовых базах (ГАРАНТ)
   - Поиск законов, статей, судебной практики
"""
        
        if self.web_search:
            caps += """
9. WEB_SEARCH (web_search) — Поиск в интернете
   - Актуальная информация, новости, прецеденты
"""
        
        return caps
    
    def _create_fallback_plan(self, question: str, understanding: Dict[str, Any]) -> ExecutionPlan:
        """Создать fallback план"""
        steps = [
            PlanStep(
                step_id=1,
                step_type=StepType.SEARCH,
                description="Поиск релевантной информации",
                instruction="Найти информацию по запросу пользователя",
                query=question,
                params={"k": 20}
            ),
            PlanStep(
                step_id=2,
                step_type=StepType.GENERATE,
                description="Формирование ответа",
                instruction="Сформировать ответ на основе найденной информации",
                depends_on=[1]
            )
        ]
        
        return ExecutionPlan(
            task_understanding=understanding.get("summary", question),
            complexity=TaskComplexity.MODERATE,
            steps=steps,
            expected_output="Ответ на вопрос пользователя"
        )
    
    # =========================================================================
    # ФАЗА 3: ВЫПОЛНЕНИЕ
    # =========================================================================
    
    async def _execute_plan(self, plan: ExecutionPlan) -> AsyncGenerator[str, None]:
        """
        Выполнить план.
        
        Шаги выполняются с учётом зависимостей.
        Результаты кэшируются для использования в следующих шагах.
        """
        total_steps = len(plan.steps)
        
        for i, step in enumerate(plan.steps, 1):
            # Проверяем зависимости
            await self._wait_for_dependencies(step.depends_on)
            
            yield SSESerializer.reasoning(
                phase="execution",
                step=3,
                total_steps=4,
                content=f"Шаг {i}/{total_steps}: {step.description}"
            )
            
            # Выполняем шаг
            result = await self._execute_step(step)
            self.step_results[step.step_id] = result
            
            if not result.success:
                logger.warning(f"[AutonomousAgent] Step {step.step_id} failed: {result.content[:100]}")
    
    async def _wait_for_dependencies(self, depends_on: List[int]):
        """Дождаться выполнения зависимых шагов"""
        for dep_id in depends_on:
            while dep_id not in self.step_results:
                await asyncio.sleep(0.1)
    
    async def _execute_step(self, step: PlanStep) -> StepResult:
        """
        Выполнить один шаг плана.
        
        Динамически выбирает способ выполнения:
        - Готовый инструмент (если подходит)
        - Кастомный LLM-запрос (если нужно)
        """
        try:
            if step.step_type == StepType.SEARCH:
                return await self._execute_search(step)
            elif step.step_type == StepType.SUMMARIZE:
                return await self._execute_summarize(step)
            elif step.step_type == StepType.EXTRACT:
                return await self._execute_extract(step)
            elif step.step_type == StepType.ANALYZE:
                return await self._execute_analyze(step)
            elif step.step_type == StepType.COMPARE:
                return await self._execute_compare(step)
            elif step.step_type == StepType.GENERATE:
                return await self._execute_generate(step)
            elif step.step_type == StepType.LEGAL_RESEARCH:
                return await self._execute_legal_research(step)
            elif step.step_type == StepType.WEB_SEARCH:
                return await self._execute_web_search(step)
            else:  # CUSTOM
                return await self._execute_custom(step)
                
        except Exception as e:
            logger.error(f"[AutonomousAgent] Step {step.step_id} error: {e}")
            return StepResult(
                step_id=step.step_id,
                success=False,
                content=f"Ошибка выполнения: {str(e)}"
            )
    
    async def _execute_search(self, step: PlanStep) -> StepResult:
        """Выполнить поиск в документах"""
        query = step.query or step.instruction
        k = step.params.get("k", 20)
        
        documents = self.rag_service.retrieve_context(
            case_id=self.case_id,
            query=query,
            k=k,
            retrieval_strategy="multi_query",
            db=self.db
        )
        
        if not documents:
            return StepResult(
                step_id=step.step_id,
                success=True,
                content="Документы не найдены"
            )
        
        # Форматируем результаты
        content = self.rag_service.format_sources_for_prompt(documents, max_context_chars=8000)
        sources = list(set(d.metadata.get("source", "unknown") for d in documents))
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=content,
            sources=sources
        )
    
    async def _execute_summarize(self, step: PlanStep) -> StepResult:
        """Выполнить суммаризацию"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        all_documents = step.params.get("all_documents", False)
        
        if all_documents:
            # Map-Reduce по всем документам
            return await self._summarize_all_documents()
        else:
            # Суммаризация контекста из предыдущих шагов
            context = self._get_context_from_dependencies(step.depends_on)
            
            response = self.llm.invoke([
                SystemMessage(content="Ты юридический аналитик. Суммаризируй информацию кратко и по существу."),
                HumanMessage(content=f"Суммаризируй:\n\n{context}\n\nИнструкция: {step.instruction}")
            ])
            
            return StepResult(
                step_id=step.step_id,
                success=True,
                content=response.content if hasattr(response, 'content') else str(response)
            )
    
    async def _summarize_all_documents(self) -> StepResult:
        """Map-Reduce суммаризация всех документов"""
        from app.models.case import File as FileModel
        from langchain_core.messages import HumanMessage, SystemMessage
        
        files = self.db.query(FileModel).filter(
            FileModel.case_id == self.case_id
        ).all()
        
        if not files:
            return StepResult(step_id=0, success=True, content="Документы не найдены")
        
        # MAP: Суммаризируем каждый файл
        summaries = []
        for file in files:
            docs = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=f"содержание {file.filename}",
                k=20,
                db=self.db
            )
            
            if docs:
                content = "\n".join([d.page_content for d in docs[:10]])[:3000]
                
                response = self.llm.invoke([
                    SystemMessage(content="Кратко опиши документ (2-3 предложения)."),
                    HumanMessage(content=f"Документ: {file.filename}\n\n{content}")
                ])
                
                summary = response.content if hasattr(response, 'content') else str(response)
                summaries.append(f"**{file.filename}**: {summary}")
        
        # REDUCE: Объединяем
        combined = "\n\n".join(summaries)
        
        response = self.llm.invoke([
            SystemMessage(content="Составь общий обзор дела на основе описаний документов."),
            HumanMessage(content=f"Описания документов:\n\n{combined}\n\nСоставь структурированный обзор дела.")
        ])
        
        return StepResult(
            step_id=0,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response),
            sources=[f.filename for f in files]
        )
    
    async def _execute_extract(self, step: PlanStep) -> StepResult:
        """Извлечь сущности"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        entity_types = step.params.get("entity_types", ["dates", "amounts", "persons", "organizations"])
        context = self._get_context_from_dependencies(step.depends_on)
        
        if not context:
            # Получаем контекст через поиск
            docs = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=step.query or "ключевые факты даты суммы имена",
                k=50,
                db=self.db
            )
            context = "\n".join([d.page_content for d in docs])[:8000]
        
        prompt = f"""Извлеки из текста следующие сущности: {', '.join(entity_types)}

Текст:
{context}

Инструкция: {step.instruction}

Формат ответа:
📅 ДАТЫ: ...
💰 СУММЫ: ...
👤 ЛИЦА: ...
🏢 ОРГАНИЗАЦИИ: ..."""

        response = self.llm.invoke([
            SystemMessage(content="Ты извлекаешь структурированную информацию из юридических документов."),
            HumanMessage(content=prompt)
        ])
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response)
        )
    
    async def _execute_analyze(self, step: PlanStep) -> StepResult:
        """Выполнить анализ"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        analysis_type = step.params.get("analysis_type", "general")
        context = self._get_context_from_dependencies(step.depends_on)
        
        if not context:
            docs = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=step.query or step.instruction,
                k=50,
                db=self.db
            )
            context = "\n".join([d.page_content for d in docs])[:8000]
        
        prompt = f"""Проведи анализ типа: {analysis_type}

Контекст:
{context}

Инструкция: {step.instruction}

Дай структурированный анализ."""

        response = self.llm.invoke([
            SystemMessage(content="Ты юридический аналитик. Проводишь глубокий анализ."),
            HumanMessage(content=prompt)
        ])
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response)
        )
    
    async def _execute_compare(self, step: PlanStep) -> StepResult:
        """Выполнить сравнение"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        context = self._get_context_from_dependencies(step.depends_on)
        
        if not context:
            docs = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=step.query or step.instruction,
                k=50,
                db=self.db
            )
            context = "\n".join([d.page_content for d in docs])[:8000]
        
        prompt = f"""Проведи сравнительный анализ.

Контекст:
{context}

Инструкция: {step.instruction}

Представь результат в виде таблицы или структурированного сравнения."""

        response = self.llm.invoke([
            SystemMessage(content="Ты эксперт по сравнительному анализу юридических документов."),
            HumanMessage(content=prompt)
        ])
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response)
        )
    
    async def _execute_generate(self, step: PlanStep) -> StepResult:
        """Сгенерировать текст"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        context = self._get_context_from_dependencies(step.depends_on)
        output_type = step.params.get("output_type", "text")
        
        prompt = f"""Сгенерируй текст типа: {output_type}

Контекст и данные:
{context}

Инструкция: {step.instruction}"""

        response = self.llm.invoke([
            SystemMessage(content="Ты юридический писатель. Создаёшь качественные тексты."),
            HumanMessage(content=prompt)
        ])
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response)
        )
    
    async def _execute_legal_research(self, step: PlanStep) -> StepResult:
        """Поиск в правовых базах (ГАРАНТ)"""
        if not self.legal_research:
            return StepResult(
                step_id=step.step_id,
                success=False,
                content="Поиск в ГАРАНТ отключён пользователем"
            )
        
        try:
            from app.services.langchain_agents.garant_tools import search_garant
            
            query = step.query or step.instruction
            result = search_garant.invoke({"query": query})
            
            return StepResult(
                step_id=step.step_id,
                success=True,
                content=result,
                sources=["ГАРАНТ"]
            )
        except Exception as e:
            logger.warning(f"[AutonomousAgent] GARANT search failed: {e}")
            return StepResult(
                step_id=step.step_id,
                success=False,
                content=f"Ошибка поиска в ГАРАНТ: {str(e)}"
            )
    
    async def _execute_web_search(self, step: PlanStep) -> StepResult:
        """Веб-поиск"""
        if not self.web_search:
            return StepResult(
                step_id=step.step_id,
                success=False,
                content="Веб-поиск отключён пользователем"
            )
        
        try:
            from app.services.langchain_agents.web_research_tool import web_research_tool
            
            query = step.query or step.instruction
            result = web_research_tool.invoke({"query": query})
            
            return StepResult(
                step_id=step.step_id,
                success=True,
                content=result,
                sources=["Web"]
            )
        except Exception as e:
            logger.warning(f"[AutonomousAgent] Web search failed: {e}")
            return StepResult(
                step_id=step.step_id,
                success=False,
                content=f"Ошибка веб-поиска: {str(e)}"
            )
    
    async def _execute_custom(self, step: PlanStep) -> StepResult:
        """Кастомный LLM-запрос"""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        context = self._get_context_from_dependencies(step.depends_on)
        
        if not context and step.query:
            docs = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=step.query,
                k=30,
                db=self.db
            )
            context = "\n".join([d.page_content for d in docs])[:6000]
        
        prompt = f"""Выполни задачу:

{step.instruction}

Контекст:
{context if context else 'Контекст не предоставлен'}"""

        response = self.llm.invoke([
            SystemMessage(content="Ты универсальный юридический ассистент. Выполняй задачи качественно."),
            HumanMessage(content=prompt)
        ])
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            content=response.content if hasattr(response, 'content') else str(response)
        )
    
    def _get_context_from_dependencies(self, depends_on: List[int]) -> str:
        """Получить контекст из результатов зависимых шагов"""
        if not depends_on:
            return ""
        
        contexts = []
        for dep_id in depends_on:
            if dep_id in self.step_results:
                result = self.step_results[dep_id]
                if result.success and result.content:
                    contexts.append(result.content)
        
        return "\n\n---\n\n".join(contexts)
    
    # =========================================================================
    # ФАЗА 4: СИНТЕЗ
    # =========================================================================
    
    async def _synthesize_answer(self, question: str, plan: ExecutionPlan) -> str:
        """
        Синтезировать финальный ответ из результатов всех шагов.
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Собираем все результаты
        all_results = []
        all_sources = set()
        
        for step_id, result in self.step_results.items():
            if result.success and result.content:
                all_results.append(f"### Результат шага {step_id}:\n{result.content}")
                all_sources.update(result.sources)
        
        combined_results = "\n\n".join(all_results)
        
        prompt = f"""Синтезируй финальный ответ на вопрос пользователя.

ВОПРОС: {question}

ПОНИМАНИЕ ЗАДАЧИ: {plan.task_understanding}

ОЖИДАЕМЫЙ ФОРМАТ: {plan.expected_output}

РЕЗУЛЬТАТЫ АНАЛИЗА:
{combined_results}

ПРАВИЛА:
1. Ответ должен быть ПОЛНЫМ и СТРУКТУРИРОВАННЫМ
2. Используй Markdown для форматирования
3. Укажи источники информации
4. Если были противоречия или неопределённости — отметь их
5. Дай конкретные выводы и рекомендации если уместно

ИСТОЧНИКИ: {', '.join(all_sources) if all_sources else 'документы дела'}

Финальный ответ:"""

        response = self.llm.invoke([
            SystemMessage(content="Ты юридический эксперт. Даёшь качественные, структурированные ответы."),
            HumanMessage(content=prompt)
        ])
        
        answer = response.content if hasattr(response, 'content') else str(response)
        
        # Добавляем источники если есть
        if all_sources:
            answer += f"\n\n---\n📚 *Источники: {', '.join(all_sources)}*"
        
        return answer

