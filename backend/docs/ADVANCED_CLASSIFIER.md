# Advanced Complexity Classifier

## Обзор

`AdvancedComplexityClassifier` - улучшенный классификатор запросов пользователя с поддержкой hybrid пути и state-based классификации. Является расширением базового `ComplexityClassifier` с дополнительными возможностями.

## Основные возможности

1. **Многоуровневая классификация**: simple/complex/hybrid
2. **State-based классификация**: учет контекста дела при классификации
3. **Поддержка hybrid пути**: комбинированная обработка (RAG + Agent)
4. **Интеграция с LangGraph**: готовность к использованию как узел графа
5. **Уточнение запросов**: определение необходимости уточнения при низкой уверенности
6. **Предсказание сложности**: оценка сложности задачи (low/medium/high)

## Типы классификации

### Simple (простой вопрос)
- Вопросы с "какие", "что", "где", "когда", "кто", "почему"
- Разговорные фразы
- Запросы на получение информации (статьи кодексов, тексты документов)
- Требует немедленного ответа на основе документов
- **Путь**: RAG

Примеры:
- "Какие ключевые сроки важны в этом деле?"
- "Что говорится в договоре о сроках?"
- "Пришли статью 135 ГПК"

### Complex (сложная задача)
- Команды на выполнение анализа (извлеки, найди, проанализируй, составь)
- Требует запуска фонового анализа через агентов
- Многошаговые задачи с зависимостями
- **Путь**: Agent

Примеры:
- "Извлеки все даты из документов"
- "Найди противоречия между документами"
- "Составь таблицу с судьями и судами"

### Hybrid (комбинированный запрос)
- Сначала RAG для контекста, затем агенты для анализа
- Запросы типа "Что говорит договор о сроках и найди все нарушения"
- Требует и информационного ответа, и выполнения анализа
- **Путь**: Hybrid (RAG → Agent)

Примеры:
- "Покажи статью 123 ГК и проанализируй риски"
- "Что в договоре и найди противоречия"
- "Пришли статью 135 ГПК и составь резюме дела"

## Использование

### Базовое использование

```python
from app.services.langchain_agents.advanced_complexity_classifier import AdvancedComplexityClassifier
from app.services.llm_factory import create_llm
from app.routes.assistant_chat import get_classification_cache

# Создание классификатора
llm = create_llm(temperature=0.0, top_p=1.0, max_tokens=500)
cache = get_classification_cache()
classifier = AdvancedComplexityClassifier(
    llm=llm,
    cache=cache,
    confidence_threshold=0.7  # Порог уверенности для requires_clarification
)

# Классификация запроса
query = "Покажи статью 123 ГК и проанализируй риски"
result = classifier.classify(query)

print(f"Label: {result.label}")  # hybrid
print(f"Path: {result.recommended_path}")  # hybrid
print(f"Confidence: {result.confidence}")  # 0.85
print(f"Suggested agents: {result.suggested_agents}")  # ["risk"]
print(f"RAG queries: {result.rag_queries}")  # ["Покажи статью 123 ГК"]
```

### Использование с контекстом

```python
# Классификация с учетом контекста дела
context = {
    "case_id": "case-123",
    "workspace_files": ["doc1.pdf", "doc2.pdf"],
    "previous_results": {
        "entity_extraction": True,
        "timeline": True
    }
}

result = classifier.classify(query, context=context)
```

### Использование с state (LangGraph)

```python
# Классификация на основе state графа
state = {
    "case_id": "case-123",
    "messages": [HumanMessage(content="Покажи статью 123 ГК и проанализируй риски")],
    "timeline_result": {...},
    "workspace_files": ["doc1.pdf"]
}

result = classifier.classify_from_state(state, use_command=False)
```

### Использование в PipelineService

```python
from app.services.langchain_agents.pipeline_service import PipelineService

# PipelineService автоматически использует AdvancedComplexityClassifier
pipeline_service = PipelineService(
    db=db,
    rag_service=rag_service,
    document_processor=document_processor,
    use_advanced_classifier=True  # По умолчанию True
)

# Классификация и обработка
classification = await pipeline_service.process_request(
    case_id="case-123",
    query="Покажи статью 123 ГК и проанализируй риски",
    current_user=user
)

# Потоковая обработка с автоматической маршрутизацией
async for chunk in pipeline_service.stream_response(
    case_id="case-123",
    query="Покажи статью 123 ГК и проанализируй риски",
    current_user=user,
    classification=classification
):
    print(chunk)
```

## Структура результата

### EnhancedClassificationResult

```python
class EnhancedClassificationResult(BaseModel):
    label: Literal["simple", "complex", "hybrid"]
    confidence: float  # 0.0-1.0
    rationale: str
    recommended_path: Literal["rag", "agent", "hybrid"]
    requires_clarification: bool
    suggested_agents: List[str]
    rag_queries: List[str]
    estimated_complexity: Literal["low", "medium", "high"]
    metadata: Dict[str, Any]
```

### Поля результата

