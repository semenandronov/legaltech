# Инструкции по деплою на Railway

## Проблема
Railway не может найти `pip` при сборке проекта, потому что Railpack не правильно определяет Python окружение для монорепо (backend + frontend).

## Решения

### Решение 1: Использовать Dockerfile (Рекомендуется)
Railway автоматически обнаружит `Dockerfile` в корне проекта и использует его для сборки. Это самый надежный способ.

1. Убедитесь, что `Dockerfile` находится в корне проекта
2. Railway автоматически использует его для сборки

### Решение 2: Установить Root Directory в настройках Railway
1. Откройте настройки вашего сервиса в Railway
2. Установите **Root Directory** на `backend/`
3. Обновите команды сборки и запуска:
   - Build Command: `pip install --upgrade pip && pip install -r requirements.txt && cd ../frontend && npm install --legacy-peer-deps && npm run type-check && npm run build`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Решение 3: Использовать nixpacks.toml
Файл `nixpacks.toml` уже создан в корне проекта. Railway должен автоматически использовать его для конфигурации сборки.

## Настройка переменных окружения

После успешного деплоя необходимо настроить переменные окружения в Railway:

### Обязательные переменные для работы приложения:

1. **YANDEX_API_KEY** или **YANDEX_IAM_TOKEN** (хотя бы одна)
   - Получите API ключ в [Yandex Cloud Console](https://console.cloud.yandex.ru/)
   - Или создайте IAM токен (действителен 12 часов)

2. **YANDEX_FOLDER_ID**
   - ID папки в Yandex Cloud, где будут создаваться ресурсы

3. **DATABASE_URL**
   - Строка подключения к PostgreSQL базе данных
   - Формат: `postgresql://user:password@host:port/database`

4. **JWT_SECRET_KEY**
   - Секретный ключ для JWT токенов (используйте случайную строку)

### Дополнительные переменные (опционально):

- **GIGACHAT_CREDENTIALS** - Учетные данные для GigaChat (Сбер)
- **GARANT_API_KEY** - API ключ для ГАРАНТ API
- **LANGSMITH_API_KEY** - API ключ для LangSmith (мониторинг)
- **VITE_API_URL** - URL API для frontend (обычно URL вашего Railway сервиса)

### Как настроить переменные в Railway:

1. Откройте ваш проект в Railway
2. Перейдите в раздел **Variables**
3. Добавьте каждую переменную:
   - Нажмите **+ New Variable**
   - Введите имя переменной (например, `YANDEX_API_KEY`)
   - Введите значение
   - Нажмите **Add**

После добавления переменных Railway автоматически перезапустит сервис.

## Проверка
После применения одного из решений:
1. Запустите новый деплой на Railway
2. Проверьте логи сборки - не должно быть ошибки `pip: not found`
3. Убедитесь, что сборка проходит успешно
4. Настройте переменные окружения
5. Проверьте логи запуска - приложение должно запуститься без ошибок

