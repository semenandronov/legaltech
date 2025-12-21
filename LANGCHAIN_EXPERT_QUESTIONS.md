# Вопросы для эксперта по LangChain

## Критические архитектурные вопросы

### 1. Vector Store: pgvector vs Yandex Vector Store

**Контекст:**
- Сейчас используется Yandex Vector Store (внешний сервис)
- Описанная архитектура предлагает PostgreSQL + pgvector
- Нужно хранить embeddings локально для multi-tenant изоляции

**Вопросы:**
1. **Какие преимущества/недостатки pgvector vs внешних векторных хранилищ (Yandex Vector Store, Pinecone) для production e-discovery системы?**
   - Производительность при больших объемах (миллионы документов)?
   - Multi-tenant изоляция и безопасность?
   - Масштабируемость и стоимость?

2. **Как правильно организовать pgvector с LangChain для multi-tenant системы?**
   - Один collection на дело или один на все дела с фильтрацией?
   - Как эффективно фильтровать по `case_id` в `PGVector.as_retriever()`?
   - Какой размер embeddings оптимален для юридических документов (Yandex vs OpenAI embeddings)?

3. **Миграция данных: как перенести существующие embeddings из Yandex Vector Store в pgvector?**
   - Нужно ли пересчитывать embeddings или можно экспортировать?
   - Как минимизировать downtime при миграции?

---

### 2. RAG Chain: create_retrieval_chain vs кастомный подход

**Контекст:**
- Сейчас используется кастомный подход: `retrieve_relevant_chunks()` → `generate_with_sources()`
- Roadmap предлагает стандартный `create_retrieval_chain` + `create_stuff_documents_chain`
- Нужны legal-specific промпты с требованиями FRCP compliance

**Вопросы:**
4. **Когда использовать `create_retrieval_chain` vs кастомный подход?**
   - Преимущества стандартного подхода для production?
   - Как интегрировать legal-specific требования (цитирование, источники, compliance) в стандартный chain?
   - Как передать результаты нескольких агентов (timeline, discrepancies) в RAG промпт?

5. **Как правильно структурировать промпт для legal RAG?**
   - Где лучше определять system prompt: в `ChatPromptTemplate` или в LLM wrapper?
   - Как обеспечить обязательное цитирование источников (file, page, line)?
   - Как обрабатывать случаи когда документы не найдены (FRCP compliance)?

6. **Retrieval strategies: когда использовать MultiQuery, Compression, Ensemble?**
   - Для юридических запросов (например "найди противоречия между CEO и CFO") какая стратегия лучше?
   - Как оптимизировать cost vs quality для разных типов запросов?
   - Можно ли динамически выбирать стратегию в зависимости от типа запроса?

---

### 3. LangGraph: PostgresSaver и состояние

**Контекст:**
- Сейчас используется MemorySaver (временно отключен PostgresSaver)
- Multi-agent workflow с зависимостями между агентами
- Нужно сохранять состояние между перезапусками сервера

**Вопросы:**
7. **PostgresSaver: правильная настройка для production?**
   - Как правильно инициализировать PostgresSaver из connection string?
   - Нужно ли вызывать `setup()` при каждом старте или только один раз?
   - Как управлять TTL для checkpoint'ов (30 дней для legal cases)?

8. **Multi-tenant checkpointing: как изолировать состояния разных дел?**
   - Один checkpointer для всех дел или отдельный thread_id на дело?
   - Как правильно использовать `thread_id` для изоляции?
   - Влияет ли это на производительность при сотнях активных дел?

9. **State management: как оптимизировать размер состояния?**
   - Когда хранить полные результаты агентов в state, а когда только ссылки на БД?
   - Как избежать дублирования данных между LangGraph state и PostgreSQL?
   - Best practices для TypedDict state с большими данными?

---

### 4. Agents и Tools: интеграция с YandexGPT

**Контекст:**
- Используется YandexGPT через кастомный `ChatYandexGPT` wrapper
- Множество агентов с @tool декораторами
- Нужна структурированная output (Pydantic models) для юридических данных

**Вопросы:**
10. **YandexGPT integration: оптимальный подход?**
    - Правильно ли использовать кастомный `BaseChatModel` wrapper или есть лучше способ?
    - Поддерживает ли YandexGPT structured output (`.with_structured_output()`)?
    - Как обрабатывать rate limits и retries для YandexGPT в LangChain?

11. **Tools и LangGraph: как правильно передавать runtime в tools?**
    - В roadmap показано `ToolRuntime` - это актуально для LangGraph 1.0?
    - Как tools получают доступ к database session и другим сервисам?
    - Как обеспечить thread-safety для tools в concurrent execution?

12. **Structured output для юридических агентов: best practices?**
    - Как валидировать Pydantic models для privilege checks, risk analysis?
    - Что делать если LLM возвращает невалидный JSON (fallback стратегия)?
    - Как обрабатывать confidence scores и uncertainty в structured output?

---

### 5. Streaming и WebSocket

**Контекст:**
- Нужен real-time streaming ответов в чат
- LangGraph поддерживает streaming через `graph.stream()`
- Frontend использует React

