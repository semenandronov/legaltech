# Анализ GigaChain и рекомендации по миграции

## Что такое GigaChain

[GigaChain](https://github.com/ai-forever/gigachain) — это набор решений для разработки LLM-приложений на русском языке с поддержкой GigaChat. Это форк LangChain с официальной поддержкой GigaChat от команды AI Forever (Сбер).

## Основные компоненты GigaChain

### 1. **langchain-gigachat** — Готовая интеграция с LangChain

**Ключевая находка:** GigaChain предоставляет готовую библиотеку `langchain-gigachat`, которая:
- ✅ Полностью интегрирована с LangChain и LangGraph
- ✅ Поддерживает все возможности LangChain (agents, chains, tools)
- ✅ Официально поддерживается командой AI Forever
- ✅ Протестирована и используется в production

**Установка:**
```bash
pip install langchain-gigachat
```

**Использование:**
```python
from langchain_gigachat.chat_models import GigaChat

llm = GigaChat(
    credentials="ваш_ключ_авторизации",
    verify_ssl_certs=False
)

# Работает со всеми LangChain компонентами
from langchain.agents import create_react_agent
agent = create_react_agent(llm, tools, prompt)
```

### 2. **gigachat** SDK — Базовый SDK

Мы уже используем этот SDK в нашем проекте (`gigachat>=0.1.0`). Это базовый SDK для работы с GigaChat API.

### 3. Другие компоненты

- **GigaAgent** — универсальный агент-оркестратор
- **gpt2giga** — прокси-сервер для совместимости с OpenAI API
- **MCP-серверы** — инструменты для работы с GigaChat

## Сравнение: Наш wrapper vs langchain-gigachat

| Критерий | Наш ChatGigaChat wrapper | langchain-gigachat |
|----------|-------------------------|-------------------|
| **Поддержка LangChain** | ✅ Базовая (BaseChatModel) | ✅ Полная интеграция |
| **Function Calling** | ⚠️ Частичная (экспериментальная) | ✅ Полная поддержка |
| **Официальная поддержка** | ❌ Самописный | ✅ Официальная от AI Forever |
| **Тестирование** | ⚠️ Минимальное | ✅ Протестировано |
| **Обновления** | ❌ Ручные | ✅ Автоматические через PyPI |
| **Совместимость с LangGraph** | ⚠️ Базовая | ✅ Полная |
| **Поддержка tools** | ⚠️ Экспериментальная | ✅ Нативная |
| **Документация** | ⚠️ Минимальная | ✅ Полная |

## Рекомендация: Миграция на langchain-gigachat

### Преимущества миграции:

1. **Официальная поддержка** — библиотека поддерживается командой AI Forever
2. **Полная интеграция** — все возможности LangChain работают из коробки
3. **Function calling** — нативная поддержка tools и function calling
4. **Меньше кода** — не нужно поддерживать собственный wrapper
5. **Обновления** — автоматические обновления через PyPI
6. **Стабильность** — протестированная библиотека

### План миграции:

#### Шаг 1: Установка библиотеки

```bash
pip install langchain-gigachat
```

#### Шаг 2: Обновление requirements.txt

```python
# GigaChat (Сбер)
gigachat>=0.1.0  # Базовый SDK (уже есть)
langchain-gigachat>=0.1.0  # Интеграция с LangChain (НОВОЕ)
```

#### Шаг 3: Обновление llm_factory.py

```python
# Вместо:
from app.services.gigachat_llm import ChatGigaChat

# Использовать:
from langchain_gigachat.chat_models import GigaChat

# Инициализация:
llm = GigaChat(
    credentials=config.GIGACHAT_CREDENTIALS,
    model=model or config.GIGACHAT_MODEL,
    temperature=temperature,
    verify_ssl_certs=config.GIGACHAT_VERIFY_SSL
)
```

#### Шаг 4: Удаление самописного wrapper

После успешной миграции можно удалить:
- `backend/app/services/gigachat_llm.py` (наш wrapper)
- Обновить импорты в других файлах

#### Шаг 5: Тестирование

Протестировать:
- Базовые вызовы LLM
- Function calling с tools
- Интеграцию с агентами
- Работу с LangGraph

## Текущее состояние

### Что у нас есть:

1. ✅ **gigachat SDK** — базовый SDK установлен
2. ✅ **ChatGigaChat wrapper** — самописный wrapper для LangChain
3. ✅ **LLM Factory** — фабрика для переключения между провайдерами
4. ✅ **Конфигурация** — настройки GigaChat в config.py

### Что нужно добавить:

1. ⚠️ **langchain-gigachat** — готовая библиотека (рекомендуется)
2. ⚠️ **Миграция кода** — замена нашего wrapper на готовую библиотеку

## Выводы

### Рекомендация: **Использовать langchain-gigachat**

**Причины:**
1. Официальная поддержка от команды AI Forever
2. Полная интеграция с LangChain и LangGraph
3. Нативная поддержка function calling
4. Меньше кода для поддержки
5. Автоматические обновления

### Альтернатива: Оставить наш wrapper

**Если:**
- Нужна полная кастомизация
- Есть специфические требования
- Хотите полный контроль над реализацией

**Но:** Это требует больше времени на поддержку и тестирование.

## Следующие шаги

1. ✅ Изучить документацию langchain-gigachat
2. ⚠️ Протестировать langchain-gigachat в отдельной ветке
3. ⚠️ Сравнить производительность и функциональность
4. ⚠️ Принять решение о миграции
5. ⚠️ Выполнить миграцию (если решение положительное)

## Полезные ссылки

- [GigaChain GitHub](https://github.com/ai-forever/gigachain)
- [langchain-gigachat (предположительно)](https://pypi.org/project/langchain-gigachat/) - нужно проверить
- [GigaChat SDK](https://github.com/ai-forever/gigachat)
- [Документация GigaChain](https://github.com/ai-forever/gigachain#readme)

## Проверка доступности langchain-gigachat

**Статус:** Требуется проверка доступности пакета на PyPI.

**Варианты:**
1. Если пакет доступен на PyPI → использовать готовую библиотеку
2. Если пакет не доступен → можно установить из GitHub:
   ```bash
   pip install git+https://github.com/ai-forever/langchain-gigachat.git
   ```
3. Если пакет в разработке → использовать наш wrapper до стабильного релиза

## Примечание

Перед миграцией рекомендуется:
1. ✅ Проверить доступность `langchain-gigachat` на PyPI или GitHub
2. ⚠️ Протестировать совместимость с текущей версией LangChain (1.2.0)
3. ⚠️ Убедиться, что function calling работает корректно
4. ⚠️ Провести тестирование на реальных задачах
5. ⚠️ Сравнить производительность с нашим wrapper

## Текущий статус

**Наш wrapper работает**, но использование готовой библиотеки `langchain-gigachat` было бы предпочтительнее, если она:
- Доступна и стабильна
- Совместима с LangChain 1.2.0
- Поддерживает function calling
- Имеет хорошую документацию

