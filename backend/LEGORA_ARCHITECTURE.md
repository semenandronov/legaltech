# LEGORA Architecture

## Обзор

LEGORA (Legal Graph Orchestration and Reasoning Architecture) - это полная реализация workflow для юридической AI-системы на базе LangGraph и LangChain.

## Архитектура Workflow

```
User Request → UNDERSTAND → PLAN → EXECUTE → VERIFY → DELIVER → Table + Summary
```

### Фазы Workflow

#### 1. UNDERSTAND (understand_node.py)
- **Назначение**: Парсинг и анализ запроса пользователя
- **Функции**:
  - Анализ задачи пользователя
  - Определение сложности (simple/medium/high)
  - Определение типа задачи (extraction/analysis/comparison/research)
  - Извлечение целей
  - Анализ документов для контекста

#### 2. PLAN (plan_node.py)
- **Назначение**: Создание плана анализа на основе понимания
- **Функции**:
  - Использование understanding_result из UNDERSTAND фазы
  - Создание детального плана через PlanningAgent
  - Определение зависимостей между анализами
  - Сохранение плана в state["current_plan"]

#### 3. EXECUTE
- **Назначение**: Выполнение специализированных агентов
- **Агенты**:
  - timeline - хронология событий
  - key_facts - ключевые факты
  - discrepancy - противоречия
  - risk - анализ рисков
  - summary - резюме
  - document_classifier - классификация документов
  - entity_extraction - извлечение сущностей
  - privilege_check - проверка привилегий
  - relationship - граф связей
  - deep_analysis - глубокий анализ (для сложных задач)

#### 4. VERIFY (evaluation_node.py)
- **Назначение**: Оценка качества результатов
- **Функции**:
  - 4-уровневая валидация
  - Проверка confidence
  - Определение необходимости адаптации

#### 5. DELIVER (deliver_node.py)
- **Назначение**: Финальная обработка и форматирование
- **Функции**:
  - Создание таблиц через Table Creator
  - Генерация отчетов через ReportGenerator
  - Форматирование результатов для пользователя

## Компоненты

### Deep Reasoning Agent (deep_reasoning_agent.py)
Для сложных многошаговых задач:
- Разбивает задачу на подзадачи
- Выполняет многошаговое рассуждение
- Синтезирует результаты из разных источников

### Legal Research Tool (legal_research_tool.py)
Поиск прецедентов и case law:
- МойАрбитр - судебные решения
- ВАС практика - практика Высшего Арбитражного Суда
- ЕГРЮЛ - информация о компаниях
- Fedres - информация о банкротстве

### Table Creator Tool (table_creator_tool.py)
Автоматическое создание таблиц из результатов анализа:
- Timeline таблицы
- Key Facts таблицы
- Discrepancy таблицы
- Risk таблицы

## Интеграция с существующей системой

### Обратная совместимость
- Флаг `use_legora_workflow` в `create_analysis_graph()`
- По умолчанию `True` (LEGORA включен)
- Старый workflow продолжает работать при `use_legora_workflow=False`

### Coordinator
- Автоматически использует `delivery_result` если доступен
- Fallback на старый формат для обратной совместимости

## Использование

```python
from app.services.langchain_agents.coordinator import AgentCoordinator

# Создать coordinator с LEGORA workflow
coordinator = AgentCoordinator(
    db=db,
    rag_service=rag_service,
    document_processor=document_processor,
    use_legora_workflow=True  # По умолчанию True
)

# Запустить анализ
results = coordinator.run_analysis(
    case_id=case_id,
    analysis_types=["timeline", "key_facts", "risk"],
    user_task="Найди все риски в документах"
)

# Результаты содержат delivery_result если LEGORA workflow использовался
if results.get("workflow") == "legora":
    tables = results.get("tables", {})
    reports = results.get("reports", {})
    summary = results.get("summary", "")
```

## Расширение

### Добавление новых источников Legal Research
1. Создать класс, наследующий `BaseSource` в `backend/app/services/external_sources/`
2. Зарегистрировать в `initialize_source_router()`
3. Добавить в `legal_research_tool.py` если нужно

### Добавление новых типов таблиц
1. Добавить метод в `TabularReviewService`
2. Обновить `table_creator_tool.py`
3. Интегрировать в `deliver_node.py`