**Вопросы:**
13. **LangGraph streaming через WebSocket: правильная архитектура?**
    - Как правильно использовать `graph.stream(stream_mode="values")` в FastAPI WebSocket?
    - Как обрабатывать ошибки в streaming (не прерывать соединение)?
    - Как передавать progress updates (агент X завершен, агент Y начался)?

14. **Streaming для multi-agent workflow: что stream'ить?**
    - Stream'ить результаты каждого агента отдельно или только финальный ответ?
    - Как показать пользователю прогресс выполнения агентов (timeline → risk → summary)?
    - Как обрабатывать long-running agents (privilege check на 1000 документов)?

---

### 6. Document Processing и Embeddings

**Контекст:**
- Документы разбиваются на chunks через LangChain splitters
- Нужно сохранять metadata (source_file, source_page, source_line) для цитирования
- Используются Yandex embeddings

**Вопросы:**
15. **Chunking strategy для юридических документов: что оптимально?**
    - Какой размер chunk оптимален для юридических текстов (contracts, emails, memos)?
    - Как сохранять контекст между chunks (overlap, hierarchical chunking)?
    - Как обрабатывать таблицы и структурированные данные в документах?

16. **Embeddings: Yandex vs OpenAI для русского юридического текста?**
    - Какие embeddings лучше для русскоязычных юридических документов?
    - Как обеспечить consistency embeddings между разными моделями?
    - Нужно ли fine-tune embeddings для юридического домена?

17. **Metadata preservation: как правильно хранить source information?**
    - Как структурировать metadata для эффективного filtering в pgvector?
    - Как обрабатывать metadata при hierarchical chunking?
    - Как обеспечить точное цитирование (page, line) в RAG ответах?

---

### 7. Performance и Optimization

**Контекст:**
- Множество параллельных агентов
- Большие объемы документов (10GB+ на дело)
- Нужна быстрая реакция для юристов

**Вопросы:**
18. **Parallel agent execution: как оптимизировать?**
    - LangGraph автоматически распараллеливает независимые агенты?
    - Как ограничить concurrent LLM calls (rate limiting)?
    - Нужно ли использовать async/await для agent nodes?

19. **Caching и оптимизация: best practices?**
    - Как кэшировать embeddings для одинаковых документов?
    - Стоит ли кэшировать результаты агентов (privilege checks, risk analysis)?
    - Как использовать LangChain's cache для LLM calls?

20. **Batch processing: как обрабатывать большие дела?**
    - Как разбить обработку 10000 документов на батчи?
    - Как отслеживать прогресс batch processing?
    - Как обрабатывать failures в batch (retry стратегия)?

---

### 8. Relationship Agent (новый агент)

**Контекст:**
- Нужен агент для построения графа связей между участниками
- Уже есть entity extraction агент
- Нужно визуализировать граф на фронте

**Вопросы:**
21. **Relationship Agent: как правильно реализовать?**
    - Отдельный агент или расширить entity extraction?
    - Как использовать LLM для извлечения relationships между entities?
    - Как структурировать output (nodes/edges) для D3.js визуализации?

22. **Entity linking: как связать упоминания одного человека в разных документах?**
    - Как обрабатывать вариации имен (Иван Иванов vs И. Иванов)?
    - Как определить, что два упоминания относятся к одному entity?
    - Нужен ли отдельный entity linking шаг или LLM справится?

---

### 9. Compliance и LangSmith

**Контекст:**
- LangSmith уже настроен
- Нужен audit trail для юридических требований
- FRCP compliance требует полной трассируемости

**Вопросы:**
23. **LangSmith для legal compliance: что дополнительно нужно?**
    - Достаточно ли LangSmith для audit trail или нужны дополнительные логи?
    - Как связать LangSmith traces с делами в PostgreSQL?
    - Как экспортировать traces для судебных разбирательств?

24. **Prompt versioning: как управлять изменениями промптов?**
    - Как версионировать промпты агентов для compliance?
    - Как отследить, какой промпт использовался для конкретного анализа?
    - Нужен ли prompt registry для production?

---

### 10. Production Deployment

**Контекст:**
- Используется Render для deployment
- FastAPI backend
- PostgreSQL (Neon)

**Вопросы:**
25. **LangGraph в production: что нужно для масштабирования?**
    - Как правильно настроить connection pooling для PostgresSaver?
    - Как обрабатывать serverless cold starts (Render, AWS Lambda)?
    - Нужен ли Redis для shared state между instances?

26. **Monitoring и observability: что мониторить?**
    - Какие метрики критичны для LangGraph workflow (execution time, success rate)?
    - Как интегрировать LangSmith с APM tools (Datadog, New Relic)?
    - Как алертить на failures в agent workflow?

---

## Приоритетные вопросы для быстрого старта

Если нужно начать немедленно, вот топ-5 самых критичных вопросов:

1. **PostgresSaver setup** (вопрос 7) - нужно для production
2. **pgvector vs Yandex Vector Store** (вопросы 1-3) - архитектурное решение
3. **create_retrieval_chain для legal RAG** (вопросы 4-6) - стандартизация
4. **Multi-tenant checkpointing** (вопрос 8) - изоляция данных
5. **Streaming через WebSocket** (вопрос 13) - UX улучшение

