# Миграция на langchain-gigachat

## Что изменилось

Мы мигрировали с самописного `ChatGigaChat` wrapper на официальную библиотеку **`langchain-gigachat`** от AI Forever (Сбер).

## Преимущества миграции

1. ✅ **Официальная поддержка** - Библиотека поддерживается командой AI Forever
2. ✅ **Полная интеграция** - Все возможности LangChain работают из коробки
3. ✅ **Function calling** - Нативная поддержка tools и function calling
4. ✅ **Меньше кода** - Не нужно поддерживать собственный wrapper
5. ✅ **Обновления** - Автоматические обновления через PyPI
6. ✅ **Стабильность** - Протестированная библиотека

## Установка

```bash
pip install langchain-gigachat
```

Или через requirements.txt:
```
langchain-gigachat>=0.1.0
```

## Изменения в коде

### До (наш wrapper):
```python
from app.services.gigachat_llm import ChatGigaChat

llm = ChatGigaChat(
    credentials=config.GIGACHAT_CREDENTIALS,
    temperature=0.1
)
```

### После (langchain-gigachat):
```python
from langchain_gigachat.chat_models import GigaChat

llm = GigaChat(
    credentials=config.GIGACHAT_CREDENTIALS,
    temperature=0.1,
    verify_ssl_certs=config.GIGACHAT_VERIFY_SSL
)
```

## Обновленные файлы

1. ✅ `backend/requirements.txt` - Добавлен `langchain-gigachat`
2. ✅ `backend/app/services/llm_factory.py` - Использует `langchain_gigachat.chat_models.GigaChat`
3. ✅ `backend/test_gigachat_integration.py` - Обновлен для использования новой библиотеки
4. ✅ `backend/GIGACHAT_SETUP.md` - Обновлена документация

## Устаревшие файлы

После успешного тестирования можно удалить:
- `backend/app/services/gigachat_llm.py` - Наш самописный wrapper (больше не нужен)

**Примечание:** Пока оставляем файл на случай необходимости отката, но он больше не используется.

## Тестирование

Запустите тестовый скрипт:
```bash
cd backend
python test_gigachat_integration.py
```

Тесты проверят:
1. ✅ Валидность credentials
2. ✅ Базовый вызов GigaChat
3. ✅ Function calling с tools
4. ✅ LLM Factory

## Совместимость

- ✅ LangChain 1.2.0
- ✅ LangGraph 1.0.5
- ✅ Все существующие агенты работают без изменений
- ✅ Function calling работает из коробки

## Откат (если нужен)

Если возникнут проблемы, можно временно вернуться к нашему wrapper:

1. В `llm_factory.py` заменить:
   ```python
   from langchain_gigachat.chat_models import GigaChat
   ```
   на:
   ```python
   from app.services.gigachat_llm import ChatGigaChat
   ```

2. Заменить `GigaChat` на `ChatGigaChat` в инициализации

Но рекомендуется использовать официальную библиотеку для лучшей поддержки.

## Документация

- [GigaChain GitHub](https://github.com/ai-forever/gigachain)
- [langchain-gigachat документация](https://developers.sber.ru/docs/ru/gigachain/tools/python/langchain-gigachat)
- [GigaChat SDK](https://github.com/ai-forever/gigachat)

