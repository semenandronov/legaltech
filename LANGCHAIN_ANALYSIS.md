# Анализ использования LangChain в LEGALCHAIN AI

## 📋 Текущее использование LangChain

### 1. Компоненты, которые мы используем

#### ✅ **Text Splitters (Разделение текста)**
**Файл**: `backend/app/services/document_processor.py`

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

self.text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,        # Размер чанка
    chunk_overlap=200,      # Перекрытие между чанками
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""]
)
```

**Что делает:**
- Разбивает большие документы на маленькие чанки (1000 символов)
- Сохраняет контекст через перекрытие (200 символов)
- Использует иерархию разделителей (параграфы → строки → предложения → слова)

**Зачем нужно:**
- LLM не может обработать весь документ сразу (лимит контекста)
- Меньшие чанки = более точный поиск релевантной информации
- Перекрытие сохраняет смысл на границах чанков

---

#### ✅ **Embeddings (Векторные представления)**
**Файл**: `backend/app/services/document_processor.py`

```python
from langchain_openai import OpenAIEmbeddings

self.embeddings = OpenAIEmbeddings(
    openai_api_key=config.OPENROUTER_API_KEY,
    openai_api_base=config.OPENROUTER_BASE_URL,
    model="text-embedding-ada-002"
)
```

**Что делает:**
- Преобразует текст в числовые векторы (embeddings)
- Позволяет находить семантически похожие тексты
- Работает через OpenRouter API (совместим с OpenAI)

**Зачем нужно:**
- Поиск по смыслу, а не по ключевым словам
- "договор" и "контракт" будут найдены вместе
- Основа для RAG (Retrieval Augmented Generation)

---

#### ✅ **Vector Stores (Векторные базы данных)**
**Файл**: `backend/app/services/document_processor.py`

```python
from langchain_community.vectorstores import Chroma

vector_store = Chroma.from_documents(
    documents=documents,
    embedding=self.embeddings,
    persist_directory=persist_directory
)
```

**Что делает:**
- Хранит документы как векторы в ChromaDB
- Быстрый семантический поиск (similarity search)
- Сохраняет на диск для постоянного хранения

**Зачем нужно:**
- Мгновенный поиск релевантных фрагментов
- Масштабируемость (миллионы документов)
- Персистентность (данные не теряются при перезапуске)

---

#### ✅ **LLM Integration (Интеграция с языковыми моделями)**
**Файл**: `backend/app/services/rag_service.py`

```python
from langchain_openai import ChatOpenAI

self.llm = ChatOpenAI(
    model=config.OPENROUTER_MODEL,
    openai_api_key=config.OPENROUTER_API_KEY,
    openai_api_base=config.OPENROUTER_BASE_URL,
    temperature=0.7,
    max_tokens=2000
)
```

**Что делает:**
- Подключается к LLM через OpenRouter
- Генерирует ответы на основе контекста
- Настраиваемые параметры (температура, токены)

**Зачем нужно:**
- Генерация ответов на русском языке
- Использование контекста из документов
- Гибкость выбора модели

---

#### ✅ **Prompt Templates (Шаблоны промптов)**
**Файл**: `backend/app/services/rag_service.py`

```python
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

system_template = """Ты эксперт по анализу юридических документов..."""
human_template = "{question}"

prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(system_template),
    HumanMessagePromptTemplate.from_template(human_template)
])
```

**Что делает:**
- Структурирует промпты для LLM
- Разделяет системные инструкции и пользовательские вопросы
- Поддерживает переменные (formatting)

**Зачем нужно:**
- Консистентность ответов
- Легко изменять инструкции
- Переиспользование шаблонов

---

#### ✅ **Document Objects (Объекты документов)**
**Файл**: `backend/app/services/document_processor.py`

```python
from langchain.schema import Document

documents.append(Document(
    page_content=chunk_text,
    metadata=chunk_metadata
))
```

**Что делает:**
- Стандартизированный формат для документов
- Хранит текст и метаданные вместе
- Совместимость между компонентами LangChain

**Зачем нужно:**
- Единый интерфейс для всех документов
- Метаданные (файл, страница, строки) сохраняются
- Легкая интеграция компонентов

---

## 🚀 Что мы НЕ используем (но могли бы!)

### 1. **Document Loaders (Загрузчики документов)**

**Текущая ситуация:**
Мы парсим файлы вручную через `file_parser.py` (pypdf, python-docx)

**Что предлагает LangChain:**
```python
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

