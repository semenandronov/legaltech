# Анализ соответствия чек-листу интеграции Yandex AI Studio

## Статус проверки по пунктам чек-листа

### ✅ 1. Вход файлов (frontend → backend)

**Статус:** ✅ **СООТВЕТСТВУЕТ**

**Проверено:**
- Файлы принимаются через HTTPS, через `/api/upload`
- Ограничения размера и формата реализованы
- Файлы читаются в память через `file.read()` и не сохраняются на диск
- Используются LangChain-лоадеры (PyPDFLoader, DOCX-loader и т.д.)
- После извлечения текста бинарник удаляется из памяти

**Код:**
- `backend/app/routes/upload.py` - файлы обрабатываются в памяти
- Не обнаружено `save()`, `/tmp`, `tempfile` - файлы работают только в памяти

---

### ✅ 2. Разбор и сохранение в PostgreSQL

**Статус:** ✅ **СООТВЕТСТВУЕТ**

**Проверено:**

**Структура БД:**

**`files`:**
- ✅ `id`, `case_id`, `filename`, `file_type`, `original_text`, `created_at`

**`document_chunks`:**
- ✅ `id`, `case_id`, `file_id`, `chunk_text`, `chunk_metadata` (JSONB), `created_at`
- ✅ `source_file`, `source_page`, `source_start_line`, `source_end_line` - все метаданные присутствуют

**`cases`:**
- ✅ `id`, `user_id`, `full_text` (используется для быстрого доступа), `file_names`, `yandex_index_id`, `yandex_assistant_id`, `created_at`

**Замечание:**
- `full_text` хранится в `cases` - это опционально, но может быть полезно для быстрого поиска без индекса

**Код:**
- `backend/app/models/case.py` - правильная структура моделей
- `backend/app/models/analysis.py` - DocumentChunk с правильными полями

---

### ⚠️ 3. Векторный индекс в Yandex AI Studio (Search Index API)

**Статус:** ⚠️ **ЧАСТИЧНО СООТВЕТСТВУЕТ** (требует доработки)

**Проверено:**

**✅ Используется SDK:**
- Используется `yandex-cloud-ml-sdk` вместо старого REST API
- Код: `backend/app/services/yandex_index.py`

**✅ ENV переменные:**
- `YANDEX_FOLDER_ID` ✅
- `YANDEX_API_KEY` ✅
- `YANDEX_EMBEDDING_MODEL_URI` ✅ (опционально)
- Базовая конфигурация присутствует

**✅ Логика создания индекса:**
1. Проверяется `cases.yandex_index_id` ✅
2. Если пусто → создается индекс через SDK ✅
3. Документы загружаются как файлы, затем создается индекс с file_ids ✅

**❌ ПРОБЛЕМЫ:**

1. **Формат файлов:**
   - Сейчас документы конвертируются в JSON формат `{"text": "...", "metadata": {...}}`
   - Нужно проверить, поддерживает ли Yandex Vector Store такой формат
   - Возможно, нужно использовать чистый текст или другой формат

2. **Удаление индекса:**
   - ❌ Не реализована логика удаления индекса при удалении кейса
   - Нужно добавить фоновый джоб или обработчик для удаления

**Код:**
- `backend/app/services/yandex_index.py` - использует SDK ✅
- `backend/app/services/yandex_index.py:create_index()` - правильная логика ✅
- `backend/app/services/yandex_index.py:_upload_documents_as_files()` - загрузка файлов ✅

---

### ❌ 4. Ассистент в Yandex AI Studio

**Статус:** ❌ **НЕ СООТВЕТСТВУЕТ** (критично!)

**Проверено:**

**❌ Используется старый API:**
- Используется `foundationModels/v1/assistants` ❌
- Код: `backend/app/services/yandex_assistant.py:81, 175, 253, 283`

**✅ ENV переменные:**
- `YANDEX_GPT_MODEL_URI` ✅ (используется правильно)
- `YANDEX_FOLDER_ID` ✅

**✅ Логика создания:**
1. Проверяется `cases.yandex_assistant_id` ✅
2. Если пусто → создается ассистент ✅
3. Используется Search Index tool с `index_id` ✅
4. System prompt настроен ✅

**❌ КРИТИЧЕСКИЕ ПРОБЛЕМЫ:**

1. **Старый API endpoint:**
   - Используется `https://llm.api.cloud.yandex.net/foundationModels/v1/assistants` ❌
   - Нужно использовать новый Assistants API через SDK или новый REST endpoint
   - Не соответствует чек-листу: "Все чаты идут через `/assistants/{assistant_id}/chat`, а не напрямую через старый Completion API"

2. **Не используется SDK:**
   - Вместо SDK используется прямой REST API
   - Нужно проверить, поддерживает ли SDK работу с ассистентами

