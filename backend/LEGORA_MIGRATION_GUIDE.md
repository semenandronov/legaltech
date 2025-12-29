# LEGORA Migration Guide

## Обзор миграции

Это руководство описывает процесс миграции существующей системы к полной архитектуре LEGORA.

## Что изменилось

### Новые узлы
1. **understand_node** - Фаза понимания задачи
2. **plan_node** - Фаза планирования (рефакторинг PlanningAgent)
3. **deliver_node** - Фаза доставки результатов

### Новые компоненты
1. **DeepReasoningAgent** - для сложных задач
2. **Legal Research Tools** - поиск прецедентов
3. **Table Creator Tool** - автоматическое создание таблиц
4. **MoyArbitrSource, VASPracticeSource** - источники правовой информации

### Обновленные компоненты
1. **graph.py** - добавлены новые узлы и edges
2. **coordinator.py** - поддержка delivery_result
3. **state.py** - новые поля для LEGORA workflow
4. **supervisor.py** - роутинг к deep_analysis
5. **tools.py** - добавлены legal research tools

## Пошаговая миграция

### Шаг 1: Обновление зависимостей

```bash
# Установить langchain-experimental (опционально, для DeepAgentExecutor)
pip install langchain-experimental
```

### Шаг 2: Обновление кода

Все изменения уже внесены в код. Система автоматически использует LEGORA workflow по умолчанию.

### Шаг 3: Тестирование

1. **Проверить базовый workflow**:
```python
coordinator = AgentCoordinator(db, rag_service, document_processor)
results = coordinator.run_analysis(case_id, ["timeline"], "Извлеки даты")
```

2. **Проверить LEGORA workflow**:
```python
results = coordinator.run_analysis(
    case_id, 
    ["timeline", "risk"], 
    "Найди все риски с учетом прецедентов"
)
assert results.get("workflow") == "legora"
assert "delivery" in results
```

### Шаг 4: Обратная совместимость

Если нужно временно отключить LEGORA:

```python
coordinator = AgentCoordinator(
    db, rag_service, document_processor,
    use_legora_workflow=False  # Старый workflow
)
```

## Проверка миграции

### Чеклист

- [ ] Все новые узлы созданы и работают
- [ ] Граф обновлен с новыми edges
- [ ] Coordinator использует delivery_result
- [ ] Table Creator создает таблицы автоматически
- [ ] ReportGenerator интегрирован в DELIVER
- [ ] Legal Research tools доступны для агентов
- [ ] DeepAgents работают для сложных задач
- [ ] Обратная совместимость сохранена

### Тестирование

1. **Unit тесты** (создать):
   - test_understand_node.py
   - test_plan_node.py
   - test_deliver_node.py
   - test_deep_reasoning_agent.py
   - test_legal_research_tool.py

2. **Integration тесты** (создать):
   - test_legora_workflow.py - полный workflow

## Известные ограничения

1. **DeepAgentExecutor**: Требует langchain-experimental. Если недоступен, используется fallback на ReAct agent.

2. **Legal Research Sources**: MoyArbitrSource и VASPracticeSource используют web_search как fallback. В production нужна интеграция с реальными API.

3. **Table Creator**: Требует user_id для создания таблиц. Если не указан, используется "system".

## Troubleshooting

### Проблема: LEGORA workflow не запускается
**Решение**: Проверить, что `use_legora_workflow=True` в `create_analysis_graph()`

### Проблема: delivery_result пустой
**Решение**: Проверить, что DELIVER узел выполнился (должен быть после evaluation)

### Проблема: Таблицы не создаются
**Решение**: Проверить, что TabularReviewService инициализирован и user_id указан

### Проблема: Legal Research не работает
**Решение**: Проверить, что SourceRouter инициализирован с новыми источниками

## Дальнейшее развитие

1. **Реальная интеграция с МойАрбитр API**
2. **Кэширование результатов Legal Research**
3. **Batch processing для Table Creator**
4. **Performance оптимизация**
5. **Расширенное тестирование**

