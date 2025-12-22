# Legal AI Vault MVP

Веб-приложение для анализа юридических дел с помощью AI.

## Возможности

- **Загрузка документов**: PDF, DOCX, TXT, XLSX
- **Чат с AI**: Вопросы по документам с ответами и источниками
- **История чата**: Сохранение всех вопросов и ответов

## Архитектура

- **Backend**: FastAPI (Python) на порту 8000
- **Frontend**: React + Vite + TypeScript на порту 5173
- **База данных**: PostgreSQL (Neon)

## Установка и запуск

### Backend

1. Перейдите в папку backend:
```bash
cd backend
```

2. Создайте виртуальное окружение:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env`:
```env
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxx
OPENROUTER_MODEL=openrouter/auto
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

DATABASE_URL=postgresql://user:password@localhost:5432/legal_ai_vault
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:5174
```

5. Инициализируйте базу данных:
```bash
python -c "from app.utils.database import init_db; init_db()"
```

6. Запустите backend:
```bash
uvicorn app.main:app --reload
```

Backend будет доступен на `http://localhost:8000`

### Frontend

1. Перейдите в папку frontend:
```bash
cd frontend
```

2. Установите зависимости:
```bash
npm install
```

3. Запустите frontend:
```bash
npm run dev
```

Frontend будет доступен на `http://localhost:5173`

## Использование

1. Откройте `http://localhost:5173` в браузере
2. Перетащите документы в область загрузки или выберите файлы
3. После загрузки откроется окно чата
4. Задавайте вопросы о документах
5. Получайте ответы с ссылками на источники

## API Endpoints

- `GET /` - Главная страница API
- `GET /api/health` - Проверка работоспособности
- `POST /api/upload` - Загрузка файлов
- `POST /api/chat` - Отправка вопроса
- `GET /api/chat/{case_id}/history` - История чата

## Деплой на Render

### Подготовка

1. Убедитесь, что у вас есть:
   - Аккаунт на [Render.com](https://render.com)
   - База данных PostgreSQL (можно использовать Neon или Render PostgreSQL)
   - API ключ от OpenRouter

2. Создайте файл `render.yaml` в корне проекта (уже включен в проект)

### Настройка переменных окружения в Render

В настройках сервиса на Render добавьте следующие переменные окружения:

**Обязательные:**
- `DATABASE_URL` - URL подключения к PostgreSQL
- `OPENROUTER_API_KEY` - API ключ от OpenRouter
- `JWT_SECRET_KEY` - Секретный ключ для JWT (сгенерируйте случайную строку)
- `VITE_API_URL` - URL вашего backend сервиса на Render (например: `https://your-app.onrender.com`)

**Опциональные:**
- `OPENROUTER_MODEL` - Модель для использования (по умолчанию: `openrouter/auto`)
- `CORS_ORIGINS` - Разрешенные источники для CORS (по умолчанию: `*`)
- `AGENT_ENABLED` - Включить систему агентов (по умолчанию: `true`)

Полный список переменных окружения см. в `backend/.env.example` и `frontend/.env.example`

### Деплой

1. Подключите ваш GitHub репозиторий к Render
2. Render автоматически обнаружит `render.yaml` и создаст сервис
3. Установите все переменные окружения в настройках сервиса
4. Render автоматически выполнит сборку и деплой

### Проверка деплоя

После успешного деплоя:
1. Проверьте, что backend доступен: `https://your-app.onrender.com/api/health`
2. Проверьте, что frontend загружается и подключается к backend
3. Проверьте логи в панели Render на наличие ошибок

### Troubleshooting

**Проблема: Build fails**
- Проверьте логи сборки в Render
- Убедитесь, что все зависимости установлены
- Проверьте, что `npm run type-check` проходит успешно

**Проблема: Frontend не подключается к backend**
- Проверьте переменную `VITE_API_URL` - она должна указывать на ваш backend URL
- Проверьте CORS настройки в backend
- Проверьте, что backend запущен и доступен

**Проблема: Ошибки типов TypeScript**
- Запустите `npm run type-check` локально
- Исправьте все ошибки типов перед коммитом

## Технологии

- **Backend**: FastAPI, SQLAlchemy, OpenRouter (через OpenAI-клиент), pypdf, python-docx, openpyxl
- **Frontend**: React, TypeScript, Vite, Axios, shadcn/ui
- **База данных**: PostgreSQL