# PDF
loader = PyPDFLoader("document.pdf")
documents = loader.load()  # Автоматически извлекает текст + метаданные

# DOCX
loader = Docx2txtLoader("document.docx")
documents = loader.load()

# Множественные файлы
from langchain_community.document_loaders import DirectoryLoader
loader = DirectoryLoader("./docs", glob="**/*.pdf")
documents = loader.load()
```

**Преимущества:**
- ✅ Автоматическое извлечение метаданных (страницы, автор, дата)
- ✅ Обработка сложных PDF (таблицы, изображения)
- ✅ Единый интерфейс для всех форматов
- ✅ Поддержка веб-страниц, YouTube, Notion и т.д.

**Рекомендация:** Заменить `file_parser.py` на LangChain loaders

---

### 2. **Retrieval Chains (Цепи извлечения)**

**Текущая ситуация:**
Мы вручную делаем: retrieve → format → generate

**Что предлагает LangChain:**
```python
from langchain.chains import RetrievalQA
from langchain.chains.question_answering import load_qa_chain

qa_chain = RetrievalQA.from_chain_type(
    llm=self.llm,
    chain_type="stuff",  # или "map_reduce", "refine"
    retriever=vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 5}
    ),
    return_source_documents=True
)

answer = qa_chain.invoke({"query": "Какие сроки в договоре?"})
```

**Преимущества:**
- ✅ Готовые стратегии обработки (stuff, map_reduce, refine)
- ✅ Автоматическое управление контекстом
- ✅ Встроенная обработка больших документов
- ✅ Меньше кода, больше функционала

**Рекомендация:** Использовать для сложных запросов

---

### 3. **Memory (Память для чата)**

**Текущая ситуация:**
Мы передаем историю вручную через `chat_history`

**Что предлагает LangChain:**
```python
from langchain.memory import ConversationBufferMemory, ConversationSummaryMemory

# Простая память
memory = ConversationBufferMemory(
    return_messages=True,
    memory_key="chat_history"
)

# Память с суммаризацией (для длинных диалогов)
memory = ConversationSummaryMemory(
    llm=self.llm,
    return_messages=True
)

# Использование в цепи
conversation_chain = ConversationalRetrievalChain.from_llm(
    llm=self.llm,
    retriever=vector_store.as_retriever(),
    memory=memory
)
```

**Преимущества:**
- ✅ Автоматическое управление контекстом
- ✅ Суммаризация старых сообщений (экономия токенов)
- ✅ Разные типы памяти (buffer, summary, entity)
- ✅ Сохранение состояния между запросами

**Рекомендация:** Использовать для улучшения контекста в чате

---

### 4. **Agents (Агенты)**

**Что это:**
Агенты могут использовать инструменты (tools) для выполнения действий

**Пример использования:**
```python
from langchain.agents import initialize_agent, Tool
from langchain.agents import AgentType

tools = [
    Tool(
        name="Search Documents",
        func=vector_store.similarity_search,
        description="Используй для поиска информации в документах дела"
    ),
    Tool(
        name="Calculate",
        func=calculator,
        description="Используй для математических расчетов"
    )
]

agent = initialize_agent(
    tools=tools,
    llm=self.llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# Агент сам решает, какие инструменты использовать
answer = agent.run("Какая сумма договора и когда она должна быть выплачена?")
```

**Преимущества:**
- ✅ Автоматический выбор инструментов
- ✅ Цепочка рассуждений (reasoning)
- ✅ Работа с несколькими источниками данных
- ✅ Выполнение действий (не только поиск)

**Рекомендация:** Для сложных многошаговых запросов

---

### 5. **Callbacks (Обратные вызовы)**

**Что это:**
Мониторинг и логирование выполнения цепей

**Пример:**
```python
from langchain.callbacks import StdOutCallbackHandler, FileCallbackHandler

callbacks = [
    StdOutCallbackHandler(),  # Вывод в консоль
    FileCallbackHandler("logs/langchain.log")  # Логи в файл
]

chain.run("query", callbacks=callbacks)
```

**Преимущества:**
- ✅ Отладка цепей
- ✅ Мониторинг производительности
- ✅ Логирование токенов и стоимости
- ✅ Визуализация выполнения

**Рекомендация:** Для production мониторинга

---

### 6. **Advanced Text Splitters**

**Текущая ситуация:**
Используем только `RecursiveCharacterTextSplitter`

**Дополнительные опции:**
```python
# Для кода
from langchain.text_splitter import Language, RecursiveCharacterTextSplitter
python_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.PYTHON,
    chunk_size=1000
)

