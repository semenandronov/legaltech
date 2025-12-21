# FAQ: Интеграция с Yandex Cloud AI Studio

## Общие вопросы

### 1. Какие переменные окружения нужны для работы с Yandex Cloud?

**Ответ:**
Обязательные переменные:
- `YANDEX_API_KEY` - API ключ из Yandex Cloud (рекомендуется)
- `YANDEX_IAM_TOKEN` - IAM токен (альтернатива API ключу, истекает через 12 часов)
- `YANDEX_FOLDER_ID` - ID каталога (folder ID) из Yandex Cloud Console

Опциональные (для кастомизации моделей):
- `YANDEX_GPT_MODEL` - Короткое имя модели YandexGPT (по умолчанию: `yandexgpt-pro/latest`)
- `YANDEX_GPT_MODEL_URI` - Полный URI модели (приоритет над `YANDEX_GPT_MODEL`)
- `YANDEX_EMBEDDING_MODEL` - Короткое имя модели для embeddings (по умолчанию: `text-search-query`)
- `YANDEX_EMBEDDING_MODEL_URI` - Полный URI модели embeddings (приоритет над `YANDEX_EMBEDDING_MODEL`)
- `YANDEX_INDEX_PREFIX` - Префикс для имен индексов (по умолчанию: `legal_ai_vault`)

### 2. Где взять YANDEX_FOLDER_ID?

