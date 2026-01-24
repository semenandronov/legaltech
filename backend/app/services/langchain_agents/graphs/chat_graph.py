"""
ChatGraph - LangGraph граф для страницы чата.

# РОЛЬ
Основной граф для обработки запросов пользователя на странице AssistantChatPage.
Маршрутизирует запросы по режимам и координирует работу узлов.

# РЕЖИМЫ РАБОТЫ
- normal: RAG поиск в документах + опционально ГАРАНТ + ответ
- deep_think: RAG + ГАРАНТ + пошаговое мышление + развёрнутый ответ
- garant: RAG + приоритет ГАРАНТ + ответ с цитатами из законодательства
- draft: Создание юридического документа без RAG

# АРХИТЕКТУРА ГРАФА
```
START
  ↓
mode_router (определяет режим)
  ↓
  ├── draft → draft_node → END
  │
  └── normal/deep_think/garant
        ↓
      rag_retrieval (поиск в документах дела)
        ↓
      garant_retrieval (поиск в ГАРАНТ, если включён)
        ↓
        ├── deep_think → thinking_node → generate_response → END
        │
        └── normal/garant → generate_response → END
```

# КОГДА ИСПОЛЬЗОВАТЬ
- Ответы на вопросы пользователя в чате
- Поиск информации в документах дела
- Поиск в законодательстве (ГАРАНТ)
- Глубокий анализ с пошаговым мышлением
- Создание юридических документов
"""
from typing import TypedDict, Literal, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from app.services.llm_factory import create_llm, create_legal_llm
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.utils.checkpointer_setup import get_checkpointer_instance
from sqlalchemy.orm import Session
import logging
import operator

logger = logging.getLogger(__name__)


# ============== State Definition ==============

class ChatGraphState(TypedDict):
    """Состояние графа чата."""
    # Входные данные
    case_id: str
    user_id: str
    question: str
    mode: Literal["normal", "deep_think", "garant", "draft"]
    
    # Опции
    enable_garant: bool
    enable_citations: bool
    
    # Контекст документа (для режима редактора)
    document_context: Optional[str]
    document_id: Optional[str]
    selected_text: Optional[str]
    
    # Промежуточные результаты
    rag_context: Optional[str]
    garant_context: Optional[str]
    thinking_steps: Optional[List[Dict[str, Any]]]
    
    # Результат
    response: Optional[str]
    citations: Optional[List[Dict[str, Any]]]
    document_created: Optional[Dict[str, Any]]
    
    # Метаданные
    messages: Annotated[List[BaseMessage], operator.add]
    errors: Optional[List[str]]


def create_initial_chat_state(
    case_id: str,
    user_id: str,
    question: str,
    mode: str = "normal",
    enable_garant: bool = True,
    enable_citations: bool = True,
    document_context: str = None,
    document_id: str = None,
    selected_text: str = None
) -> ChatGraphState:
    """Создать начальное состояние для графа чата."""
    return ChatGraphState(
        case_id=case_id,
        user_id=user_id,
        question=question,
        mode=mode,
        enable_garant=enable_garant,
        enable_citations=enable_citations,
        document_context=document_context,
        document_id=document_id,
        selected_text=selected_text,
        rag_context=None,
        garant_context=None,
        thinking_steps=None,
        response=None,
        citations=None,
        document_created=None,
        messages=[HumanMessage(content=question)],
        errors=None
    )


# ============== Node Functions ==============

