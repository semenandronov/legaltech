# Настройка базы данных Neon PostgreSQL

## Вариант 1: Использование Prisma db push (рекомендуется)

Выполните на Render или локально:

```bash
export DATABASE_URL="postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&schema=public"
npx prisma db push
```

## Вариант 2: Выполнение SQL через веб-интерфейс Neon

1. Откройте [Neon Console](https://console.neon.tech)
2. Выберите ваш проект
3. Перейдите в SQL Editor
4. Скопируйте и выполните SQL из файла `prisma/migrations/init/migration.sql`

## Вариант 3: Использование psql (если установлен)

```bash
export PGPASSWORD='npg_c5L8QzZstGWd'
psql 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require' -f prisma/migrations/init/migration.sql
```

## После настройки базы данных

После успешного создания таблиц, вы можете создать тестового пользователя:

```sql
-- Создание тестового пользователя (пароль: admin123)
INSERT INTO users (id, email, name, password, role, "createdAt", "updatedAt")
VALUES (
  'test-user-1',
  'admin@example.com',
  'Admin User',
  '$2a$10$rOzJqJqJqJqJqJqJqJqJqOqJqJqJqJqJqJqJqJqJqJqJqJqJqJqJqJq', -- bcrypt hash для 'admin123'
  'ADMIN',
  NOW(),
  NOW()
);
```

**Примечание:** Пароль должен быть захеширован с помощью bcrypt. Используйте API endpoint `/api/auth/register` для создания пользователей.

