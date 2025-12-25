# Tabular Review - Документация

## Обзор

Tabular Review - это функционал для преобразования документов в интерактивную таблицу, где каждая строка представляет документ, а каждая колонка - извлеченное поле из документов с помощью AI.

## Функционал

- ✅ Создание Tabular Review проектов
- ✅ Добавление пользовательских колонок (вопросов к документам)
- ✅ Параллельное извлечение данных из всех документов
- ✅ Интерактивная таблица с сортировкой и фильтрацией
- ✅ Cell expansion - просмотр деталей ячейки (verbatim extract, reasoning, confidence)
- ✅ Экспорт в Excel и CSV
- ✅ Статусы документов (reviewed, flagged, etc.)

## Структура базы данных

### Таблицы:
1. `tabular_reviews` - проекты Tabular Review
2. `tabular_columns` - определения колонок (вопросы)
3. `tabular_cells` - значения ячеек (ответы AI)
4. `tabular_column_templates` - шаблоны колонок для переиспользования
5. `tabular_document_status` - статусы просмотра документов

## Backend API

Все endpoints находятся под префиксом `/api/tabular-review/`:

- `POST /` - создать новый review
- `GET /{review_id}` - получить данные review
- `GET /{review_id}/table-data` - получить данные таблицы
- `POST /{review_id}/columns` - добавить колонку
- `POST /{review_id}/run` - запустить обработку документов
- `GET /{review_id}/cell/{file_id}/{column_id}` - получить детали ячейки
- `POST /{review_id}/document-status` - обновить статус документа
- `POST /{review_id}/export/csv` - экспорт в CSV
- `POST /{review_id}/export/excel` - экспорт в Excel
- `GET /templates` - получить шаблоны
- `POST /templates` - сохранить шаблон

## Frontend

### Компоненты:
- `TabularReviewPage` - главная страница
- `TabularReviewTable` - таблица на основе TanStack Table
- `CellExpansionModal` - модалка с деталями ячейки
- `ColumnBuilder` - форма для создания колонок
- `TabularReviewToolbar` - панель инструментов

### Роутинг:
- `/cases/:caseId/tabular-review/:reviewId?` - страница Tabular Review

## Использование

1. Откройте дело (case)
2. Перейдите на вкладку "Tabular Review"
3. Если review не существует, он будет создан автоматически
4. Добавьте колонки (вопросы к документам)
5. Нажмите "Run all" для запуска обработки
6. Просматривайте результаты в таблице
7. Кликайте на ячейки для просмотра деталей
8. Экспортируйте результаты в Excel/CSV

## Технологии

- **Backend**: FastAPI, SQLAlchemy, YandexGPT
- **Frontend**: React, TypeScript, TanStack Table v8.21.3
- **База данных**: PostgreSQL с JSONB для гибких данных

## Миграция БД

Для создания таблиц выполните миграцию:
```bash
psql -d your_database -f backend/migrations/add_tabular_review_tables.sql
```

Или таблицы создадутся автоматически при первом запуске через SQLAlchemy.

## Следующие шаги (TODO)

- [ ] Добавить WebSocket для real-time обновлений
- [ ] Реализовать шаблоны колонок
- [ ] Добавить virtual scrolling для больших таблиц (10k+ строк)
- [ ] Улучшить обработку ошибок извлечения
- [ ] Добавить batch операции со статусами документов
- [ ] Реализовать share функционал

