# Атомарность чекпоинтов и Store

## Текущая реализация

### Checkpointer (PostgresSaver)
- Используется `PostgresSaver` из `langgraph.checkpoint.postgres`
- Таблицы: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`
- Инициализация через `get_checkpointer_instance()` с connection pooling

### Store (LangGraph Store)
- Опциональная интеграция через `store_integration.py`
- Используется для long-term memory
- Инициализируется отдельно от checkpointer

## Проблема атомарности

Текущая реализация НЕ гарантирует атомарность между:
1. Записью checkpoints (через PostgresSaver)
2. Записью в Store (если используется)

Это может привести к:
- Несогласованности данных при сбоях
- Потере данных между checkpoint и store

## Рекомендации

### 1. Транзакции PostgreSQL
Если Store также использует PostgreSQL:
- Использовать транзакции для атомарности
- Оборачивать checkpoint + store операции в одну транзакцию

### 2. Версионирование state
Добавить поле `state_version` в AnalysisState для отслеживания изменений:
```python
metadata: {
    "state_version": "1.0",
    "checkpoint_id": "...",
    ...
}
```

### 3. Health-check checkpointer
Перед использованием проверять доступность checkpointer:
```python
def health_check_checkpointer() -> bool:
    try:
        checkpointer = get_checkpointer_instance()
        if checkpointer:
            # Попытка простой операции
            return True
    except Exception:
        return False
```

### 4. Миграции схемы
Документировать изменения схемы checkpoints:
- Версии сериализации state
- Изменения структуры таблиц
- Обратная совместимость

## Реализация (будущее)

Для полной атомарности требуется:
1. Единый транзакционный контекст для checkpoint + store
2. Версионирование state schema
3. Health-check перед использованием
4. Миграции для schema changes

Текущая реализация работает для большинства случаев, но не гарантирует атомарность при сбоях между операциями.

