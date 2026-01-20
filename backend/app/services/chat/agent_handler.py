"""
Agent Handler - Обработчик агентных задач

Отвечает за:
- Выполнение сложных задач через агентов
- Планирование анализа
- Координация multi-agent workflow
- Human-in-the-loop feedback
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging
import uuid

from app.services.chat.events import (
    SSESerializer,
    PlanApprovalEvent,
    HumanFeedbackEvent,
    AgentProgressEvent,
    AgentCompleteEvent,
    PlanInfo,
    PlanStep,
    FeedbackOption,
)
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)


class AgentHandler:
    """
    Обработчик агентных задач.
    
    Выполняет:
    1. Планирование через PlanningAgent/AdvancedPlanningAgent
    2. Запрос одобрения плана у пользователя
    3. Выполнение плана через координатор
    4. Human feedback при необходимости
    """
    
    def __init__(
        self,
        rag_service: RAGService,
        db: Session
    ):
        """
        Инициализация обработчика
        
        Args:
            rag_service: RAG сервис
            db: SQLAlchemy сессия
        """
        self.rag_service = rag_service
        self.db = db
    
    async def handle(
        self,
        case_id: str,
        question: str,
        current_user: User,
        auto_approve: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Обработать агентную задачу
        
        Args:
            case_id: ID дела
            question: Задача пользователя
            current_user: Текущий пользователь
            auto_approve: Автоматически одобрять план
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[AgentHandler] Processing task for case {case_id}: {question[:100]}…")
            
            # 1. Создание плана через PlanningAgent
            yield SSESerializer.text_delta("🔍 Анализирую задачу и создаю план…\n\n")
            
            plan = await self._create_plan(case_id, question, current_user)
            
            if not plan:
                yield SSESerializer.error("Не удалось создать план анализа")
                return
            
            # 2. Отправляем план на одобрение (если не auto_approve)
            if not auto_approve:
                yield PlanApprovalEvent(plan=plan).to_sse()
                yield SSESerializer.text_delta(f"\n📋 **План анализа готов**\n\nОжидаю подтверждения для выполнения.\n")
                return  # Ждём подтверждения через отдельный endpoint
            
            # 3. Выполняем план
            async for event in self._execute_plan(case_id, plan, current_user):
                yield event
                
        except Exception as e:
            logger.error(f"[AgentHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка при выполнении задачи: {str(e)}")
    
    async def _create_plan(
        self,
        case_id: str,
        question: str,
        current_user: User
    ) -> Optional[PlanInfo]:
        """
        Создать план анализа через PlanningAgent
        
        Returns:
            PlanInfo или None
        """
        try:
            from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
            
            planning_agent = AdvancedPlanningAgent(
                case_id=case_id,
                rag_service=self.rag_service,
                db=self.db
            )
            
            # Получаем план
            plan_result = await planning_agent.create_plan(question)
            
            if not plan_result:
                logger.warning("[AgentHandler] Planning agent returned no result")
                return None
            
            # Преобразуем в PlanInfo
            plan_id = str(uuid.uuid4())
            
            steps = []
            if plan_result.get("steps"):
                for i, step in enumerate(plan_result["steps"]):
                    steps.append(PlanStep(
                        description=step.get("description", f"Шаг {i+1}"),
                        agent_name=step.get("agent"),
                        estimated_time=step.get("estimated_time")
                    ))
            
            return PlanInfo(
                plan_id=plan_id,
                reasoning=plan_result.get("reasoning"),
                analysis_types=plan_result.get("analysis_types", []),
                confidence=plan_result.get("confidence"),
                goals=plan_result.get("goals"),
                steps=steps,
                strategy=plan_result.get("strategy")
            )
            
        except Exception as e:
            logger.error(f"[AgentHandler] Planning error: {e}", exc_info=True)
            return None
    
    async def _execute_plan(
        self,
        case_id: str,
        plan: PlanInfo,
        current_user: User
    ) -> AsyncGenerator[str, None]:
        """
        Выполнить план анализа
        
        Yields:
            SSE события прогресса и результатов
        """
        try:
            # Используем упрощённый координатор
            from app.services.langchain_agents.simplified_coordinator import SimplifiedAgentCoordinator
            
            yield SSESerializer.text_delta("⚙️ **Выполняю план анализа…**\n\n")
            
            # Создаём упрощённый координатор
            coordinator = SimplifiedAgentCoordinator(
                db=self.db,
                rag_service=self.rag_service,
            )
            
            # Выполняем анализ через stream
            total_steps = len(plan.steps) if plan.steps else len(plan.analysis_types or [])
            current_step = 0
            
            async for event in coordinator.stream_analysis(
                case_id=case_id,
                analysis_types=plan.analysis_types or [],
            ):
                event_type = event.get("type")
                
                if event_type == "start":
                    # Событие старта анализа
                    agents = event.get("agents", [])
                    yield SSESerializer.text_delta(f"🚀 Запускаю анализ: {', '.join(agents)}\n\n")
                
                elif event_type == "agent_complete":
                    agent_name = event.get("agent", "unknown")
                    result_preview = event.get("result_preview", {})
                    current_step += 1
                    progress = current_step / max(total_steps, 1)
                    
                    yield AgentProgressEvent(
                        agent_name=agent_name,
                        step=f"Завершён {agent_name}",
                        progress=progress,
                        message=f"Шаг {current_step} из {total_steps}"
                    ).to_sse()
                    
                    # Форматируем preview
                    preview_text = result_preview.get("preview", f"Выполнено: {agent_name}")
                    yield SSESerializer.text_delta(f"✅ **{agent_name}**: {preview_text}\n")
                
                elif event_type == "complete":
                    # Финальное событие
                    execution_time = event.get("execution_time", 0)
                    completed_agents = event.get("completed_agents", [])
                    
                    yield SSESerializer.text_delta(
                        f"\n\n✅ **Анализ завершён** за {execution_time:.1f}с\n"
                        f"Выполнено агентов: {len(completed_agents)}\n"
                    )
                    
                    # Получаем финальные результаты
                    final_state = event.get("final_state", {})
                    if final_state:
                        for agent in completed_agents:
                            result_key = f"{agent}_result"
                            if agent == "document_classifier":
                                result_key = "classification_result"
                            elif agent == "entity_extraction":
                                result_key = "entities_result"
                            
                            result = final_state.get(result_key)
                            if result:
                                summary = self._format_agent_result(agent, result)
                                yield SSESerializer.text_delta(f"\n{summary}\n")
                
                elif event_type == "error":
                    error_msg = event.get("message", "Unknown error")
                    yield SSESerializer.error(f"Ошибка: {error_msg}")
                
                elif event_type == "token":
                    # Streaming токенов от LLM
                    content = event.get("content", "")
                    if content:
                        yield SSESerializer.text_delta(content)
            
            yield SSESerializer.text_delta("\n\n✅ **Анализ завершён**\n")
            
        except Exception as e:
            logger.error(f"[AgentHandler] Execution error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка выполнения: {str(e)}")
    
    def _format_agent_result(self, agent_name: str, result: Dict[str, Any]) -> str:
        """Форматировать результат агента для отображения"""
        
        formatters = {
            "timeline": self._format_timeline,
            "key_facts": self._format_key_facts,
            "risk": self._format_risks,
            "discrepancy": self._format_discrepancies,
            "summary": self._format_summary,
            "entity_extraction": self._format_entities,
        }
        
        formatter = formatters.get(agent_name)
        if formatter:
            try:
                return formatter(result)
            except Exception as e:
                logger.warning(f"[AgentHandler] Format error for {agent_name}: {e}")
        
        # Default formatting
        if isinstance(result, dict):
            items = result.get("items", result.get("results", []))
            if items:
                return f"✅ **{agent_name}**: найдено {len(items)} элементов"
        
        return f"✅ **{agent_name}**: выполнено"
    
    def _format_timeline(self, result: Dict) -> str:
        events = result.get("events", result.get("items", []))
        if not events:
            return "📅 **Хронология**: событий не найдено"
        
        lines = ["📅 **Хронология событий:**"]
        for event in events[:5]:  # Первые 5
            date = event.get("date", "?")
            desc = event.get("description", event.get("event", ""))[:100]
            lines.append(f"  • {date}: {desc}")
        
        if len(events) > 5:
            lines.append(f"  … и ещё {len(events) - 5} событий")
        
        return "\n".join(lines)
    
    def _format_key_facts(self, result: Dict) -> str:
        facts = result.get("facts", result.get("items", []))
        if not facts:
            return "📌 **Ключевые факты**: не найдено"
        
        lines = ["📌 **Ключевые факты:**"]
        for fact in facts[:5]:
            text = fact.get("fact", fact.get("text", str(fact)))[:100]
            lines.append(f"  • {text}")
        
        if len(facts) > 5:
            lines.append(f"  … и ещё {len(facts) - 5} фактов")
        
        return "\n".join(lines)
    
    def _format_risks(self, result: Dict) -> str:
        risks = result.get("risks", result.get("items", []))
        if not risks:
            return "⚠️ **Риски**: не выявлено"
        
        lines = ["⚠️ **Выявленные риски:**"]
        for risk in risks[:5]:
            desc = risk.get("description", risk.get("risk", str(risk)))[:100]
            severity = risk.get("severity", "")
            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity.lower(), "⚪")
            lines.append(f"  {severity_emoji} {desc}")
        
        if len(risks) > 5:
            lines.append(f"  … и ещё {len(risks) - 5} рисков")
        
        return "\n".join(lines)
    
    def _format_discrepancies(self, result: Dict) -> str:
        items = result.get("discrepancies", result.get("items", []))
        if not items:
            return "🔍 **Противоречия**: не найдено"
        
        lines = ["🔍 **Найденные противоречия:**"]
        for item in items[:5]:
            desc = item.get("description", str(item))[:100]
            lines.append(f"  • {desc}")
        
        if len(items) > 5:
            lines.append(f"  … и ещё {len(items) - 5} противоречий")
        
        return "\n".join(lines)
    
    def _format_summary(self, result: Dict) -> str:
        summary = result.get("summary", result.get("text", ""))
        if not summary:
            return "📝 **Резюме**: не сформировано"
        
        # Обрезаем если слишком длинное
        if len(summary) > 500:
            summary = summary[:500] + "…"
        
        return f"📝 **Резюме:**\n{summary}"
    
    def _format_entities(self, result: Dict) -> str:
        entities = result.get("entities", result.get("items", []))
        if not entities:
            return "🏷️ **Сущности**: не найдено"
        
        # Группируем по типу
        by_type: Dict[str, List] = {}
        for entity in entities:
            etype = entity.get("type", "other")
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append(entity.get("value", entity.get("text", str(entity))))
        
        lines = ["🏷️ **Извлечённые сущности:**"]
        type_names = {
            "person": "👤 Лица",
            "organization": "🏢 Организации",
            "date": "📅 Даты",
            "money": "💰 Суммы",
            "location": "📍 Места"
        }
        
        for etype, values in by_type.items():
            name = type_names.get(etype, etype.title())
            lines.append(f"  {name}: {', '.join(values[:3])}")
            if len(values) > 3:
                lines[-1] += f" (+{len(values) - 3})"
        
        return "\n".join(lines)
    
    async def handle_plan_approval(
        self,
        case_id: str,
        plan_id: str,
        approved: bool,
        modifications: Optional[str] = None,
        current_user: User = None
    ) -> AsyncGenerator[str, None]:
        """
        Обработать одобрение/отклонение плана
        
        Args:
            case_id: ID дела
            plan_id: ID плана
            approved: Одобрен ли план
            modifications: Модификации от пользователя
            current_user: Текущий пользователь
            
        Yields:
            SSE события
        """
        if not approved:
            yield SSESerializer.text_delta("❌ План отклонён. Вы можете сформулировать задачу иначе.\n")
            return
        
        # TODO: Загрузить план из хранилища по plan_id
        # Пока создаём заглушку
        yield SSESerializer.text_delta("✅ План одобрен. Начинаю выполнение…\n\n")
        
        # Если есть модификации, нужно пересоздать план
        if modifications:
            yield SSESerializer.text_delta(f"📝 Учитываю ваши изменения: {modifications[:100]}…\n\n")
        
        # Выполняем план
        # async for event in self._execute_plan(case_id, plan, current_user):
        #     yield event
        
        yield SSESerializer.text_delta("⚙️ Выполнение плана… (требуется интеграция с хранилищем планов)\n")
    
    async def handle_human_feedback(
        self,
        case_id: str,
        request_id: str,
        response: str,
        current_user: User
    ) -> AsyncGenerator[str, None]:
        """
        Обработать ответ пользователя на запрос feedback
        
        Args:
            case_id: ID дела
            request_id: ID запроса feedback
            response: Ответ пользователя
            current_user: Текущий пользователь
            
        Yields:
            SSE события
        """
        yield SSESerializer.text_delta(f"📩 Получен ваш ответ. Продолжаю выполнение…\n\n")
        
        # TODO: Возобновить выполнение графа с полученным feedback
        # Это требует интеграции с LangGraph checkpointer
        
        yield SSESerializer.text_delta("⚙️ Возобновление выполнения… (требуется интеграция с checkpointer)\n")

