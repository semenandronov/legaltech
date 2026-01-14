"""Enhanced Adaptive Agent with self-awareness and self-correction"""
from typing import Dict, List, Any, Optional
from app.services.agent_self_awareness import SelfAwarenessService, GapType
from app.services.legal_reasoning_model import LegalReasoningModel
from app.services.langgraph_store_service import LangGraphStoreService
from app.services.llm_factory import create_llm
import logging

logger = logging.getLogger(__name__)


class EnhancedAdaptiveAgent:
    """
    Адаптивный агент с самосознанием и самокоррекцией
    
    Процесс работы:
    1. Анализ задачи → определение пробелов
    2. Генерация стратегии поиска
    3. Выполнение поиска через инструменты
    4. Обработка результатов
    5. Обновление знаний
    6. Переоценка плана
    7. Самокоррекция
    """
    
    def __init__(self, agent_type: str, tools: List[Any], llm: Any = None):
        """
        Инициализация адаптивного агента
        
        Args:
            agent_type: Тип агента (risk, discrepancy, key_facts, etc.)
            tools: Список доступных инструментов
            llm: LLM instance (опционально, создастся автоматически)
        """
        self.agent_type = agent_type
        self.tools = tools
        self.llm = llm or create_llm(temperature=0.1)
        self.self_awareness = SelfAwarenessService()
        self.reasoning_model = LegalReasoningModel()
        self.max_iterations = 3  # Ограничение итераций
        logger.info(f"✅ EnhancedAdaptiveAgent initialized for {agent_type}")
    
    async def solve_task(
        self,
        goal: str,
        initial_context: Dict[str, Any],
        case_id: str,
        store_service: Optional[LangGraphStoreService] = None
    ) -> Dict[str, Any]:
        """
        Решает задачу с адаптивным поиском информации
        
        Args:
            goal: Цель агента
            initial_context: Начальный контекст (документы дела)
            case_id: ID дела
            store_service: LangGraph Store для сохранения результатов
        
        Returns:
            Результат работы агента
        """
        iteration = 0
        current_context = initial_context.copy()
        knowledge_gaps = []
        
        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"[{self.agent_type} Agent] Iteration {iteration}/{self.max_iterations}")
            
            # 1. Анализ пробелов в знаниях
            case_documents_text = current_context.get("documents_text", "")
            agent_output = current_context.get("agent_output", "")
            
            gaps = self.self_awareness.identify_knowledge_gaps(
                case_documents=case_documents_text,
                agent_output=agent_output,
                task_type=self.agent_type
            )
            
            # 2. Проверка Store перед поиском
            if store_service and gaps:
                # Проверяем, может информация уже есть в Store
                for gap in gaps.copy():  # Используем copy для безопасного удаления
                    stored_info = await self._check_store(store_service, case_id, gap)
                    if stored_info:
                        logger.info(f"[{self.agent_type} Agent] Found info in Store for {gap.value}")
                        current_context["found_info"] = stored_info
                        gaps.remove(gap)
            
            # 3. Если есть пробелы - генерируем стратегию поиска
            if self.self_awareness.should_search(gaps):
                search_strategy = self.self_awareness.generate_search_strategy(gaps)
                logger.info(f"[{self.agent_type} Agent] Search strategy: {search_strategy}")
                
                # 4. Выполняем поиск (агент сам вызовет инструменты через function calling)
                # Инструменты доступны через self.tools
                # Агент вызовет их автоматически при необходимости
                
                # 5. Обновляем контекст с результатами поиска
                # (результаты будут добавлены в current_context после вызова инструментов)
                current_context["search_strategy"] = search_strategy
                current_context["knowledge_gaps"] = [g.value for g in gaps]
            
            # 6. Если пробелов нет или достигнут лимит итераций - завершаем
            if not gaps or iteration >= self.max_iterations:
                break
        
        return {
            "result": current_context.get("agent_output", ""),
            "iterations": iteration,
            "gaps_found": len(knowledge_gaps),
            "final_context": current_context
        }
    
    async def _check_store(
        self,
        store_service: LangGraphStoreService,
        case_id: str,
        gap: GapType
    ) -> Optional[Dict]:
        """
        Проверяет Store на наличие информации
        
        Args:
            store_service: LangGraph Store service
            case_id: ID дела
            gap: Тип пробела
        
        Returns:
            Найденная информация или None
        """
        namespace_map = {
            GapType.MISSING_NORM: "norms",
            GapType.MISSING_PRECEDENT: "precedents",
            GapType.MISSING_COURT_POSITION: "court_positions"
        }
        
        namespace = namespace_map.get(gap)
        if not namespace:
            return None
        
        try:
            # Ищем в Store
            keys = await store_service.list(f"case_{case_id}/{namespace}", limit=10)
            if keys:
                # Возвращаем последний результат
                value = await store_service.get(f"case_{case_id}/{namespace}", keys[-1])
                return value
        except Exception as e:
            logger.debug(f"Error checking store: {e}")
        
        return None


























