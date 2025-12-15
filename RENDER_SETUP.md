# Настройка Legal AI Vault на Render

## Backend (Python FastAPI)

### Настройка Web Service на Render (через Dashboard):

1. Зайдите в Render Dashboard → New → Web Service
2. Подключите репозиторий: `https://github.com/semenandronov/legaltech`
3. Настройки:
   - **Name**: `legal-ai-vault-backend`
   - **Runtime**: `Python 3`
   - **Region**: Выберите ближайший регион
   - **Branch**: `main`
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Environment Variables:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
OPENAI_API_KEY=sk-xxxxx
CORS_ORIGINS=https://your-frontend-url.vercel.app,http://localhost:5173
```

### После деплоя:

База данных инициализируется автоматически при первом запуске (в `app/main.py` вызывается `init_db()`).

Если нужно инициализировать вручную:
- Используйте Render Shell: `python init_db.py`

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

