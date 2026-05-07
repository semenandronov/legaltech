# Workflow DeepAgents Event Contract

Этот документ фиксирует канонический контракт событий workflow для фронтенда и SSE.

## Обязательные поля события

- `type` (`string`) — тип события.
- `event_type` (`string`) — алиас `type` для совместимости.
- `execution_id` (`string`) — идентификатор выполнения.
- `step_id` (`string | null`) — идентификатор шага (если применимо).
- `timestamp` (`ISO datetime`) — время события.
- `progress_percent` (`number`) — прогресс 0..100.
- `progress` (`number`) — алиас `progress_percent`.
- `message` (`string`) — человекочитаемое описание.
- `data` (`object`) — полезная нагрузка.

## Типы событий

- Жизненный цикл: `started`, `status`, `completed`, `failed`
- Шаги: `tool_reasoned`, `step_started`, `step_completed`, `step_failed`
- Подзадачи DeepAgents (LangChain `write_todos` / `TodoListMiddleware`): `agent_todos_updated`
- Качество/перепланирование: `quality_gate_started`, `review_iteration_started`, `review_iteration_failed`, `review_iteration_passed`, `replan_started`, `replan_applied`
- HITL: `hitl_pause`, `hitl_resume`, `waiting_for_lawyer`

## Terminal contract (`completed` / `failed`)

`data` обязана содержать:

- `summary` (`string`)
- `artifacts` (`object`) c ключами `documents|tables|reports|checks`
- `error` (`string | null`)

Дополнительно может содержать:

- `results` (`object`) — агрегированные результаты шагов.
- `run_stats` (`object`) — метрики выполнения (`total_steps`, `deepagents_steps`, `total_llm_calls`, `total_tokens_used`, `forced_finalize`).

### `agent_todos_updated`

Эмитится при изменении списка подзадач агента (снимок из стрима `updates`, поле `todos` в состоянии графа).

`data` содержит:

- `todos` (`array`) — до 48 элементов, каждый: `{ "content": string, "status": string }` (`status` — например `pending`, `in_progress`, `completed` в зависимости от версии LangChain).

UI держит последний снимок и показывает его отдельно от «Плана workflow» (контекст БД / `planOutline`).

## UI-правила

- `completed` и `failed` считаются terminal-событиями.
- UI применяет terminal-состояние ровно один раз (`exactly-once`).
- Polling используется только как fallback при потере/тишине SSE.
