# Развертывание на одном Web Service

## ✅ Преимущества

- **Один сервис** вместо двух (проще и дешевле)
- **Один URL** для всего приложения
- **Нет проблем с CORS** между frontend и backend
- **Проще настройка** - все в одном месте

## Как это работает

1. **Build команда** собирает и backend, и frontend:
   ```bash
   pip install -r backend/requirements.txt &&
   cd frontend && npm install && npm run build
   ```

2. **Start команда** запускает только FastAPI:
   ```bash
   cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

3. **FastAPI раздает статику** из `frontend/dist`:
   - API endpoints: `/api/*`
   - Статические файлы: `/static/*`
   - Frontend SPA: все остальные пути → `index.html`

## Настройка на Render

1. Создайте **Web Service** (не Static Site!)
2. Подключите репозиторий
3. Настройки:
   - **Runtime**: Python 3
   - **Root Directory**: `.` (корень проекта)
   - **Build Command**: `pip install -r backend/requirements.txt && cd frontend && npm install && npm run build`
   - **Start Command**: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

4. Environment Variables:
   ```
   DATABASE_URL=postgresql://...
   OPENAI_API_KEY=sk-xxxxx
   CORS_ORIGINS=*
   ```

## Структура URL

- `https://your-app.onrender.com/` - главная страница (frontend)
- `https://your-app.onrender.com/api/health` - API health check
- `https://your-app.onrender.com/api/upload` - загрузка файлов
- `https://your-app.onrender.com/api/chat` - чат с AI

Все работает на одном домене! 🎉

