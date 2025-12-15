# 🚨 ВАЖНО: Frontend не развернут!

## Проблема

Сейчас на Render развернут только **backend** (FastAPI). Frontend (React) нужно развернуть отдельно.

## Решение: Развернуть Frontend на Render как Static Site

### Шаг 1: Создайте новый Static Site в Render Dashboard

1. Зайдите в Render Dashboard → **New → Static Site**
2. Подключите репозиторий: `https://github.com/semenandronov/legaltech`
3. Настройки:
   - **Name**: `legal-ai-vault-frontend`
   - **Branch**: `main`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Publish Directory**: `dist`

### Шаг 2: Environment Variables для Frontend

Добавьте переменную окружения:
```
VITE_API_URL=https://legaltech-ynit.onrender.com
```

(Замените `legaltech-ynit.onrender.com` на URL вашего backend сервиса)

### Шаг 3: После деплоя

Frontend будет доступен по адресу типа: `https://legal-ai-vault-frontend.onrender.com`

## Альтернатива: Vercel (рекомендуется для React)

1. Подключите репозиторий к Vercel
2. Root Directory: `frontend`
3. Build Command: `npm install && npm run build`
4. Output Directory: `dist`
5. Environment Variable: `VITE_API_URL=https://legaltech-ynit.onrender.com`

## Проверка

После развертывания frontend должен открываться на главной странице без ошибок 404.

