# Настройка Legal AI Vault на Render

## Backend (Python FastAPI)

### Настройка Web Service на Render:

1. **Тип сервиса**: Web Service
2. **Runtime**: Python 3
3. **Build Command**: `pip install -r backend/requirements.txt`
4. **Start Command**: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Root Directory**: `backend`

### Environment Variables:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
OPENAI_API_KEY=sk-xxxxx
CORS_ORIGINS=https://your-frontend-url.vercel.app,http://localhost:5173
```

### После деплоя:

1. Инициализируйте базу данных:
   - Подключитесь к серверу через SSH или используйте Render Shell
   - Выполните: `python backend/init_db.py`

Или создайте отдельный скрипт для автоматической инициализации при первом запуске.

## Frontend (React + Vite)

### Настройка Static Site на Render (или используйте Vercel):

**Вариант 1: Render Static Site**

1. **Тип сервиса**: Static Site
2. **Build Command**: `cd frontend && npm install && npm run build`
3. **Publish Directory**: `frontend/dist`
4. **Root Directory**: `frontend`

**Вариант 2: Vercel (рекомендуется)**

1. Подключите репозиторий к Vercel
2. Root Directory: `frontend`
3. Build Command: `npm install && npm run build`
4. Output Directory: `dist`
5. Environment Variable: `VITE_API_URL=https://your-backend.onrender.com`

### Обновление API URL в frontend:

После деплоя backend, обновите URL в `frontend/src/components/UploadArea.tsx` и `ChatWindow.tsx`:

```typescript
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
```

