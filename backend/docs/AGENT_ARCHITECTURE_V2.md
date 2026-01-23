# Agent Architecture V2 - Страничная архитектура

## Обзор

Новая архитектура агентов построена вокруг страниц приложения, а не типов анализа.
Каждая страница имеет свой граф (LangGraph) и агентов.

## Принципы (из LangGraph документации)

### Когда использовать агента vs узел

**Агент (Agent)** нужен когда:
- Есть принятие решений о следующем действии
- Нужны циклы (итеративное уточнение)
- Есть условная логика на основе результатов tools
- Требуется Human-in-the-Loop

**Узел (Node)** достаточен когда:
- Линейная обработка без ветвлений
- Простой вызов LLM с промптом
- Нет итераций или условий

### Правило
> "Начните с простых цепочек (chains). Переходите на агентов только если нужны циклы или условные переходы."

---

## Структура файлов

```
backend/app/services/langchain_agents/
├── agents/                           # Настоящие агенты
│   ├── __init__.py
│   ├── chat_react_agent.py          # ReAct агент для чата
│   ├── tabular_extraction_agent.py  # Map-Reduce агент для таблиц
│   └── workflow_orchestrator_agent.py # Оркестратор workflows
│
├── graphs/                           # LangGraph графы
│   ├── __init__.py
│   ├── chat_graph.py                # Граф для AssistantChatPage
│   ├── tabular_graph.py             # Граф для TabularReviewPage
│   └── workflow_graph.py            # Граф для WorkflowsPage
│
├── nodes/                            # Простые узлы
│   ├── __init__.py
│   ├── discrepancy_risk_node.py     # Объединённый узел
│   └── summary_chain.py             # Упрощённый summary
│
├── chat_graph_service.py            # Сервис интеграции ChatGraph
├── tabular_graph_service.py         # Сервис интеграции TabularGraph
└── workflow_graph_service.py        # Сервис интеграции WorkflowGraph
```

---

## Страница: AssistantChatPage

### Граф: ChatGraph

```
START -> mode_router -> [normal_flow | deep_think_flow | garant_flow | draft_flow] -> response_node -> END
```

### Режимы

| Режим | Описание | Используемые узлы |
|-------|----------|-------------------|
| `normal` | RAG поиск + ответы | rag_retrieval -> generate_response |
| `deep_think` | Глубокий анализ | rag_retrieval -> garant_retrieval -> thinking -> generate_response |
| `garant` | Поиск в ГАРАНТ | rag_retrieval -> garant_retrieval -> generate_response |
| `draft` | Создание документа | draft_node |

### Агент: ChatReActAgent

ReAct агент с tools:
- `rag_search` - поиск в документах дела
- `garant_search` - поиск в правовой базе ГАРАНТ
- `deep_analysis` - глубокий анализ (режим deep_think)
- `create_document` - создание документа (режим draft)

### Использование

```python
from app.services.langchain_agents import get_chat_graph_service

service = get_chat_graph_service(db, rag_service)

async for event in service.stream_response(
    case_id="...",
    question="...",
    user=current_user,
    deep_think=True
):
    yield event
```

---

## Страница: TabularReviewPage

### Граф: TabularGraph

```
START -> validate -> map_extract -> reduce_merge -> check_confidence -> [clarify_interrupt | save] -> END
```

### Паттерн: Map-Reduce

1. **Map**: Параллельное извлечение из каждого документа
2. **Reduce**: Объединение результатов
3. **HITL**: interrupt() для ячеек с низкой уверенностью

### Агент: TabularExtractionAgent

- Извлечение данных из документов в табличную структуру
- Поддержка типов колонок: text, number, currency, yes_no, date, tag, verbatim
- Оценка уверенности для каждой ячейки
- HITL через LangGraph interrupt

### Использование