# Для Markdown
from langchain.text_splitter import MarkdownTextSplitter
markdown_splitter = MarkdownTextSplitter(chunk_size=1000)

# Семантическое разделение (по смыслу, а не по размеру)
from langchain_experimental.text_splitter import SemanticChunker
semantic_splitter = SemanticChunker(embeddings=self.embeddings)
```

**Преимущества:**
- ✅ Сохранение структуры документа
- ✅ Разделение по смыслу, а не по размеру
- ✅ Лучшее качество для специфичных форматов

**Рекомендация:** Для юридических документов с таблицами/структурой

---

### 7. **Query Transformers (Трансформация запросов)**

**Что это:**
Улучшение запросов перед поиском

**Пример:**
```python
from langchain.retrievers.multi_query import MultiQueryRetriever

retriever = MultiQueryRetriever.from_llm(
    retriever=vector_store.as_retriever(),
    llm=self.llm
)

# Автоматически генерирует несколько вариантов запроса
# и ищет по всем, объединяя результаты
```

**Преимущества:**
- ✅ Лучшее покрытие поиска
- ✅ Обработка синонимов
- ✅ Расширение узких запросов

**Рекомендация:** Для улучшения качества поиска

---

### 8. **Reranking (Переранжирование)**

**Что это:**
Улучшение релевантности результатов после поиска

**Пример:**
```python
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import LLMChainExtractor

compressor = LLMChainExtractor.from_llm(llm=self.llm)
compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=vector_store.as_retriever()
)

# Извлекает только релевантные части найденных документов
```

**Преимущества:**
- ✅ Более точные результаты
- ✅ Удаление нерелевантных частей
- ✅ Экономия токенов

**Рекомендация:** Для критически важных запросов

---

## 📊 Сравнение: Текущий подход vs LangChain Chains

### Текущий подход (ручной):
```python
# 1. Получить релевантные чанки
relevant_docs = document_processor.retrieve_relevant_chunks(case_id, query, k=5)

# 2. Отформатировать источники
sources_text = format_sources_for_prompt(relevant_docs)

# 3. Создать промпт
prompt = create_prompt(sources_text, query)

# 4. Вызвать LLM
response = llm.invoke(prompt)

# 5. Отформатировать ответ
answer = response.content
sources = format_sources(relevant_docs)
```

**Плюсы:**
- ✅ Полный контроль
- ✅ Понятный код
- ✅ Легко кастомизировать

**Минусы:**
- ❌ Много кода
- ❌ Нужно вручную обрабатывать edge cases
- ❌ Нет готовых паттернов

---

### LangChain Chains (автоматический):
```python
from langchain.chains import RetrievalQA

qa_chain = RetrievalQA.from_chain_type(
    llm=self.llm,
    chain_type="stuff",
    retriever=vector_store.as_retriever(search_kwargs={"k": 5}),
    return_source_documents=True
)

result = qa_chain.invoke({"query": query})
answer = result["result"]
sources = result["source_documents"]
```

**Плюсы:**
- ✅ Меньше кода
- ✅ Готовые паттерны
- ✅ Автоматическая обработка ошибок
- ✅ Оптимизация контекста

**Минусы:**
- ❌ Меньше контроля
- ❌ Нужно изучать API
- ❌ Может быть избыточно для простых случаев

---

## 🎯 Рекомендации по улучшению

### Приоритет 1: Document Loaders
**Зачем:** Улучшение качества парсинга, автоматические метаданные

**Действие:**
```python
# Заменить file_parser.py на LangChain loaders
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

