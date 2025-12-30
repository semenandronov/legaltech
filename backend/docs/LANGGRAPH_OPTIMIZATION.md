# LangGraph Optimization Documentation

## Обзор

Документация по оптимизации LangGraph графов в проекте. Включает информацию о кэшировании, приоритетах, checkpointing и мониторинге.

## Компоненты

### 1. Graph Optimizer (`graph_optimizer.py`)

Оптимизация conditional edges с кэшированием и приоритетами.

#### RouteCache

Кэш для решений роутинга с автоматической инвалидацией.

```python
from app.services.langchain_agents.graph_optimizer import RouteCache

cache = RouteCache(max_size=100)
cached_route = cache.get(state)
cache.set(state, route)
```

#### AgentPriorities

Приоритеты агентов для оптимизации порядка выполнения.

```python
from app.services.langchain_agents.graph_optimizer import AgentPriorities

priority = AgentPriorities.get_priority("document_classifier")
sorted_agents = AgentPriorities.sort_by_priority(agent_list)
```

#### optimize_route_function

Обертка для функции роутинга с оптимизациями.

```python
from app.services.langchain_agents.graph_optimizer import optimize_route_function

optimized_route = optimize_route_function(
    base_route_func,
    enable_cache=True,
    enable_priorities=True
)
```

### 2. Checkpointing (`checkpointer_setup.py`, `checkpoint_helper.py`)

#### Connection Pooling

PostgreSQL checkpointer с connection pooling для лучшей производительности.

```python
from app.utils.checkpointer_setup import get_checkpointer_instance

checkpointer = get_checkpointer_instance()
graph = graph.compile(checkpointer=checkpointer)
```

#### Intermediate Checkpoints

Промежуточные checkpoint'ы для длительных операций.

```python
from app.services.langchain_agents.checkpoint_helper import with_intermediate_checkpoint

@with_intermediate_checkpoint(checkpoint_interval=60)
def long_running_node(state: AnalysisState) -> AnalysisState:
    # ... node implementation
```

### 3. Graph Monitoring (`graph_monitoring.py`)

Мониторинг выполнения графов с метриками.

```python
from app.services.langchain_agents.graph_monitoring import get_graph_monitor, monitor_node_execution

# Декоратор для автоматического мониторинга
@monitor_node_execution("my_node")
def my_node(state: AnalysisState) -> AnalysisState:
    # ... node implementation

# Получение метрик
monitor = get_graph_monitor()
metrics = monitor.get_node_metrics("my_node")
summary = monitor.get_performance_summary()
```

### 4. Error Handling (`error_handler.py`)

Retry механизмы и улучшенная обработка ошибок.

```python
from app.services.langchain_agents.error_handler import with_retry, RetryConfig

# Стандартный retry
@with_retry()
def my_node(state: AnalysisState) -> AnalysisState:
    # ... node implementation

# Кастомный retry config
config = RetryConfig(max_retries=5, initial_delay=2.0)
@with_retry(retry_config=config)
def my_node(state: AnalysisState) -> AnalysisState:
    # ... node implementation
```

## Использование

Все оптимизации автоматически применяются при создании графа в `graph.py`. Дополнительная настройка не требуется для базового использования.

## Метрики производительности

Используйте GraphMonitor для отслеживания производительности:

```python
from app.services.langchain_agents.graph_monitoring import get_graph_monitor

monitor = get_graph_monitor()
summary = monitor.get_performance_summary()
print(f"Average execution time: {summary['average_execution_time']:.2f}s")
print(f"Slowest nodes: {summary['slowest_nodes']}")
```

