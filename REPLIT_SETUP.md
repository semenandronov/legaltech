# Настройка проекта в Replit

## Быстрый старт

1. Импортируйте репозиторий в Replit
2. Установите зависимости: `npm install`
3. Настройте переменные окружения (см. ниже)
4. Запустите миграции: `npx prisma migrate dev`
5. Запустите проект: `npm run dev`

## Переменные окружения

Создайте файл `.env` в корне проекта со следующими переменными:

```env
# Database (Replit предоставляет PostgreSQL через Secrets)
DATABASE_URL="postgresql://user:password@localhost:5432/legal_ai"

# NextAuth
NEXTAUTH_URL="https://your-repl-name.repl.co"
NEXTAUTH_SECRET="your-secret-key-here-generate-random-string"

# OpenAI (опционально)
OPENAI_API_KEY=""
OPENAI_MODEL="gpt-4o"

# Yandex Cloud (опционально)
YANDEX_API_KEY=""
YANDEX_FOLDER_ID=""
YANDEX_IAM_TOKEN=""

# File Upload
MAX_FILE_SIZE=10485760
ALLOWED_FILE_TYPES="pdf,docx,txt"
```

## Настройка в Replit

### 1. Secrets (Переменные окружения)

В Replit перейдите в раздел Secrets и добавьте все переменные из `.env.example`

### 2. База данных

Replit не предоставляет PostgreSQL по умолчанию. Варианты:

**Вариант 1: Использовать внешнюю БД (рекомендуется)**
- Supabase (бесплатный tier)
- Neon (бесплатный tier)
- Railway (бесплатный tier)

**Вариант 2: Использовать SQLite для разработки**
- Измените `provider` в `prisma/schema.prisma` на `"sqlite"`
- Удалите `embedding` поле (не поддерживается в SQLite)

### 3. Запуск

После настройки переменных окружения:

```bash
npm install
npx prisma generate
npx prisma migrate dev
npm run dev
```

## Важные замечания

1. **PostgreSQL**: Replit не предоставляет PostgreSQL по умолчанию. Используйте внешний сервис или SQLite для разработки.

2. **Порты**: Replit автоматически назначает порт. Используйте переменную `PORT` из окружения.

3. **Файлы**: Replit имеет ограничения на размер файлов. Убедитесь, что загружаемые файлы не превышают лимиты.

4. **Таймауты**: Длительные операции (обработка больших документов) могут превышать таймауты Replit.

## Troubleshooting

### Ошибка при установке зависимостей
- Убедитесь, что используете Node.js 18+
- Попробуйте очистить кэш: `rm -rf node_modules package-lock.json && npm install`

### Ошибка Prisma
- Убедитесь, что `DATABASE_URL` правильно настроен
- Выполните `npx prisma generate` после установки зависимостей

### Ошибка сборки Next.js
- Проверьте, что все зависимости установлены
- Убедитесь, что TypeScript компилируется без ошибок: `npm run lint`

