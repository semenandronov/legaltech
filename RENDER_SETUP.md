# Настройка переменных окружения для Render

## Быстрая настройка

### 1. Обязательные переменные (установить вручную в Render Dashboard)

Перейдите в ваш сервис на Render → Environment → Add Environment Variable:

| Переменная | Описание | Где получить |
|-----------|----------|--------------|
| `DATABASE_URL` | URL PostgreSQL базы данных | Render Dashboard → PostgreSQL → Internal Database URL |
| `OPENROUTER_API_KEY` | API ключ OpenRouter | [openrouter.ai](https://openrouter.ai) → API Keys |
| `JWT_SECRET_KEY` | Секретный ключ для JWT (минимум 32 символа) | Сгенерировать: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### 2. Автоматически установленные переменные

Эти переменные уже настроены в `render.yaml` и будут установлены автоматически:

- `OPENROUTER_MODEL` = `openrouter/auto`
- `OPENROUTER_BASE_URL` = `https://openrouter.ai/api/v1`
- `JWT_ALGORITHM` = `HS256`
- `ACCESS_TOKEN_EXPIRE_MINUTES` = `1440`
- `CORS_ORIGINS` = `*`
- `AGENT_ENABLED` = `true` ⭐ **Новое для агентной системы**
- `AGENT_MAX_PARALLEL` = `3` ⭐ **Новое**
- `AGENT_TIMEOUT` = `300` ⭐ **Новое**
- `AGENT_RETRY_COUNT` = `2` ⭐ **Новое**
- `VECTOR_DB_DIR` = `/tmp/vector_db` ⭐ **Новое**

### 3. Опциональные настройки (при необходимости)

Если нужно изменить значения по умолчанию, добавьте в Render Dashboard:

- `AGENT_ENABLED` = `false` (если хотите отключить агентную систему)
- `CORS_ORIGINS` = `https://yourdomain.com` (для production, вместо `*`)

## Проверка после деплоя

1. Проверьте логи в Render Dashboard на наличие ошибок
2. Проверьте health endpoint: `https://your-app.onrender.com/api/health`
3. Если агенты не работают, проверьте что `AGENT_ENABLED=true` и `OPENROUTER_API_KEY` установлен

## Важные замечания

⚠️ **Безопасность:**
- `JWT_SECRET_KEY` должен быть уникальным и длинным (минимум 32 символа)
- В production измените `CORS_ORIGINS` на конкретные домены вместо `*`

⚠️ **Векторная БД:**
- `VECTOR_DB_DIR=/tmp/vector_db` - данные будут теряться при перезапуске
- Для production рассмотрите внешнее хранилище (S3, etc.)

Подробная документация: см. `backend/RENDER_ENV_VARS.md`
