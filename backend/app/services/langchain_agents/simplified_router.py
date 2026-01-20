"""
Упрощённый Rule-based Router для юридического анализа.

Заменяет сложную логику supervisor.py на простые правила:
- 95% запросов обрабатываются без LLM
- Только сложные случаи используют LLM для классификации
- Детерминированное поведение
- Легко тестировать и отлаживать
"""
from typing import Optional, Set, Dict, Any
from dataclasses import dataclass
import logging
import re

from app.services.langchain_agents.state import AnalysisState

logger = logging.getLogger(__name__)


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# Основные агенты
CORE_AGENTS = {
    "document_classifier",
    "entity_extraction",
    "timeline",
    "key_facts",
    "discrepancy",
    "summary",
}

# Опциональные агенты (включаются по явному запросу)
OPTIONAL_AGENTS = {
    "risk",
    "relationship",
    "privilege_check",
}

# Все поддерживаемые агенты
ALL_AGENTS = CORE_AGENTS | OPTIONAL_AGENTS

# Зависимости
DEPENDENCIES = {
    "summary": {"key_facts"},
    "risk": {"discrepancy"},
    "relationship": {"entity_extraction"},
}

# Порядок выполнения (приоритет)
EXECUTION_PRIORITY = [
    "document_classifier",  # 1. Классификация
    "entity_extraction",    # 2. Сущности
    "timeline",             # 3. Хронология
    "key_facts",            # 4. Факты
    "discrepancy",          # 5. Противоречия
    "risk",                 # 6. Риски (если запрошено)
    "relationship",         # 7. Связи (если запрошено)
    "privilege_check",      # 8. Привилегии (если запрошено)
    "summary",              # 9. Резюме (последний)
]


# =============================================================================
# КЛАССИФИКАЦИЯ ЗАПРОСОВ
# =============================================================================

@dataclass
class ClassificationResult:
    """Результат классификации запроса."""
    is_task: bool  # True = агентная задача, False = RAG вопрос
    confidence: float
    reason: str
    suggested_agents: Set[str]


# Паттерны для RAG (вопросы)
RAG_PATTERNS = [
    # Запросы статей кодексов
    r"статья\s+\d+",
    r"ст\.\s*\d+",
    r"пришли\s+статью",
    r"покажи\s+статью",
    r"текст\s+статьи",
    
    # Приветствия
    r"^привет",
    r"^здравствуй",
    r"^добрый\s+(день|вечер|утро)",
    
    # Вопросительные слова (простые вопросы)
    r"^что\s+такое",
    r"^как\s+понять",
    r"^объясни",
    r"^расскажи\s+о",
]

# Паттерны для агентных задач
AGENT_PATTERNS = {
    "timeline": [
        r"извлеки?\s+(все\s+)?даты",
        r"хронологи[яю]",
        r"timeline",
        r"временн[аую][яю]\s+лини[яю]",
        r"последовательность\s+событий",
    ],
    "key_facts": [
        r"ключевые\s+факты",
        r"основные\s+факты",
        r"важные\s+факты",
        r"выдели\s+факты",
        r"key\s*facts",
    ],
    "discrepancy": [
        r"противоречи[яе]",
        r"несоответстви[яе]",
        r"расхождени[яе]",
        r"найди\s+противоречия",
        r"discrepancy",
    ],
    "entity_extraction": [
        r"извлеки?\s+сущности",
        r"найди\s+(все\s+)?(имена|организации|суммы)",
        r"entities",
        r"сущности",
    ],
    "document_classifier": [
        r"классифицир",
        r"тип[ыа]?\s+документ",
        r"какие\s+документы",
        r"categorize",
    ],
    "summary": [
        r"резюме",
        r"краткое\s+содержание",
        r"summary",
        r"сводка",
        r"подведи\s+итог",
    ],
    "risk": [
        r"риск[иа]",
        r"анализ\s+рисков",
        r"risk\s+analysis",
        r"оцени\s+риски",
    ],
    "relationship": [
        r"связи\s+между",
        r"граф\s+связей",
        r"relationship",
        r"взаимосвязи",
    ],
}

# Комплексные паттерны (несколько агентов)
COMPLEX_PATTERNS = [
    (r"полный\s+анализ", {"document_classifier", "entity_extraction", "timeline", "key_facts", "discrepancy", "summary"}),
    (r"проанализируй\s+(все|полностью|документы)", {"document_classifier", "entity_extraction", "timeline", "key_facts", "discrepancy", "summary"}),
    (r"составь\s+таблицу", {"entity_extraction", "timeline", "key_facts"}),
]


