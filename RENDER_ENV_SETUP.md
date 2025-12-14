# Настройка переменных окружения для Render

## DATABASE_URL для Neon PostgreSQL

Ваш connection string:
```
postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

**Для Render используйте:**
```env
DATABASE_URL="postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&schema=public"
```

**Изменения:**
- Убран параметр `channel_binding=require` (используется только в psql)
- Добавлен параметр `schema=public` (требуется для Prisma)

## Полный список переменных для Render

### Обязательные:
```env
DATABASE_URL="postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&schema=public"
NEXTAUTH_URL="https://your-app-name.onrender.com"
NEXTAUTH_SECRET="your-generated-secret-key-here-min-32-characters"
```

### Опциональные (для AI):
```env
OPENAI_API_KEY="sk-..."
OPENAI_MODEL="gpt-4o"
YANDEX_API_KEY=""
YANDEX_FOLDER_ID=""
```

## Генерация NEXTAUTH_SECRET

Выполните в терминале:
```bash
openssl rand -base64 32
```

Или используйте онлайн генератор (минимум 32 символа).

## Шаги настройки на Render:

1. **Откройте ваш сервис** в [Render Dashboard](https://dashboard.render.com)
2. **Перейдите в Environment** (в боковом меню)
3. **Добавьте переменные:**
   - Нажмите "Add Environment Variable"
   - Добавьте каждую переменную по отдельности
4. **После добавления всех переменных:**
   - Render автоматически перезапустит сервис
   - Проверьте логи на наличие ошибок

## Важно:

- **NEXTAUTH_URL** должен быть точным URL вашего Render сервиса (например: `https://legaltech-xxxx.onrender.com`)
- **DATABASE_URL** должен содержать `schema=public` для Prisma
- После настройки переменных выполните миграции: `npx prisma migrate deploy` (если нужно)