- **label**: Тип запроса (simple/complex/hybrid)
- **confidence**: Уверенность в классификации (0.0-1.0)
- **rationale**: Объяснение решения
- **recommended_path**: Рекомендуемый путь обработки (rag/agent/hybrid)
- **requires_clarification**: Требуется ли уточнение от пользователя (если confidence < threshold)
- **suggested_agents**: Список предлагаемых агентов для выполнения (если complex/hybrid)
- **rag_queries**: Список запросов для RAG (если simple/hybrid)
- **estimated_complexity**: Оценка сложности задачи (low/medium/high)
- **metadata**: Дополнительные метаданные

## Rule-based классификация

Классификатор использует rule-based быструю проверку для очевидных случаев:

1. **Статьи кодексов** → всегда SIMPLE (confidence 0.99)
   - Паттерны: "статья 135 ГПК", "пришли статью", "покажи статью"

2. **Приветствия** → всегда SIMPLE (confidence 0.95)
   - Паттерны: "привет", "здравствуй", "hello"

3. **Команды на анализ** → COMPLEX (confidence 0.90)
   - Паттерны: "извлеки", "найди", "проанализируй", "составь" + объекты анализа

## Кэширование

Классификатор использует кэш для оптимизации производительности:

- Кэшируются результаты классификации на 1 час (TTL)
- Ключ кэша: хеш нормализованного запроса + case_id (если есть)
- Автоматическая инвалидация при изменении контекста

## Интеграция с LangGraph

Классификатор готов к использованию как узел графа LangGraph:

```python
from app.services.langchain_agents.classification_node import classification_node, route_after_classification

# Добавление узла в граф
graph.add_node("classification", classification_node)

# Добавление conditional edges
graph.add_conditional_edges(
    "classification",
    route_after_classification,
    {
        "rag_node": "rag_node",
        "supervisor": "supervisor",
        "hybrid_start": "hybrid_start",
        "clarification_needed": "clarification_needed"
    }
)
```

## Миграция с ComplexityClassifier

### Обратная совместимость

`AdvancedComplexityClassifier` расширяет функциональность `ComplexityClassifier`, но сохраняет обратную совместимость:

- Метод `classify()` имеет такую же сигнатуру
- Возвращает расширенный результат, но может использоваться как замена
- `PipelineService` автоматически использует новый классификатор при `use_advanced_classifier=True`

### Миграция кода

**Было:**
```python
from app.services.langchain_agents.complexity_classifier import ComplexityClassifier

classifier = ComplexityClassifier(llm=llm, cache=cache)
result = classifier.classify(query)
# result.label: "simple" | "complex"
# result.recommended_path: "rag" | "agent"
```

**Стало:**
```python
from app.services.langchain_agents.advanced_complexity_classifier import AdvancedComplexityClassifier

classifier = AdvancedComplexityClassifier(llm=llm, cache=cache)
result = classifier.classify(query)
# result.label: "simple" | "complex" | "hybrid"
# result.recommended_path: "rag" | "agent" | "hybrid"
# result.suggested_agents: List[str]
# result.rag_queries: List[str]
# result.requires_clarification: bool
```

## Примеры использования

### Пример 1: Простой запрос

```python
query = "Пришли статью 135 ГПК"
result = classifier.classify(query)

# Результат:
# label: "simple"
# recommended_path: "rag"
# rag_queries: ["Пришли статью 135 ГПК"]
# confidence: 0.99
```

### Пример 2: Сложная задача

```python
query = "Извлеки все даты из документов и составь таблицу"
result = classifier.classify(query)

# Результат:
# label: "complex"
# recommended_path: "agent"
# suggested_agents: ["entity_extraction"]
# estimated_complexity: "medium"
# confidence: 0.90
```

### Пример 3: Hybrid запрос

```python
query = "Покажи статью 123 ГК и проанализируй риски"
result = classifier.classify(query)

# Результат:
# label: "hybrid"
# recommended_path: "hybrid"
# rag_queries: ["Покажи статью 123 ГК"]
# suggested_agents: ["risk"]
# estimated_complexity: "medium"
# confidence: 0.85
```

### Пример 4: Запрос с низкой уверенностью

```python
classifier = AdvancedComplexityClassifier(
    llm=llm,
    cache=cache,
    confidence_threshold=0.8  # Высокий порог
)

query = "Что-то непонятное"
result = classifier.classify(query)

if result.confidence < 0.8:
    # В classify_from_state будет установлен requires_clarification
    state = {"messages": [HumanMessage(content=query)]}
    result_with_state = classifier.classify_from_state(state)
    # result_with_state.requires_clarification: True
```

## Производительность

- **Rule-based классификация**: < 1ms (для очевидных случаев)
- **Кэшированная классификация**: < 1ms
- **LLM классификация**: 100-500ms (в зависимости от LLM)
- **С кэшированием**: 80-90% запросов обрабатываются через rule-based или кэш

## Отладка

Включите логирование для отладки:

```python
import logging
logging.getLogger("app.services.langchain_agents.advanced_complexity_classifier").setLevel(logging.DEBUG)
```

Логи содержат:
- Результаты rule-based классификации
- Попадания в кэш
- Результаты LLM классификации
- Предупреждения о низкой уверенности

