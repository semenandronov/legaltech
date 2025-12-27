# Настройка GigaChat для тестирования

## Шаг 1: Регистрация и получение ключа авторизации

### 1.1. Регистрация в личном кабинете

Если вы еще не зарегистрированы, создайте учетную запись в личном кабинете Sber Developer Studio и создайте новый проект GigaChat API.

**Документация:** [Регистрация в личном кабинете](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-create-project)

### 1.2. Получение ключа авторизации

Для начала работы вам потребуется **ключ авторизации (Authorization Key)**. Этот ключ используется для получения токена доступа к API.

**Как получить:**
1. Войдите в личный кабинет вашего проекта GigaChat API
2. Перейдите в раздел **Настройки API**
3. Нажмите кнопку **Получить ключ**, чтобы сгенерировать и скачать:
   - `Client ID`
   - `Client Secret`
   - **Ключ авторизации** (Authorization Key) - это то, что нужно!

**Документация:** [Получение ключа авторизации](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-get-auth-key)

**Важно:** Ключ авторизации имеет формат `base64(ClientID:ClientSecret)`, например:
```
MDE5YjVmNmUtOTg5OS03YzUyLTgxNWUtM2JiMDhmNjAwZTJiOjMwNmVkOTlkLThiNjctNGFmMy1hNTRjLWI1YjA2ODhkOGQyZA==
```

### 1.3. Получение токена доступа (опционально)

GigaChat SDK автоматически получает токен доступа из ключа авторизации при первом запросе. Токен действителен **30 минут** и автоматически обновляется SDK.

Если вы хотите получить токен вручную (для тестирования):

```bash
curl -L -X POST 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth' \
-H 'Content-Type: application/x-www-form-urlencoded' \
-H 'Accept: application/json' \
-H 'RqUID: <уникальный_идентификатор>' \
-H 'Authorization: Basic <ключ_авторизации>' \
--data-urlencode 'scope=GIGACHAT_API_PERS'
```

**Документация:** [Получение токена доступа](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token)

**Важно:**
- Токен доступа действителен **30 минут**
- Запросы на получение токена можно отправлять до **10 раз в секунду**
- SDK автоматически обновляет токен при необходимости

## Шаг 2: Установка зависимостей

```bash
cd backend
pip install langchain-gigachat
```

Или добавьте в `requirements.txt`:
```
langchain-gigachat>=0.1.0
```

**Примечание:** `langchain-gigachat` автоматически установит `gigachat` SDK как зависимость.

## Шаг 3: Настройка переменных окружения

Добавьте в файл `.env` в корне проекта:

```bash
# GigaChat (Сбер)
# ВАЖНО: Используйте ключ авторизации (Authorization Key), а не токен доступа!
# SDK автоматически получит токен доступа из ключа авторизации
GIGACHAT_CREDENTIALS=MDE5YjVmNmUtOTg5OS03YzUyLTgxNWUtM2JiMDhmNjAwZTJiOjMwNmVkOTlkLThiNjctNGFmMy1hNTRjLWI1YjA2ODhkOGQyZA==
GIGACHAT_MODEL=GigaChat
GIGACHAT_VERIFY_SSL=true

# Выбор LLM провайдера для агентов
LLM_PROVIDER=gigachat  # или "yandex" для переключения обратно
```

**Примечание:** 
- `GIGACHAT_CREDENTIALS` должен содержать **ключ авторизации** (Authorization Key), а не токен доступа
- SDK автоматически получает и обновляет токен доступа при необходимости

## Шаг 4: Тестирование

### Базовый тест

```bash
cd backend
python test_gigachat_integration.py
```

Этот скрипт проверит:
1. ✅ Базовый вызов GigaChat
2. ✅ Function calling (bind_tools)
3. ✅ LLM Factory

### Тест timeline агента

Запустите анализ через API или через координатор агентов. Timeline агент будет использовать GigaChat, если `LLM_PROVIDER=gigachat`.

## Что изменилось

### Используется официальная библиотека:
- **`langchain-gigachat`** - Официальная интеграция GigaChat с LangChain от AI Forever (Сбер)
- Полная поддержка LangChain и LangGraph
- Нативная поддержка function calling

### Новые файлы:
- `backend/app/services/llm_factory.py` - Factory для выбора LLM провайдера
- `backend/app/services/gigachat_token_helper.py` - Helper для управления токенами
- `backend/test_gigachat_integration.py` - Тестовый скрипт

### Обновленные файлы:
- `backend/app/config.py` - Добавлены настройки GigaChat
- `backend/app/services/langchain_agents/timeline_node.py` - Использует `create_llm()` вместо прямого `ChatYandexGPT`
- `backend/app/services/langchain_agents/llm_helper.py` - Использует `create_llm()` вместо прямого `ChatYandexGPT`
- `backend/requirements.txt` - Добавлены `gigachat` и `langchain-gigachat`

### Устаревшие файлы (можно удалить после тестирования):
- `backend/app/services/gigachat_llm.py` - Наш самописный wrapper (заменен на langchain-gigachat)

## Преимущества GigaChat через langchain-gigachat

1. ✅ **Официальная поддержка** - Библиотека от AI Forever (Сбер)
2. ✅ **Function Calling** - Полная поддержка `bind_tools()` из коробки
3. ✅ **Интеграция с LangChain** - Полная совместимость с LangChain и LangGraph
4. ✅ **Автономность агентов** - LLM сам решает, когда вызывать инструменты
5. ✅ **Итеративный поиск** - Многошаговые запросы с автоматическим выбором инструментов
6. ✅ **Меньше токенов** - Только результаты вызовов в контексте, а не все документы
7. ✅ **Автоматические обновления** - Обновления через PyPI

## Переключение между провайдерами

Чтобы переключиться обратно на YandexGPT:
```bash
LLM_PROVIDER=yandex
```

Чтобы использовать GigaChat:
```bash
LLM_PROVIDER=gigachat
```

## Отладка

Если возникают проблемы:

1. **Проверьте credentials:**
   ```python
   from app.config import config
   print(config.GIGACHAT_CREDENTIALS)  # Должен быть не пустым
   ```

2. **Проверьте доступность GigaChat:**
   ```python
   from langchain_gigachat.chat_models import GigaChat
   from app.config import config
   llm = GigaChat(credentials=config.GIGACHAT_CREDENTIALS)
   # Если инициализация прошла успешно, GigaChat доступен
   ```

3. **Проверьте логи:**
   - Ищите сообщения с префиксом `✅` для успешных операций
   - Ищите сообщения с префиксом `❌` или `⚠️` для ошибок

## Следующие шаги

После успешного тестирования timeline агента:
1. Обновить остальные агенты для использования `create_llm()`
2. Протестировать function calling на реальных задачах
3. Сравнить качество результатов с YandexGPT
4. Принять решение о полной миграции или гибридном подходе