def mode_router_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел маршрутизации по режиму.
    
    Определяет, какой flow использовать на основе mode.
    """
    mode = state.get("mode", "normal")
    question = state.get("question", "")
    
    logger.info(f"[ModeRouter] Routing question to mode: {mode}")
    
    # Валидация режима
    valid_modes = ["normal", "deep_think", "garant", "draft"]
    if mode not in valid_modes:
        logger.warning(f"[ModeRouter] Invalid mode '{mode}', falling back to 'normal'")
        new_state = dict(state)
        new_state["mode"] = "normal"
        return new_state
    
    return state


def rag_retrieval_node(
    state: ChatGraphState,
    rag_service: RAGService = None,
    db: Session = None
) -> ChatGraphState:
    """
    Узел получения контекста из RAG.
    
    Используется во всех режимах кроме draft.
    """
    case_id = state.get("case_id")
    question = state.get("question", "")
    
    logger.info(f"[RAGRetrieval] Retrieving context for case {case_id}")
    
    new_state = dict(state)
    
    try:
        if rag_service:
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=5,
                retrieval_strategy="multi_query",
                db=db
            )
            
            if docs:
                context = rag_service.format_sources_for_prompt(docs, max_context_chars=4000)
                new_state["rag_context"] = context
                
                # Сохраняем citations
                citations = []
                for i, doc in enumerate(docs, 1):
                    citations.append({
                        "index": i,
                        "source": doc.metadata.get("source", "Неизвестный источник"),
                        "page": doc.metadata.get("page"),
                        "content": doc.page_content[:200]
                    })
                new_state["citations"] = citations
                
                logger.info(f"[RAGRetrieval] Retrieved {len(docs)} documents")
            else:
                new_state["rag_context"] = ""
                logger.info("[RAGRetrieval] No documents found")
        else:
            logger.warning("[RAGRetrieval] RAG service not available")
            new_state["rag_context"] = ""
            
    except Exception as e:
        logger.error(f"[RAGRetrieval] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"RAG error: {str(e)}"]
        new_state["rag_context"] = ""
    
    return new_state


def garant_retrieval_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел получения контекста из ГАРАНТ.
    
    Используется в режимах normal и garant.
    """
    question = state.get("question", "")
    enable_garant = state.get("enable_garant", True)
    
    new_state = dict(state)
    
    if not enable_garant:
        logger.info("[GarantRetrieval] ГАРАНТ disabled")
        new_state["garant_context"] = ""
        return new_state
    
    logger.info(f"[GarantRetrieval] Searching ГАРАНТ for: {question[:100]}...")
    
    try:
        from app.services.langchain_agents.utils import get_garant_source
        import asyncio
        
        garant_source = get_garant_source()
        if garant_source and garant_source.api_key:
            # Асинхронный вызов
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            garant_source.search(query=question, max_results=5)
                        )
                        results = future.result(timeout=30)
                else:
                    results = loop.run_until_complete(
                        garant_source.search(query=question, max_results=5)
                    )
            except RuntimeError:
                results = asyncio.run(
                    garant_source.search(query=question, max_results=5)
                )
            
            if results:
                # Форматируем результаты
                formatted_parts = []
                for i, result in enumerate(results[:5], 1):
                    title = result.title or "Без названия"
                    url = result.url or ""
                    content = result.content[:500] if result.content else ""
                    formatted_parts.append(f"[ГАРАНТ {i}] {title}\nURL: {url}\n{content}")
                
                new_state["garant_context"] = "\n\n".join(formatted_parts)
                logger.info(f"[GarantRetrieval] Found {len(results)} results")
            else:
                new_state["garant_context"] = ""
                logger.info("[GarantRetrieval] No results found")
        else:
            new_state["garant_context"] = ""
            logger.warning("[GarantRetrieval] ГАРАНТ API not available")
            
    except Exception as e:
        logger.error(f"[GarantRetrieval] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"ГАРАНТ error: {str(e)}"]
        new_state["garant_context"] = ""
    
    return new_state


def thinking_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел пошагового мышления.
    
    Используется в режиме deep_think.
    """
    question = state.get("question", "")
    rag_context = state.get("rag_context", "")
    garant_context = state.get("garant_context", "")
    
    logger.info("[Thinking] Starting deep thinking process")
    
    new_state = dict(state)
    
    try:
        from app.services.thinking_service import get_thinking_service
        import asyncio
        
        context = f"{rag_context}\n\n{garant_context}" if garant_context else rag_context
        
        thinking_service = get_thinking_service(deep_think=True)
        
        steps = []
        
        # Собираем шаги мышления
        async def collect_steps():
            async for step in thinking_service.think(
                question=question,
                context=context,
                stream_steps=True
            ):
                steps.append({
                    "phase": step.phase.value,
                    "step_number": step.step_number,
                    "total_steps": step.total_steps,
                    "content": step.content
                })
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, collect_steps())
                    future.result(timeout=60)
            else:
                loop.run_until_complete(collect_steps())
        except RuntimeError:
            asyncio.run(collect_steps())
        
        new_state["thinking_steps"] = steps
        logger.info(f"[Thinking] Completed {len(steps)} thinking steps")
        
    except Exception as e:
        logger.error(f"[Thinking] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Thinking error: {str(e)}"]
        new_state["thinking_steps"] = []
    
    return new_state


def generate_response_node(
    state: ChatGraphState,
    db: Session = None
) -> ChatGraphState:
    """
    Узел генерации ответа.
    
    Генерирует финальный ответ на основе контекста и режима.
    """
    question = state.get("question", "")
    mode = state.get("mode", "normal")
    rag_context = state.get("rag_context", "")
    garant_context = state.get("garant_context", "")
    thinking_steps = state.get("thinking_steps", [])
    document_context = state.get("document_context", "")
    selected_text = state.get("selected_text", "")
    
    logger.info(f"[GenerateResponse] Generating response in mode: {mode}")
    
    new_state = dict(state)
    
    try:
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Формируем промпт на основе режима с best practices
        system_prompts = {
            "normal": """# РОЛЬ
Ты — профессиональный юридический AI-ассистент.

# ЦЕЛЬ
Дать точный, краткий ответ на вопрос пользователя, опираясь на документы дела и законодательство.

# ИНСТРУКЦИИ
1. Используй информацию из документов дела (приоритет)
2. Дополняй информацией из ГАРАНТ (если доступна)
3. Цитируй источники в формате [1], [2], [3]
4. Отвечай кратко и по существу

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ выдумывай информацию
- НЕ давай заключений без источников
- ВСЕГДА указывай источники
- Используй Markdown для форматирования""",
            
            "deep_think": """# РОЛЬ
Ты — юридический аналитик в режиме глубокого анализа.

# ЦЕЛЬ
Провести комплексный анализ вопроса с рассмотрением всех аспектов.

# СТРУКТУРА ОТВЕТА
## 📜 Правовая база
[Применимые нормы, статьи кодексов]

## 🏛️ Судебная практика
[Релевантные решения судов]

## ⚖️ Анализ позиций
[Аргументы за и против]

## ⚠️ Риски
[Возможные проблемы]

## ✅ Рекомендации
[Конкретные действия]

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- Опирайся ТОЛЬКО на предоставленный контекст
- Указывай источники для каждого утверждения
- Используй Markdown для форматирования""",
            
            "garant": """# РОЛЬ
Ты — юридический консультант с доступом к базе ГАРАНТ.

# ЦЕЛЬ
Дать ответ с опорой на актуальное законодательство и судебную практику.

# ИНСТРУКЦИИ
1. Приоритет информации из ГАРАНТ
2. Цитируй конкретные статьи и пункты
3. Указывай ссылки на источники (URL)
4. Дополняй информацией из документов дела

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ давай устаревшую информацию
- ВСЕГДА указывай источник (статья, закон, URL)
- Используй Markdown для форматирования""",
            
            "draft": """# РОЛЬ
Ты — юрист, помогающий создавать документы.

# ЦЕЛЬ
Помочь пользователю создать профессиональный юридический документ.

# ИНСТРУКЦИИ
1. Уточни детали, если информации недостаточно
2. Используй стандартную структуру документа
3. Отмечай места для заполнения как [ЗАПОЛНИТЬ]

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ выдумывай реквизиты и даты
- Предупреждай о необходимости проверки юристом"""
        }
        
        system_prompt = system_prompts.get(mode, system_prompts["normal"])
        
        # Формируем контекст
        context_parts = []
        
        if rag_context:
            context_parts.append(f"=== ДОКУМЕНТЫ ДЕЛА ===\n{rag_context}")
        
        if garant_context:
            context_parts.append(f"=== РЕЗУЛЬТАТЫ ГАРАНТ ===\n{garant_context}")
        
        if thinking_steps:
            thinking_text = "\n".join([f"Шаг {s['step_number']}: {s['content']}" for s in thinking_steps])
            context_parts.append(f"=== ПРОЦЕСС АНАЛИЗА ===\n{thinking_text}")
        
        if document_context:
            context_parts.append(f"=== ДОКУМЕНТ В РЕДАКТОРЕ ===\n{document_context[:5000]}")
        
        if selected_text:
            context_parts.append(f"=== ВЫДЕЛЕННЫЙ ТЕКСТ ===\n{selected_text}")
        
        full_context = "\n\n".join(context_parts) if context_parts else "Контекст не найден."
        
        # Генерируем ответ
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"КОНТЕКСТ:\n{full_context}\n\nВОПРОС:\n{question}")
        ]
        
        response = llm.invoke(messages)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        new_state["response"] = response_text
        new_state["messages"] = [AIMessage(content=response_text)]
        
        logger.info(f"[GenerateResponse] Generated response: {len(response_text)} chars")
        
    except Exception as e:
        logger.error(f"[GenerateResponse] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Generation error: {str(e)}"]
        new_state["response"] = f"Ошибка генерации ответа: {str(e)}"
    
    return new_state


def draft_node(
    state: ChatGraphState,
    db: Session = None
) -> ChatGraphState:
    """
    Узел создания документа (draft mode).
    
    Генерирует документ напрямую через LLM без зависимости от template_graph.
    """
    question = state.get("question", "")
    case_id = state.get("case_id")
    user_id = state.get("user_id")
    
    logger.info(f"[Draft] Creating document for case {case_id}")
    
    new_state = dict(state)
    
    try:
        from app.services.document_editor_service import DocumentEditorService
        from app.services.llm_factory import create_legal_llm
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Генерируем название документа
        title_prompt = f"Извлеки краткое название документа (5-7 слов) из описания: {question}. Ответь только названием."
        title_response = llm.invoke([HumanMessage(content=title_prompt)])
        title = title_response.content.strip().replace('"', '').replace("'", "")[:255] if hasattr(title_response, 'content') else "Новый документ"
        
        if not title or len(title) < 3:
            title = "Новый документ"
        
        # Генерируем содержимое документа
        content_prompt = f"""Создай юридический документ на основе описания.

ОПИСАНИЕ:
{question}

Создай профессиональный юридический документ в формате HTML.
Используй стандартную структуру для данного типа документа.
Включи все необходимые разделы и поля для заполнения (отметь их как [ЗАПОЛНИТЬ]).

Ответь только HTML-кодом документа без дополнительных комментариев.
"""
        
        content_response = llm.invoke([HumanMessage(content=content_prompt)])
        content = content_response.content if hasattr(content_response, 'content') else ""
        
        # Сохраняем документ
        doc_service = DocumentEditorService(db)
        document = doc_service.create_document(
            case_id=case_id,
            user_id=user_id,
            title=title,
            content=content
        )
        
        new_state["document_created"] = {
            "id": str(document.id),
            "title": document.title,
            "preview": content[:500] if content else ""
        }
        new_state["response"] = f'✅ Документ "{document.title}" успешно создан!'
        new_state["messages"] = [AIMessage(content=new_state["response"])]
        
        logger.info(f"[Draft] Document created: {document.id}")
            
    except Exception as e:
        logger.error(f"[Draft] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Draft error: {str(e)}"]
        new_state["response"] = f"❌ Ошибка создания документа: {str(e)}"
    
    return new_state


# ============== Routing Functions ==============

def route_by_mode(state: ChatGraphState) -> str:
    """Определить следующий узел на основе режима."""
    mode = state.get("mode", "normal")
    
    if mode == "draft":
        return "draft"
    elif mode == "deep_think":
        return "thinking"
    elif mode == "garant":
        return "garant_retrieval"
    else:
        return "rag_retrieval"


def route_after_rag(state: ChatGraphState) -> str:
    """Определить следующий узел после RAG retrieval."""
    mode = state.get("mode", "normal")
    enable_garant = state.get("enable_garant", True)
    
    if mode == "garant" or (mode == "normal" and enable_garant):
        return "garant_retrieval"
    else:
        return "generate_response"


def route_after_garant(state: ChatGraphState) -> str:
    """Определить следующий узел после ГАРАНТ retrieval."""
    mode = state.get("mode", "normal")
    
    if mode == "deep_think":
        return "thinking"
    else:
        return "generate_response"


def route_after_thinking(state: ChatGraphState) -> str:
    """Определить следующий узел после thinking."""
    return "generate_response"


# ============== Graph Builder ==============

def create_chat_graph(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    use_checkpointing: bool = True
):
    """
    Создать LangGraph граф для страницы чата.
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
        use_checkpointing: Использовать checkpointing
    
    Returns:
        Compiled LangGraph
    """
    logger.info("[ChatGraph] Creating chat graph")
    
    # Создаём граф
    graph = StateGraph(ChatGraphState)
    
    # Создаём wrapper функции с замыканием для db и rag_service
    def rag_retrieval_wrapper(state):
        return rag_retrieval_node(state, rag_service, db)
    
    def generate_response_wrapper(state):
        return generate_response_node(state, db)
    
    def draft_wrapper(state):
        return draft_node(state, db)
    
    # Добавляем узлы
    graph.add_node("mode_router", mode_router_node)
    graph.add_node("rag_retrieval", rag_retrieval_wrapper)
    graph.add_node("garant_retrieval", garant_retrieval_node)
    graph.add_node("thinking", thinking_node)
    graph.add_node("generate_response", generate_response_wrapper)
    graph.add_node("draft", draft_wrapper)
    
    # Добавляем рёбра
    graph.add_edge(START, "mode_router")
    
    # Conditional edge после mode_router
    graph.add_conditional_edges(
        "mode_router",
        route_by_mode,
        {
            "draft": "draft",
            "thinking": "rag_retrieval",  # deep_think сначала получает контекст
            "garant_retrieval": "rag_retrieval",  # garant сначала получает RAG контекст
            "rag_retrieval": "rag_retrieval"
        }
    )
    
    # Conditional edge после rag_retrieval
    graph.add_conditional_edges(
        "rag_retrieval",
        route_after_rag,
        {
            "garant_retrieval": "garant_retrieval",
            "generate_response": "generate_response"
        }
    )
    
    # Conditional edge после garant_retrieval
    graph.add_conditional_edges(
        "garant_retrieval",
        route_after_garant,
        {
            "thinking": "thinking",
            "generate_response": "generate_response"
        }
    )
    
    # Edge после thinking
    graph.add_edge("thinking", "generate_response")
    
    # Edge после draft
    graph.add_edge("draft", END)
    
    # Edge после generate_response
    graph.add_edge("generate_response", END)
    
    # Компилируем граф
    if use_checkpointing:
        try:
            checkpointer = get_checkpointer_instance()
            compiled = graph.compile(checkpointer=checkpointer)
            logger.info("[ChatGraph] Compiled with PostgresSaver checkpointer")
        except Exception as e:
            logger.warning(f"[ChatGraph] Failed to get PostgresSaver, using MemorySaver: {e}")
            compiled = graph.compile(checkpointer=MemorySaver())
    else:
        compiled = graph.compile()
    
    logger.info("[ChatGraph] Graph created successfully")
    return compiled



