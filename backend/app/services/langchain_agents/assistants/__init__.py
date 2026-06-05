"""
Assistants модуль для LangGraph.

Предоставляет преднастроенные конфигурации агентов (assistants)
для различных use cases.

# ДОСТУПНЫЕ ASSISTANTS

1. **legal-assistant** - Общий юридический ассистент
   - RAG поиск в документах
   - Поиск в ГАРАНТ
   - Ответы на вопросы

2. **deep-analyst** - Глубокий аналитик
   - Пошаговое мышление
   - Развёрнутый анализ
   - Аргументация

3. **document-drafter** - Составитель документов
   - Создание юридических документов
   - Шаблоны
   - Форматирование

4. **workflow-orchestrator** - Оркестратор workflows
   - Многошаговые задачи
   - Параллельное выполнение
   - Адаптация при ошибках

# ИСПОЛЬЗОВАНИЕ
```python
from app.services.langchain_agents.assistants import (
    get_assistant,
    list_assistants,
    AssistantConfig,
)

# Получить assistant
assistant = get_assistant("legal-assistant", db=db)

# Выполнить запрос
result = await assistant.invoke({
    "question": "Какой срок исковой давности?",
    "case_id": "case-123"
})
```
"""

from app.services.langchain_agents.assistants.config import (
    AssistantConfig,
    AssistantMetadata,
    ASSISTANT_CONFIGS,
    get_assistant_config,
    list_assistants,
)

from app.services.langchain_agents.assistants.factory import (
    get_assistant,
    create_assistant,
    AssistantInstance,
)

__all__ = [
    # Config
    "AssistantConfig",
    "AssistantMetadata",
    "ASSISTANT_CONFIGS",
    "get_assistant_config",
    "list_assistants",
    # Factory
    "get_assistant",
    "create_assistant",
    "AssistantInstance",
]

