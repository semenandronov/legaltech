# Настройка GigaChat для тестирования

## Шаг 1: Установка зависимостей

```bash
cd backend
pip install gigachat
```

Или добавьте в `requirements.txt`:
```
gigachat>=0.1.0
```

## Шаг 2: Настройка переменных окружения

Добавьте в файл `.env` в корне проекта:

```bash
# GigaChat (Сбер)
GIGACHAT_CREDENTIALS=MDE5YjVmNmUtOTg5OS03YzUyLTgxNWUtM2JiMDhmNjAwZTJiOjMwNmVkOTlkLThiNjctNGFmMy1hNTRjLWI1YjA2ODhkOGQyZA==
GIGACHAT_MODEL=GigaChat
GIGACHAT_VERIFY_SSL=true

# Выбор LLM провайдера для агентов
LLM_PROVIDER=gigachat  # или "yandex" для переключения обратно
```

## Шаг 3: Тестирование

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

### Новые файлы:
- `backend/app/services/gigachat_llm.py` - Wrapper для GigaChat
- `backend/app/services/llm_factory.py` - Factory для выбора LLM провайдера
- `backend/test_gigachat_integration.py` - Тестовый скрипт

### Обновленные файлы:
- `backend/app/config.py` - Добавлены настройки GigaChat
- `backend/app/services/langchain_agents/timeline_node.py` - Использует `create_llm()` вместо прямого `ChatYandexGPT`
- `backend/app/services/langchain_agents/llm_helper.py` - Использует `create_llm()` вместо прямого `ChatYandexGPT`
- `backend/requirements.txt` - Добавлен `gigachat`

## Преимущества GigaChat

1. ✅ **Function Calling** - Поддерживает `bind_tools()`, в отличие от YandexGPT
2. ✅ **Автономность агентов** - LLM сам решает, когда вызывать инструменты
3. ✅ **Итеративный поиск** - Многошаговые запросы с автоматическим выбором инструментов
4. ✅ **Меньше токенов** - Только результаты вызовов в контексте, а не все документы

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
   from app.services.gigachat_llm import ChatGigaChat
   llm = ChatGigaChat()
   print(llm.is_available())  # Должно быть True
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

