# Система самосознания агентов

## Обзор

Система самосознания позволяет ИИ-агентам самостоятельно определять пробелы в знаниях и принимать решения о необходимости веб-поиска на официальных юридических источниках.

## Архитектура

### Компоненты

1. **LegalReasoningModel** (`legal_reasoning_model.py`)
   - Определяет тип задачи (найти норму, прецедент, позицию ВС)
   - Выбирает правильный источник
   - Формирует поисковый запрос

2. **SelfAwarenessService** (`agent_self_awareness.py`)
   - Анализирует пробелы в знаниях агента
   - Генерирует стратегию поиска
   - Определяет, нужен ли поиск

3. **Official Legal Sources Tools** (`official_legal_sources_tool.py`)
   - `search_legislation_tool` - поиск на pravo.gov.ru
   - `search_supreme_court_tool` - поиск на vsrf.ru
   - `search_case_law_tool` - поиск на kad.arbitr.ru
   - `smart_legal_search_tool` - автоматический выбор источника

4. **EnhancedAdaptiveAgent** (`enhanced_adaptive_agent.py`)
   - Итеративный процесс решения задач
   - Самокоррекция на основе найденной информации
   - Интеграция с LangGraph Store

5. **SelfAwarenessMiddleware** (`self_awareness_middleware.py`)
   - Улучшает промпты агентов информацией о пробелах
   - Добавляет рекомендации по поиску

## Как это работает

### Пример 1: Агент Risk находит противоречие

1. **Анализ документов:** Агент анализирует документы дела
2. **Обнаружение пробела:** "Нужна норма права о форс-мажоре"
3. **SelfAwarenessService:** Определяет `MISSING_NORM`
4. **Генерация стратегии:** `search_legislation_tool` (pravo.gov.ru)
5. **Поиск:** Агент вызывает инструмент через function calling
6. **Обновление знаний:** Найденная норма используется в анализе

### Пример 2: Агент Discrepancy находит противоречие

1. **Анализ документов:** Агент сравнивает документы
2. **Обнаружение пробела:** "Нужны аналогичные дела"
3. **SelfAwarenessService:** Определяет `MISSING_PRECEDENT`
4. **Генерация стратегии:** `search_case_law_tool` (kad.arbitr.ru)
5. **Поиск:** Агент ищет прецеденты
6. **Обновление знаний:** Прецеденты используются в анализе

## Использование

### В промптах агентов

Промпты агентов уже обновлены с секцией "САМОСОЗНАНИЕ И ПРИНЯТИЕ РЕШЕНИЙ О ВЕБ-ПОИСКЕ", которая инструктирует агентов:
- Когда использовать инструменты веб-поиска
- Какой инструмент использовать
- Как формировать запросы

### Интеграция в агенты

Агенты автоматически получают доступ к инструментам через `get_all_tools()` или `get_critical_agent_tools()`.

### Использование EnhancedAdaptiveAgent

```python
from app.services.enhanced_adaptive_agent import EnhancedAdaptiveAgent
from app.services.langgraph_store_service import LangGraphStoreService

agent = EnhancedAdaptiveAgent(
    agent_type="risk",
    tools=get_all_tools(),
    llm=create_llm()
)

store_service = LangGraphStoreService(db)

result = await agent.solve_task(
    goal="Анализ рисков",
    initial_context={"documents_text": "...", "agent_output": "..."},
    case_id="case_123",
    store_service=store_service
)
```

## Настройка

### Переменные окружения

- `YANDEX_API_KEY` - API ключ Yandex для веб-поиска
- `YANDEX_FOLDER_ID` - Folder ID для Yandex Cloud
- `LANGSMITH_API_KEY` - API ключ LangSmith (опционально)
- `LANGSMITH_PROJECT` - Название проекта в LangSmith (по умолчанию: "legal-ai-vault")

## Тестирование

Запустите тесты:

```bash
pytest backend/tests/test_legal_reasoning_model.py
pytest backend/tests/test_agent_self_awareness.py
pytest backend/tests/test_official_legal_sources_tool.py
```

## Будущие улучшения

1. Использование GigaChat для более точного определения пробелов
2. Улучшенная валидация результатов поиска
3. Кэширование результатов поиска
4. Метрики эффективности поиска

