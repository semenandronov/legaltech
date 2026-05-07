# Комплексная проверка workflow и Deep Agents

Документ фиксирует результаты аудита кода и чеклисты приёмки. Обновлять при изменении маршрутов `workflow_agentic` или `ExecutionEngine`.

## 1. Продуктовый путь (HTTP): `create_deep_agent` end-to-end

| Шаг | Компонент | Примечание |
|-----|-----------|------------|
| Клиент | `POST /api/workflow-agentic/execute` | Создаёт execution (`start_workflow`), статус `planning`. |
| Клиент | `GET /api/workflow-agentic/executions/{id}/stream` | При `status == planning` запускает раннер. |
| Раннер | [`workflow_agentic.py`](../app/routes/workflow_agentic.py) `event_generator` | Единственный вызов: `engine.plan_and_execute(execution, definition, documents)`. |
| Рантайм | [`execution_engine.py`](../app/services/workflows/execution_engine.py) `plan_and_execute` | Строит промпт, `WorkflowDeepAgentsHarness.create_agent` → `deepagents.create_deep_agent`, `agent.astream`, [`deepagents_stream_bridge`](../app/services/workflows/deepagents_stream_bridge.py). |

**Вывод:** для основного UI-потока (execute + SSE) используется **только** `plan_and_execute` и пакет **`deepagents`** через harness. Других веток в `workflow_agentic` для стрима нет.

## 2. Что не является частью этого рантайма

| Компонент | Статус относительно HTTP workflow |
|-----------|-----------------------------------|
| `ExecutionEngine.execute(execution, plan)` | Метод есть в классе; **вызовов из `workflow_agentic` и остального backend нет** — для текущего API мёртвый путь. |
| `ExecutionEngine.execute_with_supervisor` | **Нигде не вызывается** (только определение в `execution_engine.py`). |
| `POST /api/workflow-agentic/plan` | [`DeepAgentsPlanningService.create_plan`](../app/services/workflows/deepagents_planning_service.py) → фактически **`PlanningAgent.create_plan`**, не `create_deep_agent`. Имя сервиса — адаптер контрактов. |
| `WORKFLOW_DEEPAGENTS_ENABLED` | Задаётся в [`config.py`](../app/config.py), **нигде в `.py` не читается** — не переключает раннер. См. комментарий в config. |

## 3. Конфигурация (сверка с `.env`)

Проверять согласованность с [`config.py`](../app/config.py) и [`.env.example`](../../../.env.example):

- Зависимости: `deepagents`, `langgraph`, `langchain` — [`requirements-core.txt`](../requirements-core.txt).
- `WORKFLOW_DEEPAGENTS_CHECKPOINTER_ENABLED` — async Postgres vs `MemorySaver` (логи в `plan_and_execute`).
- `WORKFLOW_DEEPAGENTS_TODO_ENABLED`, `WORKFLOW_DEEPAGENTS_MIDDLEWARE`, лимиты вызовов — [`deepagents_harness.py`](../app/services/workflows/deepagents_harness.py).
- `WORKFLOW_DEEPAGENTS_HITL_ENABLED` — пауза для юриста при провале QG после лимита итераций ([`execution_engine.py`](../app/services/workflows/execution_engine.py)).
- `WORKFLOW_DEEPAGENTS_LANGSMITH_TRACING` — трассировка (по умолчанию выключена в harness).

Флаги `WORKFLOW_DEEPAGENTS_PLANNING_ENABLED` и `WORKFLOW_DEEPAGENTS_QUALITY_GATES_ENABLED` в коде **не используются** для ветвления (в отличие от HITL); quality gates в `plan_and_execute` выполняются встроенным циклом.

## 4. Ручная приёмка (сквозной сценарий)

Выполняется вручную на стенде с реальным LLM и документами в деле:

1. Загрузить минимум один файл, запустить workflow (`execute`), открыть SSE (`stream`).
2. Убедиться в событиях: `started`, статусы про DeepAgents, затем `planning_started` / инструменты (`tool_reasoned`, `step_started`, `step_completed`) из bridge.
3. При включённом todo: события `agent_todos_updated` и блок «Подзадачи агента» в UI.
4. Финал: `completed` / `completed_with_errors` / `failed`, артефакты и `run_stats` в данных.
5. Второй клиент SSE: только poll до terminal — ожидаемо по [`workflow_agentic.py`](../app/routes/workflow_agentic.py) (не другой рантайм).

## 5. Автоматические тесты

```bash
cd backend && python3 -m pytest tests/test_deepagents_harness_unittest.py tests/test_workflow_deepagents_contracts.py -q
```

Контракт SSE: [`WORKFLOW_DEEPAGENTS_EVENT_CONTRACT.md`](WORKFLOW_DEEPAGENTS_EVENT_CONTRACT.md).

## 6. Пробелы / возможные доработки

- Унифицировать нейминг: комментарий в stream раннере раньше ссылался на PlanningAgent; фактически исполняется **DeepAgents harness** (`plan_and_execute`).
- Если нужен master-switch на уровне env: подключить `WORKFLOW_DEEPAGENTS_ENABLED` к раннеру или удалить флаг из доков как «зарезервировано».
- Эндпоинт `/plan` не строит граф `create_deep_agent`; при требовании «везде deepagents» — отдельная задача на продукт.

---

*Аудит маршрутов и конфигурации зафиксирован в репозитории; дата актуальности — по git history этого файла.*
