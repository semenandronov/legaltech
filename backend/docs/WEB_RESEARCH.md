# Web Research Documentation

## Обзор

Документация по сервису веб-исследований для агентов. Предоставляет структурированный процесс веб-исследований с валидацией источников и кэшированием.

## Компоненты

### 1. Web Research Service (`web_research_service.py`)

Сервис для структурированных веб-исследований.

```python
from app.services.external_sources.web_research_service import get_web_research_service

service = get_web_research_service()

result = await service.research(
    query="прецеденты по договорам поставки",
    max_results=10,
    validate_sources=True,
    use_cache=True
)

print(f"Summary: {result.summary}")
print(f"Confidence: {result.confidence}")
print(f"Key findings: {result.key_findings}")
```

### 2. Web Research Tool (`web_research_tool.py`)

Инструмент для использования в агентах.

```python
from app.services.langchain_agents.web_research_tool import web_research_tool

# Использование в агенте
result = web_research_tool.invoke({
    "query": "прецеденты по договорам поставки",
    "max_results": 10
})
```

## Использование в агентах

Инструмент автоматически доступен через `get_all_tools()`:

```python
from app.services.langchain_agents.tools import get_all_tools

tools = get_all_tools()  # Включает web_research_tool
```

## Кэширование

Результаты автоматически кэшируются для оптимизации:

```python
# Первый запрос - выполняется поиск
result1 = await service.research("query", use_cache=True)

# Второй запрос - используется кэш
result2 = await service.research("query", use_cache=True)  # Из кэша

# Очистка кэша
service.clear_cache()
```

## Валидация источников

Автоматическая валидация включает:
- Удаление дубликатов по URL
- Проверка релевантности
- Форматирование результатов

## Интеграция

Сервис интегрирован в:
- `legal_research_tool.py` - для юридического поиска
- `citation_verifier.py` - для верификации цитат
- Агенты через `web_research_tool`

