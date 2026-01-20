"""
Определение основных агентов для юридического анализа.

Единый источник правды для:
- Списка поддерживаемых агентов
- Зависимостей между агентами
- Описаний и ключевых слов
- Порядка выполнения

Используется вместо разбросанных определений в planning_tools.py, supervisor.py, graph.py
"""
from typing import Dict, Set, List, Any
from dataclasses import dataclass, field


@dataclass
class AgentDefinition:
    """Определение агента."""
    name: str
    description: str
    keywords: List[str]
    dependencies: Set[str] = field(default_factory=set)
    is_core: bool = True  # True = основной, False = опциональный
    result_key: str = ""  # Ключ результата в state
    
    def __post_init__(self):
        if not self.result_key:
            # Автогенерация ключа результата
            key_map = {
                "document_classifier": "classification_result",
                "entity_extraction": "entities_result",
                "privilege_check": "privilege_result",
            }
            self.result_key = key_map.get(self.name, f"{self.name}_result")


# =============================================================================
# ОПРЕДЕЛЕНИЯ АГЕНТОВ
# =============================================================================

AGENT_DEFINITIONS: Dict[str, AgentDefinition] = {
    # === ОСНОВНЫЕ АГЕНТЫ (6 штук) ===
    
    "document_classifier": AgentDefinition(
        name="document_classifier",
        description="Классификация документов по типам и категориям",
        keywords=["классификация", "типы документов", "категории", "классифицировать"],
        dependencies=set(),
        is_core=True,
    ),
    
    "entity_extraction": AgentDefinition(
        name="entity_extraction",
        description="Извлечение сущностей (люди, организации, суммы, даты, места)",
        keywords=["сущности", "entities", "люди", "организации", "даты", "суммы", "имена"],
        dependencies=set(),
        is_core=True,
    ),
    
    "timeline": AgentDefinition(
        name="timeline",
        description="Извлечение хронологии событий из документов",
        keywords=["даты", "события", "хронология", "timeline", "временная линия"],
        dependencies=set(),
        is_core=True,
    ),
    
    "key_facts": AgentDefinition(
        name="key_facts",
        description="Извлечение ключевых фактов из документов",
        keywords=["факты", "ключевые факты", "key facts", "важные детали"],
        dependencies=set(),
        is_core=True,
    ),
    
    "discrepancy": AgentDefinition(
        name="discrepancy",
        description="Поиск противоречий и несоответствий между документами",
        keywords=["противоречия", "несоответствия", "discrepancy", "расхождения"],
        dependencies=set(),
        is_core=True,
    ),
    
    "summary": AgentDefinition(
        name="summary",
        description="Генерация резюме дела на основе ключевых фактов",
        keywords=["резюме", "summary", "краткое содержание", "сводка"],
        dependencies={"key_facts"},  # Требует key_facts
        is_core=True,
    ),
    
    # === ОПЦИОНАЛЬНЫЕ АГЕНТЫ ===
    
    "risk": AgentDefinition(
        name="risk",
        description="Анализ рисков на основе найденных противоречий",
        keywords=["риски", "risk", "анализ рисков", "оценка рисков"],
        dependencies={"discrepancy"},  # Требует discrepancy
        is_core=False,
    ),
    
    "relationship": AgentDefinition(
        name="relationship",
        description="Построение графа связей между сущностями",
        keywords=["связи", "relationship", "граф связей", "взаимосвязи"],
        dependencies={"entity_extraction"},  # Требует entity_extraction
        is_core=False,
    ),
    
    "privilege_check": AgentDefinition(
        name="privilege_check",
        description="Проверка документов на адвокатскую тайну и привилегии",
        keywords=["привилегии", "адвокатская тайна", "privilege", "конфиденциальность"],
        dependencies=set(),
        is_core=False,
    ),
}


# =============================================================================
# УДОБНЫЕ КОНСТАНТЫ
# =============================================================================

# Основные агенты
CORE_AGENTS: Set[str] = {
    name for name, defn in AGENT_DEFINITIONS.items() if defn.is_core
}

# Опциональные агенты
OPTIONAL_AGENTS: Set[str] = {
    name for name, defn in AGENT_DEFINITIONS.items() if not defn.is_core
}

# Все агенты
ALL_AGENTS: Set[str] = set(AGENT_DEFINITIONS.keys())

# Зависимости
DEPENDENCIES: Dict[str, Set[str]] = {
    name: defn.dependencies for name, defn in AGENT_DEFINITIONS.items()
}

# Порядок выполнения (приоритет)
EXECUTION_ORDER: List[str] = [
    "document_classifier",  # 1. Классификация
    "entity_extraction",    # 2. Сущности
    "timeline",             # 3. Хронология
    "key_facts",            # 4. Факты
    "discrepancy",          # 5. Противоречия
    "risk",                 # 6. Риски (опционально)
    "relationship",         # 7. Связи (опционально)
    "privilege_check",      # 8. Привилегии (опционально)
    "summary",              # 9. Резюме (последний)
]

# Маппинг агент → ключ результата
RESULT_KEYS: Dict[str, str] = {
    name: defn.result_key for name, defn in AGENT_DEFINITIONS.items()
}


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def get_agent_definition(agent_name: str) -> AgentDefinition:
    """Получить определение агента."""
    if agent_name not in AGENT_DEFINITIONS:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {list(AGENT_DEFINITIONS.keys())}")
    return AGENT_DEFINITIONS[agent_name]


def validate_analysis_types(analysis_types: List[str]) -> tuple:
    """
    Валидировать список типов анализа.
    
    Returns:
        (is_valid, invalid_types)
    """
    invalid = [t for t in analysis_types if t not in ALL_AGENTS]
    return len(invalid) == 0, invalid


def get_agents_with_dependencies(analysis_types: List[str]) -> List[str]:
    """
    Добавить недостающие зависимости к списку агентов.
    
    Args:
        analysis_types: Запрошенные типы анализа
    
    Returns:
        Список с добавленными зависимостями в правильном порядке
    """
    requested = set(analysis_types) & ALL_AGENTS
    
    # Добавляем зависимости
    to_add = set()
    for agent in requested:
        deps = DEPENDENCIES.get(agent, set())
        to_add.update(deps)
    
    all_agents = requested | to_add
    
    # Сортируем по порядку выполнения
    result = [a for a in EXECUTION_ORDER if a in all_agents]
    
    return result


def get_available_analyses_info() -> Dict[str, Any]:
    """
    Получить информацию о доступных анализах для API/UI.
    
    Returns:
        Словарь с информацией о каждом агенте
    """
    return {
        name: {
            "description": defn.description,
            "keywords": defn.keywords,
            "dependencies": list(defn.dependencies),
            "is_core": defn.is_core,
        }
        for name, defn in AGENT_DEFINITIONS.items()
    }


