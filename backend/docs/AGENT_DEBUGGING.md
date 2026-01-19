# Руководство по отладке агентной системы

## Диагностика проблем

### 1. Проблемы инициализации

**Симптом:** Coordinator не инициализируется или падает с ошибкой

**Диагностика:**
```python
# Проверить логи инициализации
# Должны быть сообщения:
# "✅ AnalysisGraph initialized"
# "✅ Advanced Planning Agent initialized" (или fallback)
# "AgentCoordinator initialization completed"
```

**Типичные проблемы:**
- Отсутствует RAG service → проверьте `RAGService()` инициализацию
- Недоступна БД → проверьте `DATABASE_URL`
- Ошибка создания графа → проверьте зависимости LangGraph

**Решение:**
- Проверить обязательные компоненты через ComponentFactory
- Опциональные компоненты должны деградировать gracefully

### 2. Проблемы выполнения агентов

**Симптом:** Агент не выполняется или возвращает пустой результат

**Диагностика:**
```python
# Проверить логи выполнения
# Должны быть сообщения:
# "[AgentName] agent: Starting for case {case_id}"
# "[AgentName] agent: Completed successfully"
```

**Типичные проблемы:**
- Таймаут → проверьте `AGENT_TIMEOUT` и адаптивные таймауты
- Ошибка LLM → проверьте `GIGACHAT_CREDENTIALS`
- Ошибка инструментов → проверьте `bind_tools` поддержку

**Решение:**
- Проверить UnifiedErrorHandler логи
- Увеличить таймаут для медленных агентов
- Проверить fallback механизм

### 3. Проблемы маршрутизации

**Симптом:** Supervisor выбирает неправильного агента или зацикливается

**Диагностика:**
```python
# Проверить логи супервизора
# Должны быть сообщения:
# "[Супервизор] {case_id}: → {agent_name}"
# "[Супервизор] {case_id}: ✅ Все анализы завершены!"
```

**Типичные проблемы:**
- Бесконечный цикл → проверьте зависимости агентов
- Неправильный порядок → проверьте приоритеты в `AgentPriorities`
- Кэш устарел → очистите `RouteCache`

**Решение:**
- Проверить логику `route_to_agent()`
- Очистить кэш: `RouteCache().clear()`
- Проверить зависимости в `DEPENDENT_AGENTS`

### 4. Проблемы параллельного выполнения

**Симптом:** Агенты выполняются последовательно вместо параллельно

**Диагностика:**
```python
# Проверить логи параллельного выполнения
# Должны быть сообщения:
# "[Parallel] Running {N} independent agents in parallel"
# "[Parallel] Completed {agent_name} agent successfully"
```

**Типичные проблемы:**
- Только один агент → проверьте `AGENT_MAX_PARALLEL`
- Таймауты → проверьте адаптивные таймауты
- Конфликты состояния → проверьте thread-safe слияние

**Решение:**
- Увеличить `AGENT_MAX_PARALLEL` в config
- Проверить что агенты действительно независимы
- Проверить thread-safe операции

## Типичные ошибки и решения

### Ошибка: "Failed to initialize AdvancedPlanningAgent"

**Причина:** Проблема с инициализацией планировщика

**Решение:**
- Проверить доступность LLM (GigaChat)
- Проверить RAG service инициализацию
- Система автоматически fallback на базовый PlanningAgent

### Ошибка: "Timeout after X seconds"

**Причина:** Агент выполняется слишком долго

**Решение:**
- Увеличить таймаут для конкретного агента в `AGENT_TIMEOUTS`
- Проверить размер документов (может быть слишком большой)
- Проверить производительность LLM

### Ошибка: "bind_tools not supported"

**Причина:** LLM не поддерживает function calling

**Решение:**
- Система автоматически fallback на прямой LLM вызов
- Проверить версию GigaChat API
- Обновить credentials если нужно

### Ошибка: "Dependency not ready"

**Причина:** Зависимый агент запущен до готовности зависимости

**Решение:**
- Проверить логику зависимостей в supervisor
- Убедиться что зависимости выполняются первыми
- Проверить что результаты сохраняются в state

## Инструменты для мониторинга

### 1. Логирование

Используйте централизованное логирование:
```python
from app.services.langchain_agents.logging_config import get_agent_logger

logger = get_agent_logger(__name__)
logger.info("Your message")
```

### 2. Метрики

Проверьте метрики выполнения:
```python
from app.services.metrics.planning_metrics import MetricsCollector

collector = MetricsCollector(db)
metrics = collector.get_agent_metrics(agent_name="timeline", limit=10)
```

### 3. State инспекция

Проверьте состояние графа:
```python
graph_state = coordinator.graph.get_state(thread_config)
state = graph_state.values
print(state.keys())  # Все ключи состояния
print(state.get("errors"))  # Ошибки
```

### 4. Кэш статистика

Проверьте статистику кэша:
```python
from app.services.langchain_agents.result_cache import get_result_cache

cache = get_result_cache()
stats = cache.get_stats()
print(stats)  # Статистика кэша
```

## Чеклист отладки

1. ✅ Проверить инициализацию компонентов
2. ✅ Проверить доступность LLM (GigaChat)
3. ✅ Проверить доступность БД
4. ✅ Проверить логи на ошибки
5. ✅ Проверить таймауты
6. ✅ Проверить зависимости агентов
7. ✅ Проверить параллельное выполнение
8. ✅ Проверить кэш (если используется)
9. ✅ Проверить метрики выполнения
10. ✅ Проверить state на наличие результатов

## Полезные команды

```bash
# Проверить конфигурацию
python -c "from app.config import config; print(config.AGENT_ENABLED, config.AGENT_MAX_PARALLEL, config.AGENT_TIMEOUT)"

# Проверить качество агентов
python backend/scripts/check_agent_quality.py {case_id}

# Проверить API агентов
python backend/scripts/check_agents_api.py {case_id} {token}
```








































