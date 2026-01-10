# Правильное использование Command в LangGraph

## Проблема

При использовании `Command` в `add_conditional_edges` возникала ошибка:
```
TypeError: unhashable type: 'dict'
```

## Решение

**Command НЕ предназначен для использования в conditional edges.**

`Command` в LangGraph предназначен для:
1. **Interrupts/Resume** - для приостановки и возобновления выполнения графа
2. **Динамического управления потоком** - но НЕ через conditional edges

### Правильное использование Command

#### ✅ Правильно: Использование Command для interrupts/resume

```python
# В coordinator.py - resume_after_interrupt
stream_iter = self.graph.stream(
    None,
    thread_config,
    stream_mode="updates",
    command=Command(resume=answer)  # Правильно!
)
```

#### ❌ Неправильно: Использование Command в conditional edges

```python
# НЕПРАВИЛЬНО - вызывает TypeError: unhashable type: 'dict'
def route_function(state):
    return Command(
        goto="next_node",
        update={"metadata": {...}}
    )

graph.add_conditional_edges(
    "node",
    route_function,  # Возвращает Command - НЕПРАВИЛЬНО
    {"next_node": "next_node"}
)
```

### Правильное решение для conditional edges

В conditional edges нужно возвращать **только строки**:

```python
def route_function(state):
    # Возвращаем только строку
    return "next_node"

graph.add_conditional_edges(
    "node",
    route_function,  # Возвращает строку - ПРАВИЛЬНО
    {"next_node": "next_node"}
)
```

### Обновление состояния

Если нужно обновить состояние при роутинге, делайте это **в узлах**, а не через `Command.update`:

```python
def route_function(state):
    # Возвращаем только строку
    return "next_node"

def next_node(state):
    # Обновляем состояние здесь
    new_state = dict(state)
    new_state["metadata"] = {
        **state.get("metadata", {}),
        "routing_decision": {...}
    }
    return new_state

graph.add_conditional_edges("node", route_function, {"next_node": "next_node"})
graph.add_node("next_node", next_node)
```

## Вывод

- **Command** используется только для interrupts/resume
- **Conditional edges** должны возвращать только строки
- **Обновление состояния** при роутинге делается в узлах, а не через Command.update

