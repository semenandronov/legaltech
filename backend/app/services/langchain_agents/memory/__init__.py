"""
Memory модуль для LangGraph агентов.

Реализует долгосрочную память (cross-thread/cross-session) с использованием:
- Pydantic схем для типизации данных памяти
- LangGraph Store для персистентности
- LLM для обновления и извлечения информации

# ТИПЫ ПАМЯТИ

1. **User Profile** - профиль пользователя
   - Предпочтения
   - Область права
   - Стиль коммуникации

2. **Case Memory** - память по делу
   - Ключевые факты
   - Важные даты
   - Участники

3. **Query History** - история запросов
   - Прошлые вопросы
   - Паттерны использования

4. **Insights** - инсайты и выводы
   - Выявленные паттерны
   - Рекомендации

# ИСПОЛЬЗОВАНИЕ
```python
from app.services.langchain_agents.memory import (
    UserProfile,
    CaseMemory,
    MemoryStore,
    update_user_profile,
)

# Создание store
store = MemoryStore(db_session)

# Получение профиля
profile = store.get_user_profile(user_id)

# Обновление через LLM
updated_profile = await update_user_profile(
    profile,
    new_info="Пользователь специализируется на корпоративном праве"
)
```
"""

from app.services.langchain_agents.memory.schemas import (
    UserProfile,
    CaseMemory,
    QueryRecord,
    Insight,
    MemoryNamespace,
)

from app.services.langchain_agents.memory.store import (
    MemoryStore,
    get_memory_store,
)

from app.services.langchain_agents.memory.updaters import (
    update_user_profile,
    update_case_memory,
    extract_insights,
    create_query_record,
)

from app.services.langchain_agents.memory.trustcall import (
    TrustcallExtractor,
    TrustcallError,
    JsonPatch,
    extract_and_validate,
    update_with_patch,
    generate_extraction_prompt,
)

__all__ = [
    # Schemas
    "UserProfile",
    "CaseMemory",
    "QueryRecord",
    "Insight",
    "MemoryNamespace",
    # Store
    "MemoryStore",
    "get_memory_store",
    # Updaters
    "update_user_profile",
    "update_case_memory",
    "extract_insights",
    "create_query_record",
    # Trustcall
    "TrustcallExtractor",
    "TrustcallError",
    "JsonPatch",
    "extract_and_validate",
    "update_with_patch",
    "generate_extraction_prompt",
]

