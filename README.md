# Legal AI Vault - Полная техническая документация

## О проекте

**Legal AI Vault** — это продвинутая платформа для юридических специалистов, объединяющая управление документами, AI-анализ и агентные рабочие процессы. Система построена на современной full-stack архитектуре с FastAPI backend и React frontend, интегрирована с несколькими AI провайдерами (GigaChat, Yandex Cloud) и внешними юридическими базами данных (ГАРАНТ).

---

## Содержание

- [Быстрый старт](#быстрый-старт)
- [Архитектура проекта](#архитектура-проекта)
- [Backend](#backend)
  - [Структура](#структура-backend)
  - [API Routes](#api-routes)
  - [Модели данных](#модели-данных)
  - [LangChain/LangGraph агенты](#langchainlanggraph-агенты)
  - [AI интеграции](#ai-интеграции)
- [Frontend](#frontend)
  - [Структура](#структура-frontend)
  - [Компоненты и страницы](#компоненты-и-страницы)
  - [Роутинг](#роутинг)
  - [UI библиотеки](#ui-библиотеки)
- [Стек технологий](#стек-технологий)
- [Конфигурация](#конфигурация)
- [Деплой](#деплой)
- [Основные функции](#основные-функции)

---

## Быстрый старт

### Требования

- **Python:** 3.12.8+
- **Node.js:** 20.x
- **PostgreSQL:** 14+ с расширением pgvector
- **GigaChat API** или **Yandex Cloud API** ключи

### Установка

1. **Клонирование репозитория**
```bash
git clone https://github.com/semenandronov/legaltech.git
cd legaltech
```

2. **Настройка окружения**
```bash
# Создать .env файл из примера
cp .env.example .env

# Отредактировать .env и добавить:
# - DATABASE_URL
# - GIGACHAT_CREDENTIALS или YANDEX_API_KEY
# - JWT_SECRET_KEY
```

3. **Backend установка**
```bash
# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Установить зависимости (полный стек: Docling/markitdown + PyTorch CPU — долго, но лучше PDF/PPTX)
pip install -r backend/requirements.txt

# Или только ядро без тяжёлых пакетов (быстрее; PDF в редакторе через pypdf):
# pip install -r backend/requirements-core.txt
```

4. **Frontend установка**
```bash
cd frontend
npm install --legacy-peer-deps
cd ..
```

5. **Запуск проекта**

**Backend:**
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
npm run dev
```

Приложение доступно по адресу: `http://localhost:5173`
API доступно по адресу: `http://localhost:8000/api`

---

## Архитектура проекта

### Общая структура

```
legaltech/
├── backend/           # FastAPI сервер
│   ├── app/
│   │   ├── main.py   # Точка входа
│   │   ├── config.py # Конфигурация
│   │   ├── models/   # SQLAlchemy модели
│   │   ├── routes/   # API endpoints
│   │   ├── services/ # Бизнес-логика
│   │   ├── core/     # Ядро (auth, logging, errors)
│   │   └── utils/    # Утилиты
│   ├── requirements.txt          # core + heavy (Docling); для prod см. requirements-core.txt
│   ├── requirements-core.txt
│   ├── requirements-heavy.txt
│   ├── requirements-production.txt
│   └── langgraph.json
├── frontend/          # React приложение
│   ├── src/
│   │   ├── main.tsx  # Точка входа
│   │   ├── App.tsx   # Роутинг
│   │   ├── pages/    # Страницы
│   │   ├── components/ # Компоненты
│   │   ├── services/ # API клиенты
│   │   ├── contexts/ # React контексты
│   │   └── hooks/    # Custom hooks
│   ├── package.json
│   └── vite.config.ts
├── .env.example       # Шаблон переменных окружения
├── Dockerfile         # Docker конфигурация
├── railway.json       # Railway деплой
├── render.yaml        # Render деплой
└── nixpacks.toml      # Nixpacks конфигурация
```

### Поток данных

```
┌─────────────┐
│   Frontend  │ (React + TypeScript)
│   (Vite)    │
└──────┬──────┘
       │ HTTP/SSE + JWT
       ↓
┌──────────────┐
│   Backend    │ (FastAPI + Python 3.12)
│   (Uvicorn)  │
└──────┬───────┘
       ├─→ PostgreSQL (данные + pgvector)
       ├─→ GigaChat API (основной LLM)
       ├─→ Yandex Cloud (альтернативный LLM)
       ├─→ ГАРАНТ API (юридические данные)
       └─→ LangSmith (мониторинг)
```

---

## Backend

### Структура Backend

**Расположение:** `/backend/app/`

#### Основные файлы

- **`main.py`** (530 строк) - Точка входа FastAPI
  - Настройка CORS, middleware
  - Регистрация 25+ API routes
  - Инициализация БД при старте
  - Serving статики frontend
  - Версия: v6.0.0

- **`config.py`** (351 строка) - Централизованная конфигурация
  - Валидация DATABASE_URL
  - Настройки LLM провайдеров (GigaChat, Yandex, OpenAI)
  - RAG параметры (reranking, верификация цитат)
  - Настройки мультиагентной системы
  - Rate limiting
  - JWT authentication

### API Routes

**Расположение:** `/backend/app/routes/`

25 файлов роутов (13,426 строк кода):

#### Аутентификация и пользователи
- **`auth.py`** - Регистрация, логин, обновление токенов

#### Управление документами
- **`upload.py`** - Загрузка и обработка документов
- **`documents.py`** - CRUD операции с документами
- **`cases.py`** (73,393 строки) - Управление делами
- **`folders.py`** - Папки и теги

#### AI Чат
- **`chat.py`** - Чат с ReAct агентом
- **`assistant_chat.py`** - Streaming ответы
- **`assistant_chat_v2.py`** - Улучшенная версия чата

#### Анализ и обзор
- **`analysis.py`** (53,418 строк) - Анализ документов
- **`tabular_review.py`** (77,913 строк) - Табличный обзор документов
- **`review_table.py`** - Табличный обзор

#### Редактирование
- **`document_editor.py`** - Rich text редактор документов

#### Рабочие процессы
- **`workflows.py`** - Определения workflow
- **`workflow_execution.py`** - Выполнение workflow
- **`workflow_agentic.py`** - Агентная оркестрация
- **`plan_execution.py`** - Управление планами

#### Compliance и правила
- **`playbooks.py`** - Правила проверки соответствия
- **`prompts.py`** - Управление prompt-шаблонами

#### Отчеты и дашборды
- **`reports.py`** - Генерация отчетов
- **`dashboard.py`** - Статистика дашборда

#### Инфраструктура
- **`websocket.py`** - WebSocket коммуникация
- **`metrics.py`** - Метрики системы
- **`health.py`** - Health check
- **`settings.py`** - Настройки пользователя

### Модели данных

**Расположение:** `/backend/app/models/`

Все модели наследуются от SQLAlchemy `Base`.

#### Основные модели (case.py, user.py)
- **User** - Пользователи, аутентификация, роли
- **UserSession** - Сессии и refresh токены
- **Case** - Юридические дела с метаданными
- **File** - Документы с бинарным содержимым
- **ChatMessage** - История чата с ссылками на источники

#### Анализ (analysis.py)
- **AnalysisResult** - Результаты анализа
- **DocumentChunk** - Чанки текста с pgvector embeddings
- **Discrepancy** - Обнаруженные противоречия
- **TimelineEvent** - События на временной шкале
- **DocumentClassification** - Классификация типов документов
- **ExtractedEntity** - Извлеченные сущности (даты, суммы, лица)
- **PrivilegeCheck** - Проверка привилегий
- **Risk** - Оценка рисков
- **AnalysisPlan** - Планы выполнения анализа

#### Функциональные модели
- **TabularReview** - Сессии табличного обзора (tabular_review.py)
- **WorkflowDefinition** - Шаблоны workflow (workflow.py)
- **Playbook** - Наборы правил compliance (playbook.py)
- **Document** - Документы с TipTap JSON (document_editor.py)
- **DocumentTemplate** - Шаблоны документов
- **Folder** - Иерархические папки
- **PromptTemplate** - Многоразовые промпты
- **AgentInteraction** - Human-in-the-loop взаимодействия
- **LangGraphStoreEntry** - Персистентное хранилище состояния LangGraph

### LangChain/LangGraph агенты

**Расположение:** `/backend/app/services/langchain_agents/`

#### Основные сервисы
- **`chat_graph_service.py`** (43,395 строк) - Оркестрация чат-графа
- **`tabular_graph_service.py`** - Граф табличной экстракции
- **`workflow_graph_service.py`** - Граф оркестрации workflow

#### Агенты (agents/)
- **`chat_react_agent.py`** (36,180 строк) - ReAct паттерн чат-агент
- **`tabular_extraction_agent.py`** (21,148 строк) - Экстракция данных
- **`workflow_orchestrator_agent.py`** (33,690 строк) - Координация workflow

#### Конфигурация LangGraph

**Файл:** `/backend/langgraph.json`

**3 основных графа:**
1. **chat** - Юридический ассистент с памятью
2. **tabular** - Экстракция данных из документов
3. **workflow** - Многошаговая оркестрация задач

**5 ассистентов:**
- `legal-assistant` (обычный режим)
- `deep-analyst` (режим deep_think)
- `document-drafter` (режим drafting)
- `tabular-extractor` (структурированная экстракция)
- `workflow-orchestrator` (многошаговые workflow)

### AI интеграции

#### LLM Factory (`services/llm_factory.py`)

**Основной провайдер:** GigaChat (Сбер)
- Custom wrapper совместимый с langchain-core 1.2.2
- Модели: GigaChat, GigaChat-Lite, GigaChat-Pro
- Function calling
- Rate limiting wrapper
- Connection pooling

**Альтернативные провайдеры:**
- Yandex Cloud (YandexGPT) через yandex-cloud-ml-sdk
- OpenAI (опционально, с mock-поддержкой)

#### ReAct Chat Agent v3.0

**Файл:** `services/chat/react_chat_agent.py` (41,303 строки)

**Ключевые возможности:**
- 12 универсальных инструментов
- Reflection Pattern (снижение ошибок на 30%)
- Верификация цитат
- Оценка уверенности (confidence scores)
- Deep Think режим (7 фаз)

#### Универсальные инструменты

**Файл:** `services/chat/universal_tools.py` (51,059 строк)

**12 инструментов:**

**Инструменты для работы с документами:**
1. `get_document(filename)` - Получить полный текст документа
2. `search_in_documents(query, k)` - Семантический + BM25 поиск
3. `extract_structured_data(entity_types)` - Извлечь даты, суммы, сущности
4. `compare_documents(doc1, doc2)` - Найти различия

**Юридические инструменты:**
5. `search_garant(query)` - Поиск в базе ГАРАНТ
6. `get_law_article(norm_id)` - Получить конкретную правовую норму

**Генерация документов:**
7. `generate_document(type, variables)` - Создать черновик
8. `list_templates()` - Показать доступные шаблоны

**Compliance:**
9. `validate_with_playbook(doc, playbook)` - Проверка соответствия
10. `get_user_playbooks()` - Список доступных playbooks

**Утилиты:**
11. `calculate(expression)` - Юридические расчеты (пени, проценты)
12. `get_current_date()` - Текущая дата

#### RAG Service

**Файл:** `services/rag_service.py` (73,681 строка)

**Многоступенчатый RAG pipeline:**
1. **Начальный поиск** (k=100 кандидатов)
2. **Reranking** (топ 20)
3. **Конденсация контекста** (топ 10)
4. **Финальный синтез** (топ 5)

**Возможности:**
- Гибридный поиск (семантический + BM25)
- Конденсация запроса
- Верификация цитат
- LLM-as-judge оценка релевантности
- Фильтрация по типу документа

#### Vector Store

**Файл:** `services/pgvector_store.py` (26,844 строки)

- PostgreSQL с расширением pgvector
- Размерность embeddings: 1536 (настраивается)
- Гибридный поиск (vector + BM25)
- Фильтрация по метаданным
- Отслеживание символьных смещений для точного выделения цитат
- Управление чанками с перекрытием

#### Интеграция внешних источников

**Расположение:** `services/external_sources/`

- **`garant_source.py`** (38,309 строк) - База ГАРАНТ
- **`kad_arbitr_source.py`** - База арбитражных судов
- **`pravo_gov_source.py`** (19,294 строки) - Официальное законодательство
- **`consultant_source.py`** - КонсультантПлюс
- **`vsrf_source.py`** (12,265 строк) - Верховный Суд РФ
- **`web_search.py`** (24,907 строк) - Веб-исследования
- **`source_router.py`** (13,598 строк) - Маршрутизация источников

### Аутентификация и безопасность

**Файл:** `utils/auth.py`

- JWT токены
- Refresh токены
- Хеширование паролей (bcrypt)
- Время жизни токена: 1440 минут (24 часа)
- Управление сессиями

**Функции безопасности:**
- CORS middleware
- CSP headers для защиты от XSS
- Rate limiting
- Валидация ввода (Pydantic)
- Защита от SQL injection (SQLAlchemy ORM)

---

## Frontend

### Структура Frontend

**Расположение:** `/frontend/src/`

```
src/
├── main.tsx          # Bootstrap
├── App.tsx           # Роутинг (199 строк)
├── app/              # Конфигурация приложения
├── components/       # Переиспользуемые компоненты
├── contexts/         # React context провайдеры
├── hooks/            # Custom hooks
├── lib/              # Библиотеки утилит
├── pages/            # Компоненты страниц
├── services/         # API сервисный слой
├── styles/           # Глобальные стили
├── theme/            # Конфигурация темы
└── utils/            # Вспомогательные функции
```

### Компоненты и страницы

#### Страницы (pages/)

20 файлов страниц:

- **`AssistantChatPage.tsx`** (9,254 строки) - Интерфейс AI ассистента
- **`DocumentsPage.tsx`** (38,190 строк) - Управление документами
- **`CasesListPage.tsx`** - Список дел
- **`CaseOverviewPage.tsx`** (16,626 строк) - Детали дела
- **`TabularReviewPage.tsx`** (43,435 строк) - Табличный обзор
- **`DocumentEditorPage.tsx`** (27,738 строк) - Rich text редактор
- **`PlaybooksPage.tsx`** (61,006 строк) - Управление playbooks
- **`WorkflowsPage.tsx`** (84,155 строк) - Конструктор workflow
- **`AnalysisPage.tsx`** - Анализ документов
- **`ContradictionsPage.tsx`** - Обнаружение противоречий
- **`ReportsPage.tsx`** - Генерация отчетов
- **`Dashboard.tsx`** (17,491 строка) - Дашборд
- **`LoginPage.tsx`** - Страница входа
- **`RegisterPage.tsx`** - Регистрация

#### Категории компонентов (components/)

1. **Chat/** - Компоненты чата
2. **Documents/** - Компоненты документов
3. **TabularReview/** - Табличные компоненты
4. **Editor/** - Rich text редактор
5. **Playbooks/** - Компоненты playbooks
6. **Workflows/** - Компоненты workflow
7. **Layout/** - Layout компоненты
8. **UI/** - UI библиотека (59 компонентов)
9. **Analysis/** - Компоненты анализа
10. **Common/** - Общие компоненты

### Роутинг

**Определен в:** `src/App.tsx`

```
/login                          - Вход
/register                       - Регистрация
/                               - Редирект на /cases
/cases                          - Список дел
/cases/:caseId                  - Редирект на чат
/cases/:caseId/chat             - Чат (по умолчанию)
/cases/:caseId/documents        - Документы
/cases/:caseId/editor/:docId?   - Редактор
/cases/:caseId/tabular-review   - Табличный обзор
/cases/:caseId/playbooks        - Playbooks
/cases/:caseId/workflows        - Workflows
/cases/:caseId/contradictions   - Противоречия
/cases/:caseId/analysis         - Анализ
/cases/:caseId/reports          - Отчеты
```

### UI библиотеки

#### Основной UI фреймворк
- **React 18.3.0** - UI библиотека
- **React Router v6** - Клиентский роутинг
- **Material-UI (MUI) v6.1.0** - Библиотека компонентов

#### Radix UI (Headless компоненты)
Широкое использование Radix UI для доступных компонентов:
- Accordion, Alert Dialog, Avatar
- Checkbox, Dialog, Dropdown Menu
- Popover, Select, Tabs, Tooltip
- И многое другое...

#### Специализированные библиотеки
- **TipTap** (v2.27.2) - Rich text редактор
- **@tanstack/react-table** (v8.21.3) - Продвинутые таблицы
- **@xyflow/react** (v12.10.0) - Диаграммы workflow
- **react-pdf** (v7.6.0) - Рендеринг PDF
- **recharts** (v2.15.4) - Графики
- **d3** (v7.8.5) - Визуализация данных

#### Стилизация
- **Tailwind CSS** (v3.4.0) - Utility-first CSS
- **@emotion/react** - CSS-in-JS

#### Формы
- **react-hook-form** (v7.69.0) - Управление формами
- **zod** (v4.2.1) - Валидация схем

### Интеграция с Backend API

#### API Service Layer

**Файл:** `src/services/api.ts` (25,410 строк)

- Axios instance с интерсепторами
- Автоматическая вставка JWT токена
- Обновление токена при 401
- Обработка ошибок и логирование
- Конфигурация base URL через `VITE_API_URL`

#### API модули
- `auth.ts` - Аутентификация
- `chatHistoryService.ts` - История чата
- `documentEditorApi.ts` - Editor API
- `playbooksApi.ts` - Playbook management
- `tabularReviewApi.ts` (24,254 строки)
- `workflowsApi.ts` (14,616 строк)

---

## Стек технологий

### Backend

| Категория | Технология | Версия | Назначение |
|-----------|-----------|--------|------------|
| **Framework** | FastAPI | 0.115.0 | Async API фреймворк |
| **Server** | Uvicorn | 0.32.0 | ASGI сервер |
| **Database** | PostgreSQL | - | Основная БД |
| **ORM** | SQLAlchemy | 2.0.36 | Database ORM |
| **Vector DB** | pgvector | 0.3.4 | Векторный поиск |
| **LangChain** | langchain | 1.2.0 | Оркестрация LLM |
| **LangGraph** | langgraph | 1.0.5 | Stateful графы агентов |
| **AI - Primary** | GigaChat | 0.1.37+ | Сбер LLM (основной) |
| **AI - Alt** | Yandex Cloud | 0.17.1 | YandexGPT |
| **Auth** | python-jose | 3.5.0 | JWT токены |
| **Password** | bcrypt | 5.0.0 | Хеширование паролей |
| **Documents** | pypdf | 4.3.1 | PDF обработка |
| **Documents** | python-docx | 1.2.0 | DOCX обработка |
| **Python** | Python | 3.12.8 | Среда выполнения |

### Frontend

| Категория | Технология | Версия | Назначение |
|-----------|-----------|--------|------------|
| **Framework** | React | 18.3.0 | UI библиотека |
| **Routing** | React Router | 6.20.0 | Клиентский роутинг |
| **Build Tool** | Vite | 5.0.8 | Быстрый бандлер |
| **Language** | TypeScript | 5.2.2 | Типобезопасность |
| **UI Library** | Material-UI | 6.1.0 | Библиотека компонентов |
| **Styling** | Tailwind CSS | 3.4.0 | Utility-first CSS |
| **Forms** | React Hook Form | 7.69.0 | Управление формами |
| **Editor** | TipTap | 2.27.2 | Rich text редактор |
| **Tables** | Tanstack Table | 8.21.3 | Продвинутые таблицы |
| **Charts** | Recharts | 2.15.4 | Визуализация данных |
| **HTTP** | Axios | 1.7.0 | API клиент |

---

## Конфигурация

### Переменные окружения

**Файл:** `.env.example`

```bash
# База данных
DATABASE_URL="postgresql://user:password@localhost:5432/legal_ai?schema=public"

# JWT аутентификация
JWT_SECRET_KEY="your-secret-key"
JWT_ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# GigaChat (основной LLM)
GIGACHAT_CREDENTIALS="base64_encoded_credentials"
GIGACHAT_MODEL="GigaChat-Pro"
GIGACHAT_VERIFY_SSL="false"

# Yandex Cloud (опционально)
YANDEX_API_KEY=""
YANDEX_FOLDER_ID=""
YANDEX_IAM_TOKEN=""

# OpenAI (опционально)
OPENAI_API_KEY=""
OPENAI_MODEL="gpt-4o"

# ГАРАНТ API
GARANT_API_KEY=""

# LangSmith (мониторинг)
LANGSMITH_API_KEY=""
LANGSMITH_PROJECT="legal-ai-vault"
LANGCHAIN_TRACING_V2="true"

# RAG настройки
RAG_USE_RERANKER="true"
RAG_MIN_RELEVANCE_SCORE="0.5"
CITATION_VERIFICATION_ENABLED="true"

# Rate Limiting
RATE_LIMIT_ENABLED="true"
RATE_LIMIT_RPS="2.0"
MAX_PARALLEL_LLM_CALLS="8"
```

---

## Деплой

### Поддерживаемые платформы

1. **Railway** (рекомендуется)
   - Автоопределение Dockerfile
   - PostgreSQL add-on
   - UI для переменных окружения
   - Автоматические деплои

2. **Render**
   - Конфигурация render.yaml
   - PostgreSQL сервис
   - Бесплатный tier

3. **Docker**
   - Multi-stage build
   - Python 3.12 + Node.js 20
   - Production-ready

**Зависимости pip:** для деплоя используйте `pip install -r backend/requirements-core.txt` (ядро без Docling/markitdown и без PyTorch — быстрее и без таймаутов). Полная локальная установка с улучшенным PDF: `requirements.txt`.

### Чеклист для production

- [ ] Установить сильный JWT_SECRET_KEY
- [ ] Настроить DATABASE_URL
- [ ] Настроить AI провайдер (GigaChat/Yandex)
- [ ] Настроить CORS_ORIGINS
- [ ] Включить HTTPS
- [ ] Настроить мониторинг ошибок
- [ ] Настроить rate limiting
- [ ] Включить LangSmith tracing (опционально)
- [ ] Настроить бэкапы
- [ ] Настроить логирование

---

## Основные функции

### 1. Управление документами
- Загрузка: PDF, DOCX, XLSX, TXT
- Бинарное хранилище в PostgreSQL
- Кэширование HTML preview
- Полнотекстовый поиск
- Версионирование
- Организация в папки
- Система тегов

### 2. AI-чат
- ReAct агент с 12 инструментами
- Streaming ответы (SSE)
- Ответы с цитатами
- Оценка уверенности
- Многоходовые диалоги
- Контекстная осведомленность
- Deep Think режим

### 3. Табличный обзор
- Excel-подобный интерфейс
- Редактирование на уровне ячеек
- Комментарии и треды
- Отслеживание статуса
- Массовые операции
- Экспорт в XLSX
- Шаблоны колонок

### 4. Редактор документов
- Rich text редактирование (TipTap)
- Коллаборативное редактирование
- Треды комментариев
- История версий
- Автосохранение
- Шаблоны

### 5. Автоматизация workflow
- Визуальный конструктор workflow
- Агентное выполнение
- Human-in-the-loop
- Параллельное выполнение инструментов
- Отслеживание прогресса
- Агрегация результатов

### 6. Система Playbooks
- Проверка соответствия
- Red lines / Fallbacks / No-gos
- Типы контрактов
- Правила по юрисдикциям
- Автоматические редлайны

### 7. Инструменты анализа
- Извлечение сущностей (даты, суммы, лица)
- Генерация временной шкалы
- Обнаружение противоречий
- Оценка рисков
- Классификация документов
- Проверка привилегий

---

## Архитектурные особенности

### Паттерны проектирования
- Repository Pattern
- Dependency Injection
- Factory Pattern
- Strategy Pattern
- Observer Pattern
- State Machine (LangGraph)
- Chain of Responsibility

### Оптимизация производительности
- Connection pooling для БД
- Кэширование результатов
- Virtual scrolling (таблицы)
- Code splitting (lazy loading)
- Индексы БД
- pgvector HNSW index

### Безопасность
- JWT токены (24ч)
- Хеширование паролей (bcrypt, cost 12)
- Rate limiting
- CORS защита
- CSP headers
- Валидация ввода (Pydantic)
- Защита от SQL injection (ORM)

---

## Мониторинг

### Логирование
- Структурированное логирование (JSON)
- Логирование запросов/ответов
- Отслеживание ошибок
- Метрики производительности

### Health Checks
- `/api/health` endpoint
- Проверка подключения к БД
- Доступность AI сервисов
- Статус vector store

### Метрики
- Количество запросов
- Время ответа
- Частота ошибок
- Использование LLM токенов

### Tracing
- Интеграция LangSmith
- Трассировка выполнения агентов
- Логи вызовов инструментов

---

## Документация

- [TESTING_GUIDE.md](TESTING_GUIDE.md) - Инструкции по тестированию
- [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md) - Руководство по деплою на Railway
- [BUGBOT_GUIDE.md](BUGBOT_GUIDE.md) - Руководство по отчетам об ошибках

---

## Статистика проекта

**Backend:**
- Routes: 25 файлов, ~13,426 строк
- Services: 175 файлов
- Models: 13 файлов
- Всего Python LOC: ~500,000+

**Frontend:**
- Pages: 20 файлов
- Components: 300+ файлов
- Всего TypeScript LOC: ~300,000+

**Общая сложность:**
- Строк кода: ~800,000+
- Языки: Python, TypeScript, SQL
- Зависимости: 100+ backend, 100+ frontend

---

## Лицензия

См. LICENSE файл для деталей.

---

## Контакты

Для вопросов и поддержки обращайтесь к команде разработки.