def parse_file_with_langchain(content: bytes, filename: str) -> str:
    # Сохранить во временный файл
    temp_path = save_temp_file(content, filename)
    
    # Использовать LangChain loader
    if filename.endswith('.pdf'):
        loader = PyPDFLoader(temp_path)
    elif filename.endswith('.docx'):
        loader = Docx2txtLoader(temp_path)
    
    documents = loader.load()
    return "\n\n".join([doc.page_content for doc in documents])
```

---

### Приоритет 2: Retrieval Chains
**Зачем:** Упрощение кода, лучшая обработка больших контекстов

**Действие:**
```python
# В rag_service.py добавить метод с использованием chains
from langchain.chains import RetrievalQA

def generate_answer_with_chain(self, case_id: str, query: str):
    vector_store = self.document_processor.load_vector_store(case_id)
    
    qa_chain = RetrievalQA.from_chain_type(
        llm=self.llm,
        chain_type="refine",  # Для больших документов
        retriever=vector_store.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={"k": 5, "score_threshold": 0.7}
        ),
        return_source_documents=True,
        verbose=True
    )
    
    result = qa_chain.invoke({"query": query})
    return result["result"], self.format_sources(result["source_documents"])
```

---

### Приоритет 3: Memory для чата
**Зачем:** Улучшение контекста в длинных диалогах

**Действие:**
```python
from langchain.memory import ConversationSummaryBufferMemory

# В RAGService добавить память
self.memory = ConversationSummaryBufferMemory(
    llm=self.llm,
    max_token_limit=2000,
    return_messages=True,
    memory_key="chat_history"
)

# Использовать в цепи
conversation_chain = ConversationalRetrievalChain.from_llm(
    llm=self.llm,
    retriever=vector_store.as_retriever(),
    memory=self.memory,
    return_source_documents=True
)
```

---

### Приоритет 4: Query Transformers
**Зачем:** Улучшение качества поиска

**Действие:**
```python
from langchain.retrievers.multi_query import MultiQueryRetriever

# В document_processor.py
def get_enhanced_retriever(self, case_id: str):
    base_retriever = self.vector_stores[case_id].as_retriever()
    
    # Генерирует несколько вариантов запроса
    multi_retriever = MultiQueryRetriever.from_llm(
        retriever=base_retriever,
        llm=self.llm
    )
    
    return multi_retriever
```

---

## 📈 Потенциальные улучшения производительности

### 1. **Кэширование embeddings**
```python
from langchain.cache import InMemoryCache
from langchain.globals import set_llm_cache

set_llm_cache(InMemoryCache())  # Кэш для одинаковых запросов
```

### 2. **Параллельная обработка**
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Автоматическая параллельная обработка
documents = loader.load_and_split(text_splitter)
```

### 3. **Streaming ответов**
```python
# Для больших ответов - стриминг
for chunk in chain.stream({"query": query}):
    yield chunk
```

---

## 🔧 Полезные инструменты LangChain

### 1. **LangSmith (мониторинг)**
- Отслеживание всех вызовов LLM
- Анализ производительности
- Отладка цепей

### 2. **LangServe (деплой)**
- Автоматическое создание API из цепей
- Документация
- Версионирование

### 3. **LangGraph (сложные потоки)**
- Визуализация цепей
- Условная логика
- Циклы и состояния

---

## 📝 Итоговые рекомендации

### ✅ Оставить как есть:
- Text Splitters (работает хорошо)
- Embeddings (интеграция с OpenRouter)
- Vector Stores (ChromaDB подходит)

### 🔄 Улучшить:
- Document Loaders (заменить на LangChain)
- Использовать Retrieval Chains для сложных случаев
- Добавить Memory для чата

### 🆕 Добавить:
- Query Transformers (MultiQueryRetriever)
- Reranking для критичных запросов
- Callbacks для мониторинга

### ⚠️ Не использовать пока:
- Agents (избыточно для текущих задач)
- LangGraph (слишком сложно)
- LangServe (есть FastAPI)

---

## 📚 Полезные ресурсы

- [LangChain Documentation](https://python.langchain.com/)
- [RAG Tutorial](https://python.langchain.com/docs/tutorials/rag)
- [LangChain Cookbook](https://github.com/langchain-ai/langchain-cookbook)
- [Best Practices](https://python.langchain.com/docs/guides/production)

---

**Дата создания:** 2024
**Версия LangChain:** 0.1.0+
**Статус:** Активное использование с потенциалом для улучшений