def classify_request(question: str) -> ClassificationResult:
    """
    Классифицировать запрос пользователя.
    
    Args:
        question: Текст запроса
    
    Returns:
        ClassificationResult с результатом классификации
    """
    question_lower = question.lower().strip()
    
    # 1. Проверяем RAG паттерны (быстрый выход)
    for pattern in RAG_PATTERNS:
        if re.search(pattern, question_lower):
            return ClassificationResult(
                is_task=False,
                confidence=0.95,
                reason=f"Matches RAG pattern: {pattern}",
                suggested_agents=set(),
            )
    
    # 2. Проверяем комплексные паттерны
    for pattern, agents in COMPLEX_PATTERNS:
        if re.search(pattern, question_lower):
            return ClassificationResult(
                is_task=True,
                confidence=0.9,
                reason=f"Matches complex pattern: {pattern}",
                suggested_agents=agents,
            )
    
    # 3. Проверяем агентные паттерны
    matched_agents = set()
    for agent, patterns in AGENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                matched_agents.add(agent)
                break
    
    if matched_agents:
        return ClassificationResult(
            is_task=True,
            confidence=0.85,
            reason=f"Matches agent patterns for: {matched_agents}",
            suggested_agents=matched_agents,
        )
    
    # 4. Fallback: если ничего не совпало, это вопрос
    return ClassificationResult(
        is_task=False,
        confidence=0.6,
        reason="No patterns matched, defaulting to RAG",
        suggested_agents=set(),
    )


# =============================================================================
# ROUTER
# =============================================================================

class SimplifiedRouter:
    """
    Упрощённый роутер для агентного графа.
    
    Определяет следующий агент на основе:
    1. Запрошенных типов анализа
    2. Уже выполненных агентов
    3. Зависимостей между агентами
    4. Приоритета выполнения
    """
    
    def __init__(self):
        self._result_keys = {
            "document_classifier": "classification_result",
            "entity_extraction": "entities_result",
            "timeline": "timeline_result",
            "key_facts": "key_facts_result",
            "discrepancy": "discrepancy_result",
            "summary": "summary_result",
            "risk": "risk_result",
            "relationship": "relationship_result",
            "privilege_check": "privilege_result",
        }
    
    def get_completed_agents(self, state: AnalysisState) -> Set[str]:
        """Получить множество завершённых агентов."""
        completed = set()
        for agent, key in self._result_keys.items():
            if state.get(key) is not None:
                completed.add(agent)
        return completed
    
    def get_next_agent(self, state: AnalysisState) -> Optional[str]:
        """
        Определить следующий агент для выполнения.
        
        Args:
            state: Текущее состояние графа
        
        Returns:
            Имя следующего агента или None если все выполнены
        """
        requested = set(state.get("analysis_types", []))
        completed = self.get_completed_agents(state)
        
        # Фильтруем только поддерживаемые агенты
        requested = requested & ALL_AGENTS
        
        for agent in EXECUTION_PRIORITY:
            # Пропускаем если не запрошен
            if agent not in requested:
                continue
            
            # Пропускаем если уже выполнен
            if agent in completed:
                continue
            
            # Проверяем зависимости
            deps = DEPENDENCIES.get(agent, set())
            if not deps.issubset(completed):
                # Зависимости не готовы — пропускаем
                continue
            
            return agent
        
        return None
    
    def route(self, state: AnalysisState) -> str:
        """
        Маршрутизация для LangGraph conditional_edges.
        
        Args:
            state: Текущее состояние
        
        Returns:
            Имя следующего узла ("end" если все выполнены)
        """
        next_agent = self.get_next_agent(state)
        
        if next_agent:
            case_id = state.get("case_id", "unknown")
            logger.info(f"[SimplifiedRouter] {case_id}: → {next_agent}")
            return next_agent
        
        return "end"


# Singleton instance
_router_instance: Optional[SimplifiedRouter] = None


def get_simplified_router() -> SimplifiedRouter:
    """Получить singleton instance роутера."""
    global _router_instance
    if _router_instance is None:
        _router_instance = SimplifiedRouter()
    return _router_instance


