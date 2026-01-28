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

## Проверка
После применения одного из решений:
1. Запустите новый деплой на Railway
2. Проверьте логи сборки - не должно быть ошибки `pip: not found`
3. Убедитесь, что сборка проходит успешно

