"""
Конфигурация assistants для LangGraph.

Определяет преднастроенные конфигурации для различных use cases.
"""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


class GraphType(str, Enum):
    """Типы графов."""
    CHAT = "chat"
    TABULAR = "tabular"
    WORKFLOW = "workflow"


class AssistantMetadata(BaseModel):
    """Метаданные assistant."""
    mode: Optional[str] = Field(None, description="Режим работы (normal, deep_think, garant, draft)")
    enable_garant: bool = Field(True, description="Включить поиск в ГАРАНТ")
    confidence_threshold: float = Field(0.8, description="Порог уверенности для HITL")
    enable_hitl: bool = Field(True, description="Включить Human-in-the-Loop")
    require_approval: bool = Field(False, description="Требовать одобрения плана")
    auto_adapt: bool = Field(True, description="Автоматическая адаптация при ошибках")
    max_parallel_steps: int = Field(3, description="Максимум параллельных шагов")


class AssistantConfig(BaseModel):
    """Конфигурация assistant."""
    id: str = Field(..., description="Уникальный ID assistant")
    name: str = Field(..., description="Название")
    description: str = Field(..., description="Описание")
    graph: GraphType = Field(..., description="Тип графа")
    metadata: AssistantMetadata = Field(default_factory=AssistantMetadata)
    
    # Настройки графа
    use_checkpointing: bool = Field(True, description="Использовать checkpointing")
    use_send_api: bool = Field(True, description="Использовать Send API")
    enable_memory_management: bool = Field(True, description="Управление памятью")
    
    # Breakpoints
    interrupt_before: List[str] = Field(default_factory=list)
    interrupt_after: List[str] = Field(default_factory=list)
    
    # Системный промпт
    system_prompt: Optional[str] = Field(None, description="Кастомный системный промпт")


# ============== Predefined Assistants ==============

ASSISTANT_CONFIGS: Dict[str, AssistantConfig] = {
    "legal-assistant": AssistantConfig(
        id="legal-assistant",
        name="Legal AI Assistant",
        description="Общий юридический ассистент для анализа дел и обзора документов",
        graph=GraphType.CHAT,
        metadata=AssistantMetadata(
            mode="normal",
            enable_garant=True
        ),
        system_prompt="""# РОЛЬ
Ты — профессиональный юридический AI-ассистент. Твоя задача — помогать пользователю с юридическими вопросами.

# ЦЕЛЬ
Предоставлять точные, обоснованные ответы на юридические вопросы, опираясь на документы дела и законодательство.

# ИНСТРУКЦИИ
1. Анализируй вопрос и определяй, нужен ли поиск в документах или законодательстве
2. Используй RAG для поиска в документах дела
3. Используй ГАРАНТ для поиска в законодательстве
4. Формируй структурированный ответ с цитатами

# ОГРАНИЧЕНИЯ
- НЕ выдумывай информацию
- ВСЕГДА указывай источники
- Предупреждай о необходимости консультации с юристом"""
    ),
    
    "deep-analyst": AssistantConfig(
        id="deep-analyst",
        name="Deep Legal Analyst",
        description="Глубокий юридический анализ с пошаговым мышлением",
        graph=GraphType.CHAT,
        metadata=AssistantMetadata(
            mode="deep_think",
            enable_garant=True
        ),
        system_prompt="""# РОЛЬ
Ты — глубокий юридический аналитик. Твоя задача — проводить детальный анализ сложных правовых вопросов.

# ЦЕЛЬ
Предоставлять всесторонний анализ с аргументацией, рассмотрением альтернатив и рисков.

# ПРОЦЕСС АНАЛИЗА
1. ПОНИМАНИЕ: Разбери вопрос на составляющие
2. КОНТЕКСТ: Изучи релевантные документы и нормы
3. АРГУМЕНТАЦИЯ: Построй логическую цепочку
4. ВЫВОДЫ: Сформулируй заключение с рекомендациями

# ФОРМАТ
Используй структурированный формат с заголовками и нумерованными списками."""
    ),
    
    "document-drafter": AssistantConfig(
        id="document-drafter",
        name="Document Drafter",
        description="Составление юридических документов",
        graph=GraphType.CHAT,
        metadata=AssistantMetadata(
            mode="draft",
            enable_garant=False
        ),
        system_prompt="""# РОЛЬ
Ты — профессиональный составитель юридических документов.

# ЦЕЛЬ
Создавать качественные юридические документы на основе требований пользователя.

# ПОДДЕРЖИВАЕМЫЕ ДОКУМЕНТЫ
- Договоры (купли-продажи, аренды, услуг, подряда)
- Исковые заявления
- Претензии
- Жалобы
- Доверенности
- Заявления

# ИНСТРУКЦИИ
1. Уточни тип документа и ключевые параметры
2. Используй правильную структуру и реквизиты
3. Применяй юридическую терминологию
4. Предложи варианты формулировок"""
    ),
    
    "tabular-extractor": AssistantConfig(
        id="tabular-extractor",
        name="Tabular Data Extractor",
        description="Извлечение структурированных данных из документов в таблицы",
        graph=GraphType.TABULAR,
        metadata=AssistantMetadata(
            confidence_threshold=0.8,
            enable_hitl=True
        ),
        use_send_api=True,
        interrupt_before=["clarify_interrupt"]
    ),
    
    "workflow-orchestrator": AssistantConfig(
        id="workflow-orchestrator",
        name="Workflow Orchestrator",
        description="Выполнение сложных многошаговых юридических workflows",
        graph=GraphType.WORKFLOW,
        metadata=AssistantMetadata(
            require_approval=True,
            auto_adapt=True,
            max_parallel_steps=3
        ),
        use_send_api=True,
        interrupt_before=["approval_interrupt"]
    ),
    
    "garant-expert": AssistantConfig(
        id="garant-expert",
        name="ГАРАНТ Expert",
        description="Специалист по поиску в правовой базе ГАРАНТ",
        graph=GraphType.CHAT,
        metadata=AssistantMetadata(
            mode="garant",
            enable_garant=True
        ),
        system_prompt="""# РОЛЬ
Ты — эксперт по правовой базе ГАРАНТ. Твоя задача — находить релевантные нормы права.

# ЦЕЛЬ
Предоставлять точные ссылки на законы, кодексы, судебную практику.

# ИНСТРУКЦИИ
1. Определи тип правового вопроса
2. Найди релевантные нормы в ГАРАНТ
3. Процитируй ключевые положения
4. Укажи актуальную редакцию

# ФОРМАТ ОТВЕТА
Используй формат:
[1] Название документа
URL: ссылка
Цитата: текст нормы"""
    ),
}


def get_assistant_config(assistant_id: str) -> Optional[AssistantConfig]:
    """
    Получить конфигурацию assistant по ID.
    
    Args:
        assistant_id: ID assistant
    
    Returns:
        AssistantConfig или None
    """
    return ASSISTANT_CONFIGS.get(assistant_id)


def list_assistants() -> List[Dict[str, Any]]:
    """
    Получить список всех доступных assistants.
    
    Returns:
        Список с информацией о каждом assistant
    """
    return [
        {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "graph": config.graph.value,
            "metadata": config.metadata.model_dump()
        }
        for config in ASSISTANT_CONFIGS.values()
    ]

