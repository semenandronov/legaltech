# 🚀 Быстрая настройка базы данных Neon

## Способ 1: Через веб-интерфейс Neon (САМЫЙ ПРОСТОЙ)

1. Откройте [Neon Console](https://console.neon.tech)
2. Войдите в свой аккаунт
3. Выберите проект с базой данных `neondb`
4. В левом меню нажмите **"SQL Editor"**
5. Скопируйте **весь** SQL из файла `prisma/migrations/init/migration.sql`
6. Вставьте в SQL Editor
7. Нажмите **"Run"** или **Ctrl+Enter**

✅ Готово! Все таблицы созданы.

## Способ 2: Через Render (после деплоя)

После успешного деплоя на Render, выполните в терминале Render:

```bash
npx prisma db push
```

Или добавьте в build command на Render:
```bash
yarn install && npx prisma db push && yarn build
```

## Способ 3: Локально (если установлен psql)

```bash
export PGPASSWORD='npg_c5L8QzZstGWd'
psql 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require' -f prisma/migrations/init/migration.sql
```

## Проверка успешной настройки

После выполнения миграции, проверьте что таблицы созданы:

```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
```

Должны быть созданы следующие таблицы:
- users
- documents
- document_versions
- summaries
- search_queries
- search_results
- timelines
- timeline_events
- chat_sessions
- chat_messages
- chat_prompts
- tabular_reviews
- tabular_columns
- tabular_cells

## Создание первого пользователя

После создания таблиц, создайте первого пользователя через регистрацию на сайте или через API:

```bash
POST /api/auth/register
{
  "email": "admin@example.com",
  "password": "admin123",
  "name": "Admin User"
}
```

---

**Рекомендация:** Используйте **Способ 1** (веб-интерфейс Neon) - это самый простой и быстрый способ!

