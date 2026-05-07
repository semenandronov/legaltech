# Workflow DeepAgents Production Hardening Checklist

## Rollout flags

- `WORKFLOW_DEEPAGENTS_ENABLED`
- `WORKFLOW_DEEPAGENTS_HITL_ENABLED`
- `WORKFLOW_DEEPAGENTS_CHECKPOINTER_ENABLED`
- `WORKFLOW_DEEPAGENTS_COMPOSITE_BACKEND_ENABLED`
- `WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED`

## Runtime safety

- Проверить, что terminal payload всегда содержит `summary`, `artifacts`, `error`, `run_stats`.
- Проверить, что SSE + polling дают single terminal финализацию в UI.
- Проверить, что при HITL-паузе статус фиксируется как `waiting_for_lawyer`.

## Observability

- Логировать `run_stats.total_llm_calls` и `run_stats.total_tokens_used`.
- Отслеживать частоту:
  - `hitl_pause`
  - `failed`
  - polling fallback после SSE silence.

## Rollback plan

- Отключить `WORKFLOW_DEEPAGENTS_ENABLED=false` для быстрого возврата на безопасный контур.
- При частичной деградации отключать поэтапно:
  - `WORKFLOW_DEEPAGENTS_COMPOSITE_BACKEND_ENABLED=false`
  - `WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED=false`
  - `WORKFLOW_DEEPAGENTS_CHECKPOINTER_ENABLED=false`
