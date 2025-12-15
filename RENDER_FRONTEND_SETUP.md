# 🚨 ВАЖНО: Frontend не развернут!

## Проблема

Сейчас на Render развернут только **backend** (FastAPI). Frontend (React) нужно развернуть отдельно.

Когда вы открываете `https://legaltech-ynit.onrender.com/dashboard`, вы получаете 404, потому что:
- `/dashboard` - это был старый Next.js роут, которого больше нет
- Сейчас проект использует FastAPI backend + React frontend
- Frontend не развернут на Render

## Решение: Развернуть Frontend на Render

### Вариант 1: Использовать Render Blueprint (render.yaml)

Я уже добавил конфигурацию frontend в `render.yaml`. Если вы используете Render Blueprint:

1. Зайдите в Render Dashboard
2. Найдите ваш Blueprint
3. Нажмите "Apply" или "Update"
4. Render создаст два сервиса:
   - `legal-ai-vault-backend` (уже существует)
   - `legal-ai-vault-frontend` (будет создан)

### Вариант 2: Создать Static Site вручную

1. Зайдите в Render Dashboard → **New → Static Site**
2. Подключите репозиторий: `https://github.com/semenandronov/legaltech`
3. Настройки:
   - **Name**: `legal-ai-vault-frontend`
   - **Branch**: `main`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Publish Directory**: `dist`

### Вариант 3: Создать Web Service для Frontend

1. Зайдите в Render Dashboard → **New → Web Service**
2. Подключите репозиторий: `https://github.com/semenandronov/legaltech`
3. Настройки:
   - **Name**: `legal-ai-vault-frontend`
   - **Runtime**: **Node.js**
   - **Branch**: `main`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Start Command**: `npx serve -s dist -l $PORT`

### Environment Variables для Frontend

Добавьте переменную окружения:
```
VITE_API_URL=https://legaltech-ynit.onrender.com
```

(Замените `legaltech-ynit.onrender.com` на URL вашего backend сервиса)

### После деплоя

Frontend будет доступен по адресу типа: `https://legal-ai-vault-frontend.onrender.com`

**Главная страница будет на `/` (корень), а не `/dashboard`!**

## Альтернатива: Vercel (рекомендуется для React)

1. Подключите репозиторий к Vercel
2. Root Directory: `frontend`
3. Build Command: `npm install && npm run build`
4. Output Directory: `dist`
5. Environment Variable: `VITE_API_URL=https://legaltech-ynit.onrender.com`

## Проверка

После развертывания frontend должен открываться на главной странице без ошибок 404.

**Важно**: В новом проекте нет роута `/dashboard`. Главная страница - это `/` (корень).
