# Переменные окружения (Environment Variables)

## Обязательные переменные

### База данных
```env
DATABASE_URL="postgresql://user:password@host:5432/database_name?schema=public"
```
**Описание:** URL подключения к PostgreSQL базе данных.  
**Пример для Render:** Используйте connection string из вашей PostgreSQL базы данных на Render.

### NextAuth.js (Аутентификация)
```env
NEXTAUTH_URL="https://your-app.onrender.com"
```
**Описание:** Полный URL вашего приложения.  
**Для Render:** URL вашего сервиса (например: `https://legaltech-xxxx.onrender.com`)

```env
NEXTAUTH_SECRET="your-secret-key-here-min-32-characters"
```
**Описание:** Секретный ключ для шифрования JWT токенов.  
**Генерация:** Можно сгенерировать командой: `openssl rand -base64 32`  
**Важно:** Должен быть минимум 32 символа!

## Опциональные переменные (для AI функций)

### OpenAI API
```env
OPENAI_API_KEY="sk-..."
```
**Описание:** API ключ OpenAI для использования GPT-4o.  
**Без ключа:** Приложение будет использовать моки (mock данные) для разработки.

```env
OPENAI_MODEL="gpt-4o"
```
**Описание:** Модель OpenAI для использования.  
**По умолчанию:** `gpt-4o`  
**Другие варианты:** `gpt-4-turbo`, `gpt-4`, `gpt-3.5-turbo`

### Yandex Cloud API (для обработки изображений, аудио, видео)
```env
YANDEX_API_KEY="your-yandex-oauth-token"
```
**Описание:** OAuth токен для Yandex Cloud API.  
**Без ключа:** Функции обработки через Yandex будут недоступны.

```env
YANDEX_FOLDER_ID="your-folder-id"
```
**Описание:** ID папки в Yandex Cloud.  
**Где найти:** В консоли Yandex Cloud → Cloud ID → Folder ID

```env
YANDEX_IAM_TOKEN="your-iam-token"
```
**Описание:** IAM токен для Yandex Cloud (альтернатива API ключу).  
**Примечание:** Если указан `YANDEX_IAM_TOKEN`, `YANDEX_API_KEY` не требуется.

## Опциональные переменные (настройки приложения)

### Размер файлов
```env
MAX_FILE_SIZE=10485760
```
**Описание:** Максимальный размер загружаемого файла в байтах.  
**По умолчанию:** `10485760` (10 MB)

### Разрешенные типы файлов
```env
ALLOWED_FILE_TYPES="pdf,docx,txt"
```
**Описание:** Список разрешенных типов файлов через запятую.  
**По умолчанию:** `pdf,docx,txt`

## Настройка на Render

### Шаг 1: Перейдите в настройки сервиса
1. Откройте ваш сервис в [Render Dashboard](https://dashboard.render.com)
2. Перейдите в раздел **Environment**

### Шаг 2: Добавьте переменные окружения

**Минимальный набор (для работы без AI):**
```env
DATABASE_URL=postgresql://...
NEXTAUTH_URL=https://your-app.onrender.com
NEXTAUTH_SECRET=your-secret-key-here
```

**Полный набор (с AI функциями):**
```env
DATABASE_URL=postgresql://...
NEXTAUTH_URL=https://your-app.onrender.com
NEXTAUTH_SECRET=your-secret-key-here
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
YANDEX_API_KEY=your-yandex-token
YANDEX_FOLDER_ID=your-folder-id
MAX_FILE_SIZE=10485760
ALLOWED_FILE_TYPES=pdf,docx,txt
```

### Шаг 3: Получение DATABASE_URL на Render

1. Создайте PostgreSQL базу данных в Render
2. В настройках базы данных найдите **Internal Database URL** или **External Database URL**
3. Скопируйте connection string в переменную `DATABASE_URL`

**Важно:** 
- Используйте **Internal Database URL** если база данных и приложение в одном регионе
- Используйте **External Database URL** если база данных в другом регионе или для локальной разработки

## Генерация NEXTAUTH_SECRET

Вы можете сгенерировать секретный ключ несколькими способами:

**В терминале:**
```bash
openssl rand -base64 32
```

**Или онлайн:**
- Используйте любой генератор случайных строк (минимум 32 символа)

## Проверка переменных окружения

После настройки переменных окружения на Render:
1. Перезапустите сервис (Render автоматически перезапустит при изменении переменных)
2. Проверьте логи на наличие ошибок
3. Убедитесь, что приложение успешно подключилось к базе данных

## Важные замечания

1. **Безопасность:** Никогда не коммитьте `.env` файл в Git
2. **NEXTAUTH_SECRET:** Должен быть уникальным и секретным для каждого окружения
3. **DATABASE_URL:** Должен быть правильным connection string для вашей базы данных
4. **OPENAI_API_KEY:** Без этого ключа приложение будет работать с моками (для разработки это нормально)
5. **Yandex API:** Опционально, требуется только для обработки изображений/аудио/видео

