# Workflow DeepAgents Filesystem Permissions

Документ фиксирует политику файлового доступа для DeepAgents runtime в workflow.

## Базовый режим

- Политика `deny_by_default`.
- Разрешения выдаются только через явные префиксы.
- Конфигурация управляется переменными:
  - `WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED`
  - `WORKFLOW_DEEPAGENTS_ALLOWED_READ_PATHS`
  - `WORKFLOW_DEEPAGENTS_ALLOWED_WRITE_PATHS`

## Рекомендуемые префиксы

- `read`: `/memories,/tmp,/app/uploads,./uploads`
- `write`: `/memories,/tmp,./uploads`

## Контроль изоляции

- Постоянная память хранится отдельно в `WORKFLOW_DEEPAGENTS_MEMORIES_DIR` (по умолчанию `/memories`).
- Оперативное состояние не должно записываться вне разрешённых директорий.
- Попытки доступа вне policy должны отклоняться без обходных fallback в рантайме.