```python
from app.services.langchain_agents import get_tabular_graph_service

service = get_tabular_graph_service(db, rag_service)

async for event in service.start_extraction(
    review_id="...",
    case_id="...",
    user=current_user,
    columns=[...],
    file_ids=[...]
):
    if event.get("type") == "clarification_requests":
        # Показать UI для уточнения
        pass
    yield event

# После получения ответов пользователя
async for event in service.resume_with_clarifications(
    thread_id="...",
    clarification_responses={...}
):
    yield event
```

---

## Страница: WorkflowsPage

### Граф: WorkflowGraph

```
START -> analyze -> generate_plan -> [approval_interrupt | execute] -> execute_steps -> monitor -> synthesize -> END
```

### Паттерн: Планирование + Параллельное выполнение

1. **Анализ**: Определение структуры workflow
2. **Планирование**: Генерация плана с оценкой времени
3. **HITL**: interrupt() для одобрения плана
4. **Выполнение**: Параллельное выполнение независимых шагов
5. **Мониторинг**: Отслеживание прогресса и адаптация
6. **Синтез**: Объединение результатов

### Агент: WorkflowOrchestratorAgent

- Планирование шагов с учётом зависимостей
- Параллельное выполнение независимых шагов
- Автоматическая адаптация при ошибках
- HITL для одобрения плана

### Использование

```python
from app.services.langchain_agents import get_workflow_graph_service

service = get_workflow_graph_service(db, rag_service)

async for event in service.start_workflow(
    workflow_id="...",
    case_id="...",
    user=current_user,
    workflow_definition={...}
):
    if event.get("type") == "plan":
        # Показать UI для одобрения плана
        pass
    yield event

# После одобрения плана
async for event in service.approve_plan(
    thread_id="...",
    approved=True
):
    yield event
```

---

## Узлы (Nodes)

### discrepancy_risk_node

Объединённый узел для поиска противоречий и оценки рисков.

**Почему объединили:**
- `risk_node` зависит от `discrepancy_result`
- Нет смысла разделять на отдельные узлы
- Уменьшает latency

### summary_chain

Упрощённый summary как LangChain chain (не агент).

**Почему упростили:**
- summary не требует tools
- Это просто генерация текста на основе key_facts
- Chain достаточен, агент избыточен

---

## Миграция с v1

### Было (v1)

```python
from app.services.langchain_agents import AgentCoordinator

coordinator = AgentCoordinator(...)
async for event in coordinator.run_analysis(...):
    yield event
```

### Стало (v2)

```python
from app.services.langchain_agents import get_chat_graph_service

service = get_chat_graph_service(db, rag_service)
async for event in service.stream_response(...):
    yield event
```

### Обратная совместимость

Старые компоненты остаются доступными:
- `AgentCoordinator` - для фонового анализа
- `create_analysis_graph` - старый граф
- `SimplifiedAgentCoordinator` - упрощённый координатор

---

## HITL (Human-in-the-Loop)

### Как работает

1. Граф вызывает `interrupt(payload)` в узле
2. Выполнение останавливается
3. Клиент получает событие с `thread_id` и данными для UI
4. Пользователь отвечает через UI
5. Клиент вызывает `resume` с ответом
6. Граф продолжает выполнение

### Пример: TabularGraph

```python
# В узле clarify_interrupt_node
interrupt({
    "type": "table_clarification",
    "requests": [...]
})

# На клиенте
# 1. Показать модал с запросами
# 2. Получить ответы пользователя
# 3. Вызвать resume

async for event in service.resume_with_clarifications(
    thread_id=thread_id,
    clarification_responses=responses
):
    yield event
```

---

## Checkpointing

Все графы используют PostgresSaver для сохранения состояния:

```python
from app.utils.checkpointer_setup import get_checkpointer_instance

checkpointer = get_checkpointer_instance()
graph = graph.compile(checkpointer=checkpointer)
```

Это позволяет:
- Возобновлять выполнение после interrupt
- Восстанавливать состояние при ошибках
- Отслеживать историю выполнения



