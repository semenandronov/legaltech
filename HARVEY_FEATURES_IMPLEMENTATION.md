# Реализация Harvey-подобных функций

## Обзор реализованных функций

Данный документ описывает все Harvey-подобные функции, реализованные в проекте Legal AI Vault.

---

## 1. Множественные источники данных (External Sources)

### Расположение
- `backend/app/services/external_sources/`

### Компоненты

| Файл | Описание |
|------|----------|
| `base_source.py` | Абстрактный базовый класс для источников данных |
| `source_router.py` | Роутер для управления источниками и агрегации результатов |
| `web_search.py` | Веб-поиск через Yandex Search API |
| `garant_source.py` | Интеграция с правовой системой Гарант |
| `consultant_source.py` | Интеграция с системой КонсультантПлюс |

### Архитектура

```
┌─────────────────────────────────────────────────┐
│                 Source Router                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐│
│  │  Vault  │ │   Web   │ │ Garant  │ │ Consult ││
│  │ (docs)  │ │ Search  │ │         │ │   Plus  ││
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘│
└───────┼──────────┼──────────┼──────────┼───────┘
        │          │          │          │
        └──────────┴──────────┴──────────┘
                       │
              ┌────────┴────────┐
              │ Result Aggregator│
              │  (rank, dedup)   │
              └────────┬────────┘
                       │
                  ┌────┴────┐
                  │ YandexGPT│
                  └─────────┘
```

### Frontend
- `frontend/src/components/Chat/SourceSelector.tsx` - UI для выбора источников

---

## 2. Адаптивные агенты

### Расположение
- `backend/app/services/langchain_agents/`

### Компоненты

| Файл | Описание |
|------|----------|
| `state.py` | Расширенный AnalysisState с полями для адаптации |
| `evaluation_node.py` | Узел оценки результатов агентов |
| `adaptation_engine.py` | Движок адаптации планов |

### Новые поля в AnalysisState

```python
# Адаптивные поля
current_plan: List[Dict]          # Текущий план с шагами
completed_steps: List[str]        # ID выполненных шагов
adaptation_history: List[Dict]    # История изменений плана
needs_replanning: bool            # Флаг перепланирования
evaluation_result: Optional[Dict] # Результат оценки
current_step_id: Optional[str]    # Текущий шаг

# Human-in-the-loop поля
pending_feedback: List[Dict]             # Ожидающие вопросы
feedback_responses: Dict[str, str]       # Ответы пользователя
waiting_for_human: bool                  # Флаг ожидания
current_feedback_request: Optional[Dict] # Текущий запрос
```

### Стратегии адаптации

1. **retry_failed** - Повторная попытка неудачных шагов
2. **skip_failed** - Пропуск неудачных шагов
3. **add_steps** - Добавление дополнительных шагов
4. **reorder** - Переупорядочивание шагов
5. **simplify** - Упрощение плана

---

## 3. Human-in-the-loop

### Backend
- `backend/app/models/agent_interaction.py` - Модели взаимодействия
- `backend/app/services/langchain_agents/human_feedback.py` - Сервис обратной связи

### Типы вопросов

| Тип | Описание |
|-----|----------|
| `clarification` | Запрос уточнения (свободный ответ) |
| `confirmation` | Подтверждение (Да/Нет) |
| `choice` | Выбор из вариантов |

### Frontend
- `frontend/src/components/Agents/AgentInteractionModal.tsx` - Модальное окно для вопросов
- `frontend/src/components/Agents/AgentProgressView.tsx` - Визуализация прогресса агентов

---

## 4. Библиотека промптов

### Backend
- `backend/app/models/prompt_library.py` - Модели промптов
- `backend/app/services/prompt_library_service.py` - Сервис
- `backend/app/routes/prompts.py` - API эндпоинты

### Категории промптов

| Категория | Описание |
|-----------|----------|
| contract | Договоры |
| litigation | Судебные дела |
| due_diligence | Due Diligence |
| research | Исследование |
| compliance | Compliance |
| custom | Прочее |

### API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/prompts/` | Список промптов |
| GET | `/api/prompts/{id}` | Получить промпт |
| POST | `/api/prompts/` | Создать промпт |
| PUT | `/api/prompts/{id}` | Обновить промпт |
| DELETE | `/api/prompts/{id}` | Удалить промпт |
| POST | `/api/prompts/{id}/use` | Использовать промпт |
| POST | `/api/prompts/{id}/duplicate` | Дублировать промпт |

### Frontend
- `frontend/src/components/Chat/PromptLibrary.tsx` - UI библиотеки промптов

---

## 5. Magic Prompt (Улучшение запросов)

### Backend
- `backend/app/services/prompt_improver.py` - Сервис улучшения

### Возможности

- Добавление структуры к запросам
- Добавление юридического контекста
- Предложения по улучшению
- Объяснение изменений

### Frontend
- `frontend/src/components/Chat/MagicPromptButton.tsx` - Кнопка улучшения

---

## 6. Workflows (Шаблоны рабочих процессов)

### Backend
- `backend/app/models/workflow_template.py` - Модель workflow
- `backend/app/services/workflow_service.py` - Сервис
- `backend/app/routes/workflows.py` - API эндпоинты

### Предустановленные шаблоны

| Шаблон | Описание |
|--------|----------|
| M&A Due Diligence | Комплексная проверка для сделок M&A |
| Litigation Review | Анализ материалов судебного дела |
| Contract Analysis | Детальный анализ договоров |
| Regulatory Compliance | Проверка соответствия требованиям |

### API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/workflows/` | Список workflows |
| GET | `/api/workflows/{id}` | Получить workflow |
| POST | `/api/workflows/` | Создать workflow |
| PUT | `/api/workflows/{id}` | Обновить workflow |
| DELETE | `/api/workflows/{id}` | Удалить workflow |
| POST | `/api/workflows/{id}/use` | Использовать workflow |

---

## 7. Организация файлов (Folders)

### Backend
- `backend/app/models/folder.py` - Модели папок и тегов

### Возможности

- Вложенные папки
- Теги для файлов
- Избранные файлы
- Сортировка и упорядочивание

### Frontend
- `frontend/src/components/Files/FolderTree.tsx` - Дерево папок

---

## Миграция базы данных

```bash
# Применить миграцию
psql -U postgres -d legal_ai_vault -f backend/migrations/add_harvey_features.sql
```

---

## Конфигурация

### Новые переменные окружения

```env
# Yandex Search API (для веб-поиска)
YANDEX_SEARCH_API_KEY=your_key

# Гарант API (опционально)
GARANT_API_KEY=your_key
GARANT_API_URL=https://api.garant.ru/v1

# Консультант+ API (опционально)
CONSULTANT_API_KEY=your_key
CONSULTANT_API_URL=https://api.consultant.ru/v1
```

---

## Дальнейшее развитие

### Приоритет 1 (Рекомендуется)
- [ ] Интеграция с iManage для документооборота
- [ ] Голосовой ввод (диктовка)
- [ ] Deep Research режим

### Приоритет 2
- [ ] Мобильное приложение
- [ ] Интеграция с EDGAR (SEC filings)
- [ ] Интеграция с LexisNexis

### Приоритет 3
- [ ] Совместная работа в реальном времени
- [ ] Аудит действий пользователей
- [ ] Расширенная аналитика