**Ответ:**
1. Зайдите в [Yandex Cloud Console](https://console.cloud.yandex.ru/)
2. Выберите нужный каталог (folder)
3. В URL вы увидите `folderId=XXXXX` или на странице каталога будет показан его ID
4. Скопируйте этот ID и добавьте в переменные окружения

### 3. Какой способ аутентификации лучше использовать: API ключ или IAM токен?

**Ответ:**
Рекомендуется использовать **API ключ** (`YANDEX_API_KEY`), потому что:
- Не истекает (в отличие от IAM токена, который действует 12 часов)
- Проще в использовании
- Не требует периодического обновления

IAM токен нужен только если вы используете сервисный аккаунт для аутентификации.

### 4. Как правильно указать model_uri для YandexGPT и Embeddings?

**Ответ:**
Есть два варианта:

**Вариант 1: Короткое имя + автоматическое формирование URI**
```
YANDEX_GPT_MODEL=yandexgpt-pro/latest
YANDEX_EMBEDDING_MODEL=text-search-query
```
Система автоматически сформирует полный URI: `gpt://<folder_id>/yandexgpt-pro/latest`

**Вариант 2: Полный URI (рекомендуется)**
```
YANDEX_GPT_MODEL_URI=gpt://<folder_id>/yandexgpt-lite/rc
YANDEX_EMBEDDING_MODEL_URI=emb://<folder_id>/text-search-query/latest
```

**Важно:** Если указаны оба варианта (`YANDEX_GPT_MODEL` и `YANDEX_GPT_MODEL_URI`), приоритет у полного URI.

### 5. Какие форматы model_uri поддерживаются?

**Ответ:**
- **YandexGPT:** `gpt://<folder_id>/<model_name>/<version>`
  - Примеры:
    - `gpt://b1gXXXXX/yandexgpt-pro/latest`
    - `gpt://b1gXXXXX/yandexgpt-lite/rc`
  
- **Embeddings:** `emb://<folder_id>/<model_name>/<version>`
  - Примеры:
    - `emb://b1gXXXXX/text-search-query/latest`
    - `emb://b1gXXXXX/text-search-doc/latest`

## Вопросы по Vector Store / Search Indexes

### 6. Как работает создание индексов через SDK?

**Ответ:**
Создание индекса происходит через метод `create_deferred()`:
1. Метод требует обязательный параметр `files` (список файлов)
2. Для пустого индекса передается пустой список: `files=[]`
3. Документы добавляются позже через метод `add_documents()`

**Доступные методы SDK:**
- `create_deferred(name, description, files)` - асинхронное создание индекса
- `get(index_id)` - получение информации об индексе
- `list()` - список всех индексов

### 7. Почему старый API `/foundationModels/v1/indexes` не работает?

**Ответ:**
Старый REST API endpoint устарел и возвращает 404. Нужно использовать:
- **Yandex Cloud ML SDK** (`yandex-cloud-ml-sdk`)
- Новый **Vector Store API** через SDK

Документация: https://yandex.cloud/docs/ai-studio/concepts/vector-store

### 8. Как правильно добавлять документы в индекс?

**Ответ:**
После создания индекса документы добавляются через метод `add_documents(index_id, documents)`.

**Важно:** Этот метод еще не полностью реализован через SDK. Текущая реализация возвращает статус "not_implemented" и требует доработки согласно документации SDK.

Возможные варианты реализации:
1. Конвертировать LangChain Documents в файлы и загрузить через `sdk.files.upload()`
2. Использовать `sdk.vector_store.add_files()` если доступно
3. Использовать `sdk.search_indexes.add_documents()` если доступно

### 9. Какой процесс создания индекса правильный?

**Ответ:**
Рекомендуемый процесс:
1. **Создать пустой индекс** через `create_deferred(files=[])`
2. **Сохранить index_id** в базу данных (таблица `cases`, колонка `yandex_index_id`)
3. **Добавить документы** через `add_documents()` (требует реализации)
4. **Использовать индекс** для поиска через `search()` (требует реализации)

**Альтернативный процесс (если SDK требует файлы при создании):**
1. Загрузить файлы через `sdk.files.upload()`
2. Получить file_ids
3. Создать индекс с файлами: `create_deferred(files=[{"id": "file_id_1"}, ...])`

## Вопросы по базе данных

### 10. Какие колонки нужны в таблице cases?

**Ответ:**
Обязательные колонки:
- `yandex_index_id` (VARCHAR(255), NULLABLE) - ID индекса Vector Store
- `yandex_assistant_id` (VARCHAR(255), NULLABLE) - ID ассистента Yandex AI Studio

**Важно:** Эти колонки автоматически добавляются при старте приложения через `ensure_schema()`.

### 11. Почему возникает ошибка NotNullViolation для sessionId?

**Ответ:**
Колонка `sessionId` в таблице `chat_messages` может иметь ограничение NOT NULL. 

**Решение:**
- При старте приложения выполняется миграция, которая:
  1. Проверяет статус колонки (nullable или нет)
  2. Удаляет ограничение NOT NULL если оно есть
  3. Обновляет существующие NULL значения на `case_id`

**В коде:** Всегда используйте `case_id` как `session_id` при создании `ChatMessage`.

## Вопросы по работе SDK

### 12. Как инициализируется Yandex Cloud ML SDK?

**Ответ:**
```python
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth

auth = APIKeyAuth(api_key)  # или IAM токен
sdk = YCloudML(folder_id=folder_id, auth=auth)
```

**Важно:**
- SDK инициализируется автоматически при создании сервисов
- Если `YANDEX_API_KEY` или `YANDEX_IAM_TOKEN` не установлены, SDK не будет работать
- Если `YANDEX_FOLDER_ID` не установлен, SDK не будет работать

### 13. Какие сервисы SDK используются в проекте?

**Ответ:**
1. **sdk.models.completions()** - для YandexGPT (генерация текста)
2. **sdk.models.text_embeddings()** - для создания embeddings
3. **sdk.search_indexes** - для работы с поисковыми индексами
4. **sdk.assistants** - для создания AI ассистентов (через YandexAssistantService)

### 14. Как проверить, правильно ли инициализирован SDK?

**Ответ:**
В логах должны быть сообщения:
- `✅ Using Yandex API key for authentication` (или IAM token)
- `✅ Yandex Cloud ML SDK initialized for Vector Store`

Если SDK не инициализирован, будут предупреждения:
- `YANDEX_API_KEY or YANDEX_IAM_TOKEN not set`
- `YANDEX_FOLDER_ID not set`

## Вопросы по обработке ошибок

### 15. Что делать при ошибке "invalid model_uri"?

**Ответ:**
1. Проверьте формат URI:
   - YandexGPT: `gpt://<folder_id>/<model_name>/<version>`
   - Embeddings: `emb://<folder_id>/<model_name>/<version>`
2. Убедитесь, что `YANDEX_FOLDER_ID` правильный
3. Проверьте, что модель существует и доступна в вашем каталоге
4. Используйте полный URI через `YANDEX_GPT_MODEL_URI` вместо короткого имени

### 16. Что делать при ошибке 404 при создании индекса?

**Ответ:**
Если используете старый REST API:
- Перейдите на использование Yandex Cloud ML SDK
- Используйте метод `create_deferred()` вместо прямых REST вызовов

### 17. Что делать при ошибке "missing 1 required positional argument: 'files'"?

**Ответ:**
Метод `create_deferred()` требует параметр `files` (список файлов):
- Для пустого индекса: `create_deferred(name=..., description=..., files=[])`
- Для индекса с файлами: `create_deferred(name=..., description=..., files=[{"id": "file_id"}, ...])`

### 18. Почему индексы не создаются, но документы сохраняются?

**Ответ:**
Документы сохраняются в базу данных (`document_chunks`), даже если создание индекса не удалось. Это позволяет:
1. Сохранить данные
2. Попытаться создать индекс позже
3. Использовать fallback механизм для поиска по БД

## Вопросы по развертыванию

### 19. Где на Render добавить переменные окружения?

**Ответ:**
1. Зайдите в Dashboard Render
2. Выберите ваш сервис
3. Перейдите в раздел "Environment"
4. Добавьте все необходимые переменные:
   - `YANDEX_API_KEY`
   - `YANDEX_FOLDER_ID`
   - `YANDEX_GPT_MODEL_URI` (опционально)
   - `YANDEX_EMBEDDING_MODEL_URI` (опционально)
5. Нажмите "Save Changes"
6. Сервис перезапустится автоматически

### 20. Нужно ли что-то настраивать в Yandex Cloud Console?

**Ответ:**
Да, нужно:
1. **Создать API ключ:**
   - Cloud Console → IAM → API keys → Create
   - Сохраните ключ в безопасном месте

2. **Проверить права доступа:**
   - Убедитесь, что у вашего аккаунта/сервисного аккаунта есть права:
     - `ai.assistants.editor` - **ОБЯЗАТЕЛЬНО** для загрузки файлов в Vector Store через files.upload()
     - `ai.languageModels.user` - для работы с YandexGPT и Embeddings
     - `editor` или `admin` - альтернатива для ai.assistants.editor (но рекомендуется именно ai.assistants.editor)
   
   **ВАЖНО:** Роль `ai.assistants.auditor` НЕДОСТАТОЧНА для загрузки файлов! Нужна именно `ai.assistants.editor`.

3. **Включить AI Studio:**
   - Убедитесь, что AI Studio активирован для вашего каталога

## Полезные ссылки

- **SDK Reference:** https://yandex.cloud/docs/ai-studio/sdk-ref/
- **SDK Examples:** https://github.com/yandex-cloud/yandex-cloud-ml-sdk/tree/master/examples
- **Yandex Cloud Examples:** https://github.com/yandex-cloud-examples
- **Vector Store Documentation:** https://yandex.cloud/docs/ai-studio/concepts/vector-store
- **YandexGPT Models:** https://yandex.cloud/docs/yandexgpt/concepts/models
- **AI Studio Documentation:** https://yandex.cloud/docs/ai-studio/

## Чек-лист перед развертыванием

- [ ] Установлен `YANDEX_API_KEY` или `YANDEX_IAM_TOKEN`
- [ ] Установлен `YANDEX_FOLDER_ID`
- [ ] Проверен формат `YANDEX_GPT_MODEL_URI` (если используется)
- [ ] Проверен формат `YANDEX_EMBEDDING_MODEL_URI` (если используется)
- [ ] API ключ имеет права доступа к AI Studio (роль `ai.assistants.editor` обязательна!)
- [ ] AI Studio активирован в каталоге
- [ ] База данных имеет необходимые колонки (`yandex_index_id`, `yandex_assistant_id`)
- [ ] Колонка `chat_messages.sessionId` nullable
- [ ] Логи показывают успешную инициализацию SDK

