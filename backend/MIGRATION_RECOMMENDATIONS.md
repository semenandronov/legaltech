# Рекомендации по миграции и улучшению на основе изучения репозиториев

## 🔍 Ключевые находки

### 1. Устаревший API: `create_react_agent`

**Текущее состояние:**
```python
from langgraph.prebuilt import create_react_agent
agent = create_react_agent(llm, tools, messages_modifier=prompt)
```

**Проблема:**
- `create_react_agent` из `langgraph.prebuilt` устарел в LangChain v1.0+
- Рекомендуется использовать `create_agent` из `langchain.agents`

**Новый API:**
```python
from langchain.agents import create_agent

agent = create_agent(
    model=llm,  # или строка "openai:gpt-4o"
    tools=tools,
    system_prompt=prompt  # было messages_modifier
)
```

**Важно:** Проверить совместимость с текущими версиями перед миграцией!

### 2. Архитектурные улучшения

#### A. PostgreSQL Checkpointer (Критично)

**Текущее:**
```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
```

**Улучшение:**
```python
from langgraph.checkpoint.postgres import PostgresSaver

# Требуется: langgraph-checkpoint-postgres в requirements.txt
checkpointer = PostgresSaver.from_conn_string(config.DATABASE_URL)
checkpointer.setup()  # Создать таблицы
compiled_graph = graph.compile(checkpointer=checkpointer)
```

#### B. Middleware система (из Deep Agents)

**Идея:** Создать переиспользуемый middleware для наших агентов:

```python
class LegalAnalysisMiddleware:
    """Middleware для юридического анализа"""
    
    def __init__(self, rag_service, document_processor):
        self.rag_service = rag_service
        self.document_processor = document_processor
    
    @property
    def tools(self):
        return get_all_tools()
    
    def get_prompt(self, agent_type: str):
        return get_agent_prompt(agent_type)
    
    def create_agent(self, agent_type: str, llm):
        """Создать агента с правильными инструментами и промптом"""
        tools = self.tools
        prompt = self.get_prompt(agent_type)
        
        # Использовать новый API если доступен
        try:
            from langchain.agents import create_agent
            return create_agent(
                model=llm,
                tools=tools,
                system_prompt=prompt
            )
        except ImportError:
            # Fallback на старый API
            from langgraph.prebuilt import create_react_agent
            return create_react_agent(llm, tools, messages_modifier=prompt)
```

## 📋 План миграции

### Этап 1: Проверка совместимости (Немедленно)

1. Проверить, доступен ли `create_agent` в текущих версиях:
```python
try:
    from langchain.agents import create_agent
    print("✅ create_agent доступен")
except ImportError:
    print("⚠️ create_agent недоступен, используем create_react_agent")
```

2. Если доступен - создать wrapper для обратной совместимости

### Этап 2: Миграция на PostgreSQL Checkpointer (Высокий приоритет)

1. Добавить зависимость:
```bash
# В requirements.txt
langgraph-checkpoint-postgres>=0.1.0
```

2. Обновить `graph.py`:
```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver

def create_analysis_graph(...):
    # ...
    # Попробовать использовать PostgreSQL, fallback на Memory
    try:
        checkpointer = PostgresSaver.from_conn_string(config.DATABASE_URL)
        # setup() можно вызвать отдельно при инициализации БД
        logger.info("Using PostgreSQL checkpointer")
    except Exception as e:
        logger.warning(f"PostgreSQL checkpointer failed, using MemorySaver: {e}")
        checkpointer = MemorySaver()
    
    compiled_graph = graph.compile(checkpointer=checkpointer)
    return compiled_graph
```

3. Создать миграцию для таблиц checkpointer (опционально, можно вызвать setup() при первом запуске)

### Этап 3: Интеграция LangSmith (Средний приоритет)

1. Добавить в `config.py`:
```python
# LangSmith Settings (optional)
LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "legal-ai-vault")
LANGSMITH_TRACING: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
```

2. Инициализировать в `main.py`:
```python
if config.LANGSMITH_TRACING and config.LANGSMITH_API_KEY:
    import os
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = config.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = config.LANGSMITH_PROJECT
    logger.info("LangSmith tracing enabled")
```

### Этап 4: Улучшение обработки ошибок (Средний приоритет)

Добавить retry логику через `tenacity`:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(config.AGENT_RETRY_COUNT),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def safe_node_execution(node_func, state: AnalysisState):
    """Безопасное выполнение узла с retry"""
    return node_func(state)
```

### Этап 5: Оптимизация производительности (Низкий приоритет)

Добавить параллельное выполнение независимых агентов через asyncio (см. LANGGRAPH_DEEP_ANALYSIS.md)

## 🎯 Итоговые рекомендации

### Немедленные действия:

1. ✅ **Проверить доступность `create_agent`** - создать wrapper для совместимости
2. ✅ **Добавить `langgraph-checkpoint-postgres`** в requirements.txt
3. ✅ **Подготовить миграцию на PostgreSQL checkpointer**

### Краткосрочные улучшения (1-2 недели):

4. ✅ **Интегрировать LangSmith** для мониторинга
5. ✅ **Улучшить обработку ошибок** с retry логикой

### Долгосрочные улучшения (опционально):

6. ⚠️ **Middleware система** для переиспользования
7. ⚠️ **Параллельное выполнение** для оптимизации
8. ⚠️ **Планирование (Todo List)** для больших дел

## 📚 Ссылки

- [LangChain v1 Migration Guide](https://docs.langchain.com/oss/python/migrate/langchain-v1)
- [LangGraph Checkpoints](https://docs.langchain.com/oss/python/langgraph/checkpoints)
- [LangSmith Integration](https://docs.langchain.com/langsmith/home)
