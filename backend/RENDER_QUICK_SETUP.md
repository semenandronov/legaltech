# ⚡ Быстрая настройка Render (5 минут)

## 🎯 Минимальный набор переменных для работы

### 1. Открой Render Dashboard
https://dashboard.render.com → Выбери сервис → Environment

### 2. Добавь эти 4 переменные:

```bash
# 1. База данных (автоматически из PostgreSQL)
DATABASE_URL=postgresql://...

# 2. OpenRouter (fallback для LLM)
OPENROUTER_API_KEY=sk-or-v1-твой-ключ

# 3. JWT (сгенерируй: openssl rand -hex 32)
JWT_SECRET_KEY=твой-длинный-секретный-ключ-минимум-32-символа

# 4. CORS (URL твоего фронтенда)
CORS_ORIGINS=https://твой-фронтенд.onrender.com
```

**Готово!** Система будет работать через OpenRouter.

---

## 🚀 С Яндекс (экономия 90%)

Добавь еще 3 переменные:

```bash
# 5. Yandex Folder ID
YANDEX_FOLDER_ID=b1gxxxxxxxxxxxxx

# 6. Yandex IAM Token (получи: yc iam create-token)
YANDEX_IAM_TOKEN=t1.xxxxxxxxxxxxx

# 7. Yandex AI Studio Classifier (опционально)
YANDEX_AI_STUDIO_CLASSIFIER_ID=classifier-xxxxx
```

⚠️ **Важно:** IAM токен истекает через 12 часов. Для production нужен Service Account.

---

## 📋 Полный список (копируй-вставляй)

### Обязательные:
```
DATABASE_URL=postgresql://...
OPENROUTER_API_KEY=sk-or-v1-...
JWT_SECRET_KEY=...
CORS_ORIGINS=https://...
```

### Яндекс (опционально):
```
YANDEX_FOLDER_ID=b1g...
YANDEX_IAM_TOKEN=t1...
YANDEX_AI_STUDIO_CLASSIFIER_ID=classifier-...
YANDEX_GPT_MODEL=yandexgpt-pro/latest
```

### Опциональные (уже в render.yaml):
```
AGENT_ENABLED=true
AGENT_MAX_PARALLEL=3
AGENT_TIMEOUT=300
AGENT_RETRY_COUNT=2
VECTOR_DB_DIR=/tmp/vector_db
```

---

## ✅ Проверка

После добавления переменных:
1. Сохрани изменения
2. Render перезапустит сервис
3. Проверь логи: должны быть сообщения о Яндекс (если настроен)

---

## 🔐 Генерация JWT_SECRET_KEY

```bash
# В терминале:
openssl rand -hex 32

# Скопируй результат в Render
```

---

## 🆘 Проблемы?

- **"YANDEX_FOLDER_ID not set"** → Не критично, работает через OpenRouter
- **"JWT_SECRET_KEY too short"** → Используй минимум 32 символа
- **"CORS error"** → Проверь CORS_ORIGINS, должен включать URL фронтенда

Подробнее: см. `RENDER_ENV_VARIABLES.md`
