# Рекомендации по работе с Yandex AI Studio Assistants API

## Текущая ситуация

В проекте используется устаревший `foundationModels/v1/assistants` API endpoint, который нужно заменить.

## Варианты решения

### Вариант 1: Использовать Responses API с file_search инструментом (Рекомендуется)

Согласно документации Yandex AI Studio, **Responses API** является OpenAI-совместимым API для текстовых агентов с поддержкой инструментов, включая `file_search` для работы с Vector Store.

**Преимущества:**
- Совместим с OpenAI API
- Поддерживает инструменты, включая file_search для Vector Store
- Не требует создания отдельного ассистента

**Как это работает:**
1. Создается индекс через Search Index API (уже реализовано)
2. При запросе используется Responses API с инструментом `file_search` и `index_id`
3. Модель автоматически ищет информацию в индексе и отвечает

**Пример использования:**
```python
# Использовать SDK для Responses API
sdk = YCloudML(folder_id=folder_id, auth=auth)

# Chat completion с file_search инструментом
model = sdk.models.completions(model_uri)
response = model.run(
    messages=[
        {"role": "user", "content": "Вопрос пользователя"}
    ],
    tools=[{
        "type": "file_search",
        "index_id": index_id
    }]
)
```

### Вариант 2: Использовать SDK для Assistants (если доступно)

Согласно комментариям в коде (`yandex_index.py:36`), SDK поддерживает `sdk.assistants`. 

**Проверка:**
Нужно проверить в SDK, есть ли метод `sdk.assistants.create()` или аналогичный.

**Если доступно:**
```python
sdk = YCloudML(folder_id=folder_id, auth=auth)

assistant = sdk.assistants.create(
    name="assistant_name",
    model=model_uri,
    tools=[{
        "type": "file_search",
        "index_id": index_id
    }]
)
```

**Если НЕ доступно:**
Нужно найти актуальный REST endpoint (НЕ foundationModels).

### Вариант 3: Текущий RAG подход (уже работает!)

В проекте уже реализован правильный RAG подход:
1. Поиск по индексу через `retrieve_relevant_chunks()` ✅
2. Форматирование контекста ✅
3. Передача в LLM через `ChatYandexGPT` ✅

**Это правильный подход и он уже работает!**

Однако `YandexAssistantService` используется в `rag_service.py`, но на самом деле можно использовать прямо Responses API.

## Рекомендация для проекта

### Краткосрочное решение (уже реализовано):

Текущий RAG подход **правильный** и **работает**:
- Поиск по индексу через `document_processor.retrieve_relevant_chunks()`
- Форматирование контекста
- Передача в LLM

**Проблема:** `YandexAssistantService` использует устаревший API, но фактически не используется критично, так как RAG работает через прямой поиск.

### Долгосрочное решение:

1. **Упростить архитектуру:**
   - Убрать `YandexAssistantService` (использует устаревший API)
   - Использовать прямо Responses API через SDK с инструментом `file_search`

2. **Или проверить SDK:**
   - Проверить, есть ли `sdk.assistants.create()`
   - Если есть - использовать его
   - Если нет - использовать Responses API

## Конкретные шаги

### Шаг 1: Проверить SDK на наличие assistants

```python
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth

sdk = YCloudML(folder_id=folder_id, auth=APIKeyAuth(api_key))

# Проверить доступные методы
print(dir(sdk))
if hasattr(sdk, 'assistants'):
    print(dir(sdk.assistants))
```

### Шаг 2: Если SDK поддерживает assistants

Использовать `sdk.assistants.create()` и `sdk.assistants.chat()`.

### Шаг 3: Если SDK НЕ поддерживает assistants

Использовать Responses API через SDK:
```python
model = sdk.models.completions(model_uri)
response = model.run(
    messages=messages,
    tools=[{"type": "file_search", "index_id": index_id}]
)
```

## Ссылки на документацию

- [Yandex AI Studio - Основная документация](https://yandex.cloud/ru/docs/ai-studio/)
- [Yandex Cloud ML SDK - Справочник](https://yandex.cloud/ru/docs/ai-studio/sdk/)
- Responses API: OpenAI-совместимый API для текстовых агентов
- Vector Store API: для работы с поисковыми индексами

## Вывод

**Текущий RAG подход правильный и работает!** 

`YandexAssistantService` использует устаревший API, но его можно либо:
1. Упростить и использовать Responses API напрямую
2. Или оставить как есть, если текущий RAG подход работает достаточно хорошо

Приоритет: **Низкий**, так как текущая реализация работает через RAG подход, который является правильным.

