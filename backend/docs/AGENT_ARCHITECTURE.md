# Архитектура агентной системы

## Обзор

Агентная система построена на LangGraph и использует архитектуру с координатором, супервизором и специализированными агентами.

## Компоненты

### 1. AgentCoordinator
**Файл:** `backend/app/services/langchain_agents/coordinator.py`

Главный координатор системы. Отвечает за:
- Инициализацию всех компонентов через ComponentFactory
- Запуск анализа через LangGraph
- Обработку результатов и ошибок
- Интеграцию с планировщиком

**Инициализация:**
- Использует `_initialize_components()` для единообразной инициализации
- Обязательные компоненты (граф) - fail fast
- Опциональные компоненты - graceful degradation

### 2. Supervisor
**Файл:** `backend/app/services/langchain_agents/supervisor.py`

Маршрутизатор задач. Определяет какой агент должен выполниться следующим.

**Логика маршрутизации:**
1. Проверка адаптированного плана (если есть)
2. Проверка подзадач (subtasks)
3. Определение независимых агентов → параллельное выполнение
4. Определение зависимых агентов → последовательное выполнение

**Оптимизации:**
- Кэширование решений через `graph_optimizer.RouteCache`
- Приоритеты агентов через `AgentPriorities`
- Упрощенная проверка завершенных агентов

### 3. Специализированные агенты

Каждый агент выполняет свою задачу:

- **document_classifier** - классификация документов
- **privilege_check** - проверка привилегий
- **entity_extraction** - извлечение сущностей
- **timeline** - извлечение хронологии
- **key_facts** - извлечение ключевых фактов
- **discrepancy** - поиск противоречий
- **risk** - анализ рисков (требует discrepancy)
- **summary** - генерация резюме (требует key_facts)
- **relationship** - построение графа связей (требует entity_extraction)

### 4. UnifiedErrorHandler
**Файл:** `backend/app/services/langchain_agents/unified_error_handler.py`

Единый обработчик ошибок для всех агентов.

**Классификация ошибок:**
- TIMEOUT - таймауты
- TOOL_ERROR - ошибки инструментов
- LLM_ERROR - ошибки LLM
- DEPENDENCY_ERROR - ошибки зависимостей
- VALIDATION_ERROR - ошибки валидации
- NETWORK_ERROR - сетевые ошибки

**Стратегии:**
- RETRY - повтор с exponential backoff
- FALLBACK - упрощенный подход
- SKIP - пропуск агента
- FAIL - критическая ошибка

### 5. ComponentFactory
**Файл:** `backend/app/services/langchain_agents/component_factory.py`

Централизованная фабрика для создания компонентов.

**Методы:**
- `create_required_component()` - обязательные компоненты (fail fast)
- `create_optional_component()` - опциональные компоненты (graceful degradation)
- `create_planning_agent()` - создание планировщика с fallback
- `create_all_components()` - создание всех компонентов

## Поток данных

```
User Request
    ↓
AgentCoordinator.run_analysis()
    ↓
PlanningAgent (если user_task предоставлен)
    ↓
create_initial_state()
    ↓
LangGraph.stream()
    ↓
init_workspace → understand → plan → supervisor
    ↓
supervisor.route_to_agent()
    ↓
[parallel_independent | individual_agent]
    ↓
agent_node()
    ↓
evaluation_node()
    ↓
[adaptation | deliver | supervisor]
    ↓
END
```

## Зависимости между агентами

**Независимые агенты** (могут выполняться параллельно):
- document_classifier
- entity_extraction
- timeline
- key_facts
- discrepancy

**Зависимые агенты:**
- risk → требует discrepancy
- summary → требует key_facts
- relationship → требует entity_extraction

## Параллельное выполнение

Независимые агенты выполняются параллельно через `parallel_independent_agents_node`:
- Использует ThreadPoolExecutor
- Адаптивные таймауты для каждого типа агента
- Максимум 5 параллельных агентов (настраивается)
- Thread-safe слияние состояний

## Обработка ошибок

1. **Классификация** - UnifiedErrorHandler определяет тип ошибки
2. **Стратегия** - выбирается стратегия обработки
3. **Retry** - если возможно, повтор с exponential backoff
4. **Fallback** - упрощенный подход (если применимо)
5. **Пропуск** - если ошибка не критична

## Кэширование

- **RouteCache** - кэширование решений супервизора
- **ResultCache** - кэширование результатов агентов (TTL: 1 час)

## Добавление нового агента

1. Создать файл `{agent_name}_node.py`
2. Реализовать функцию `{agent_name}_agent_node(state, db, rag_service, document_processor)`
3. Добавить узел в `graph.py`
4. Добавить маршрут в `supervisor.py`
5. Добавить приоритет в `graph_optimizer.AgentPriorities`
6. Обновить `state.py` (добавить `{agent_name}_result`)

## Конфигурация

Настройки в `backend/app/config.py`:
- `AGENT_ENABLED` - включить/выключить систему агентов
- `AGENT_MAX_PARALLEL` - максимум параллельных агентов (по умолчанию: 5)
- `AGENT_TIMEOUT` - таймаут по умолчанию (по умолчанию: 120 секунд)
- `AGENT_RETRY_COUNT` - количество повторов (по умолчанию: 2)