**Код:**
- `backend/app/services/yandex_assistant.py` - требует переработки ❌

---

### ⚠️ 5. Безопасность и 152‑ФЗ

**Статус:** ⚠️ **ТРЕБУЕТ ПРОВЕРКИ**

**Проверено:**

**✅ Логирование:**
- В логах не обнаружено сохранения полных текстов документов
- Логируются только метаданные (IDs, имена файлов) ✅

**❓ Регион и соответствие 152‑ФЗ:**
- Не проверено в коде
- Требует ручной проверки настроек Yandex Cloud Console

**✅ Доступ:**
- Есть ограничение доступа по `user_id` через `get_current_user` ✅
- Кейсы связаны с пользователями через `user_id` ✅

---

### ❌ 6. Мини‑чек‑лист для разработчика «перед релизом»

#### 1. Нет ли больше в коде `foundationModels/v1/indexes`?
- ✅ Для индексов: используется SDK ✅
- ❌ Для ассистентов: используется `foundationModels/v1/assistants` ❌

#### 2. Все `model_uri` берутся из ENV и совпадают с AI Studio Console?
- ✅ `YANDEX_GPT_MODEL_URI` используется ✅
- ✅ `YANDEX_EMBEDDING_MODEL_URI` используется ✅
- ✅ Формируются правильные URI формата `gpt://...` и `emb://...` ✅

#### 3. Файлы не пишутся на диск?
- ✅ Файлы обрабатываются только в памяти ✅

#### 4. У каждого `case` есть связка `case_id` ↔ `yandex_index_id` ↔ `yandex_assistant_id`?
- ✅ Все поля присутствуют в БД ✅
- ✅ Индекс создается при загрузке документов ✅
- ✅ Ассистент создается при необходимости ✅

#### 5. Удаление кейса удаляет индекс в Яндекс (или хотя бы помечает к удалению)?
- ❌ **НЕ РЕАЛИЗОВАНО** ❌
- Нужно добавить логику удаления индекса и ассистента

#### 6. В UI по клику «Открыть в документе» реально находится chunk по `chunk_metadata`?
- ❓ Требует проверки фронтенда (не в scope бэкенда)

---

## Итоговый список задач

### Критичные (блокируют работу):

1. ❌ **Заменить `foundationModels/v1/assistants` на новый Assistants API**
   - Файл: `backend/app/services/yandex_assistant.py`
   - Использовать SDK для ассистентов или новый REST endpoint
   - Проверить документацию: нужно ли использовать SDK или новый REST API

### Важные (нужно исправить):

2. ⚠️ **Добавить логику удаления индекса при удалении кейса**
   - Файл: добавить в роуты удаления кейсов или в модель Case
   - Использовать `yandex_index.delete_index(index_id)`

3. ⚠️ **Добавить логику удаления ассистента при удалении кейса**
   - Файл: добавить в роуты удаления кейсов или в модель Case
   - Использовать `yandex_assistant.delete_assistant(assistant_id)`

4. ⚠️ **Проверить формат файлов для Vector Store**
   - Файл: `backend/app/services/yandex_index.py:_upload_documents_as_files()`
   - Сейчас используется JSON формат - проверить, правильный ли это формат для Yandex Vector Store
   - Возможно, нужно использовать чистый текст или другой формат

### Опциональные (улучшения):

5. ⚠️ **Проверить соответствие 152‑ФЗ**
   - Требует ручной проверки настроек в Yandex Cloud Console
   - Убедиться, что `folder_id` относится к региону РФ

---

## Рекомендации по исправлению

### 1. Исправить Assistants API

**Вариант A: Использовать SDK (если поддерживается)**
```python
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth

sdk = YCloudML(folder_id=folder_id, auth=APIKeyAuth(api_key))
assistant = sdk.assistants.create(...)
```

**Вариант B: Использовать новый REST API (если SDK не поддерживает)**
- Найти актуальный endpoint для Assistants API
- Заменить `foundationModels/v1/assistants` на новый endpoint
- Проверить формат запросов/ответов

### 2. Добавить удаление индекса и ассистента

**В модель Case или в роуты:**
```python
# При удалении кейса
if case.yandex_index_id:
    index_service.delete_index(case.yandex_index_id)
if case.yandex_assistant_id:
    assistant_service.delete_assistant(case.yandex_assistant_id)
```

---

## Заключение

**Общий статус:** ⚠️ **ТРЕБУЕТ ДОРАБОТКИ**

**Критичные проблемы:** 1 (Assistants API)
**Важные проблемы:** 3 (удаление индекса/ассистента, формат файлов)
**Опциональные:** 1 (152‑ФЗ)

**Приоритет:** Исправить критичные проблемы перед продакшеном.

