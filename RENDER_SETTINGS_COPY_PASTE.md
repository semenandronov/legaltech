# 📋 Настройки для Render - Скопируйте и вставьте

## Root Directory
```
.
```

## Build Command
```bash
pip install -r backend/requirements.txt && cd frontend && npm install && npm run build
```

## Start Command
```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

---

## Пошаговая инструкция

1. **Root Directory**: Уже правильно установлено (`.`)

2. **Build Command**: Замените на:
   ```
   pip install -r backend/requirements.txt && cd frontend && npm install && npm run build
   ```

3. **Start Command**: Замените на:
   ```
   cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

4. Нажмите **"Update Fields"**

5. После сохранения нажмите **"Manual Deploy"** → **"Deploy latest commit"**

## Что происходит при сборке

1. ✅ Устанавливаются Python зависимости из `backend/requirements.txt`
2. ✅ Устанавливаются Node.js зависимости в `frontend/`
3. ✅ Собирается frontend (React) в `frontend/dist/`
4. ✅ Запускается FastAPI, который раздает и API, и статику frontend

## После деплоя

- `https://your-app.onrender.com/` - главная страница (frontend)
- `https://your-app.onrender.com/api/health` - API health check
- `https://your-app.onrender.com/api/upload` - загрузка файлов
- `https://your-app.onrender.com/api/chat` - чат с AI

**Важно**: `/dashboard` больше не существует! Главная страница - это `/` (корень).

