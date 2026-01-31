"""
Sub-graph для ГАРАНТ retrieval.

Извлекает информацию из правовой базы ГАРАНТ:
- Законы и кодексы
- Судебные решения
- Комментарии к нормам

# АРХИТЕКТУРА
```
START
  ↓
classify_query (определение типа документа)
  ↓
search_garant (поиск в ГАРАНТ API)
  ↓
format_results (форматирование результатов)
  ↓
END
```

# ИСПОЛЬЗОВАНИЕ
```python
from langgraph.types import Send

def dispatch_garant(state):
    return Send("garant_retrieval", {
        "query": state["question"],
        "doc_type": "all"
    })
```
"""
from typing import TypedDict, Optional, List, Dict, Any, Annotated, Literal
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import BaseMessage, AIMessage
import logging
import operator

logger = logging.getLogger(__name__)


# ============== State Definition ==============

class GarantRetrievalState(TypedDict):
    """
    Состояние sub-graph для ГАРАНТ retrieval.
    """
    # Входные данные
    query: str
    
    # Настройки
    doc_type: Literal["all", "laws", "court_decisions", "comments"]
    max_results: int
    
    # Промежуточные результаты
    classified_doc_type: Optional[str]
    raw_results: Optional[List[Dict[str, Any]]]
    
    # Результаты
    context: str
    citations: List[Dict[str, Any]]
    
    # Метаданные
    errors: Optional[List[str]]


def create_initial_garant_state(
    query: str,
    doc_type: str = "all",
    max_results: int = 5
) -> GarantRetrievalState:
    """Создать начальное состояние для ГАРАНТ retrieval."""
    return GarantRetrievalState(
        query=query,
        doc_type=doc_type,
        max_results=max_results,
        classified_doc_type=None,
        raw_results=None,
        context="",
        citations=[],
        errors=None
    )


# ============== Node Functions ==============

def classify_query_node(state: GarantRetrievalState) -> GarantRetrievalState:
    """
    Узел классификации запроса.
    
    Определяет оптимальный тип документа для поиска.
    """
    query = state["query"]
    doc_type = state.get("doc_type", "all")
    
    logger.info(f"[GarantRetrieval] Classifying query: {query[:100]}...")
    
    new_state = dict(state)
    
    # Если тип уже указан явно, используем его
    if doc_type != "all":
        new_state["classified_doc_type"] = doc_type
        return new_state
    
    # Автоматическая классификация на основе ключевых слов
    query_lower = query.lower()
    
    # Признаки законов/кодексов
    law_keywords = [
        "статья", "ст.", "гк рф", "гпк", "апк", "ук рф", "тк рф", "нк рф",
        "закон", "кодекс", "постановление", "указ", "приказ", "фз",
        "по закону", "согласно", "нормативный", "регулирует"
    ]
    
    # Признаки судебных решений
    court_keywords = [
        "судебная практика", "решение суда", "постановление пленума",
        "определение", "апелляция", "кассация", "обзор практики",
        "вс рф", "верховный суд", "арбитражный суд"
    ]
    
    # Признаки комментариев
    comment_keywords = [
        "комментарий", "разъяснение", "толкование", "позиция",
        "мнение", "анализ нормы"
    ]
    
    # Подсчёт совпадений
    law_score = sum(1 for kw in law_keywords if kw in query_lower)
    court_score = sum(1 for kw in court_keywords if kw in query_lower)
    comment_score = sum(1 for kw in comment_keywords if kw in query_lower)
    
    if court_score > law_score and court_score > comment_score:
        new_state["classified_doc_type"] = "court_decisions"
    elif comment_score > law_score:
        new_state["classified_doc_type"] = "comments"
    elif law_score > 0:
        new_state["classified_doc_type"] = "laws"
    else:
        new_state["classified_doc_type"] = "all"
    
    logger.info(f"[GarantRetrieval] Classified as: {new_state['classified_doc_type']}")
    
    return new_state


def search_garant_node(state: GarantRetrievalState) -> GarantRetrievalState:
    """
    Узел поиска в ГАРАНТ API.
    """
    query = state["query"]
    doc_type = state.get("classified_doc_type", "all")
    max_results = state.get("max_results", 5)
    
    logger.info(f"[GarantRetrieval] Searching ГАРАНТ: {query[:100]}...")
    
    new_state = dict(state)
    
    try:
        from app.services.langchain_agents.utils import get_garant_source
        import asyncio
        
        garant_source = get_garant_source()
        
        if not garant_source or not garant_source.api_key:
            logger.warning("[GarantRetrieval] ГАРАНТ API not available")
            new_state["raw_results"] = []
            new_state["errors"] = ["ГАРАНТ API недоступен"]
            return new_state
        
        # Асинхронный вызов
        async def do_search():
            return await garant_source.search(
                query=query,
                max_results=max_results,
                doc_type=doc_type if doc_type != "all" else None
            )
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, do_search())
                    results = future.result(timeout=30)
            else:
                results = loop.run_until_complete(do_search())
        except RuntimeError:
            results = asyncio.run(do_search())
        
        # Преобразуем результаты
        raw_results = []
        for result in results:
            raw_results.append({
                "title": getattr(result, 'title', None) or result.get('title', 'Без названия'),
                "url": getattr(result, 'url', None) or result.get('url', ''),
                "content": getattr(result, 'content', None) or result.get('content', ''),
                "doc_type": getattr(result, 'doc_type', None) or result.get('doc_type', 'document'),
                "date": getattr(result, 'date', None) or result.get('date')
            })
        
        new_state["raw_results"] = raw_results
        
        logger.info(f"[GarantRetrieval] Found {len(raw_results)} results")
        
    except Exception as e:
        logger.error(f"[GarantRetrieval] Search error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"ГАРАНТ search error: {str(e)}"]
        new_state["raw_results"] = []
    
    return new_state


def format_results_node(state: GarantRetrievalState) -> GarantRetrievalState:
    """
    Узел форматирования результатов.
    """
    raw_results = state.get("raw_results", [])
    
    logger.info(f"[GarantRetrieval] Formatting {len(raw_results)} results")
    
    new_state = dict(state)
    
    if not raw_results:
        new_state["context"] = ""
        new_state["citations"] = []
        return new_state
    
    # Форматируем контекст
    context_parts = []
    citations = []
    
    for i, result in enumerate(raw_results, 1):
        title = result.get("title", "Без названия")
        url = result.get("url", "")
        content = result.get("content", "")
        doc_type = result.get("doc_type", "document")
        date = result.get("date")
        
        # Ограничиваем длину контента
        if len(content) > 500:
            content = content[:500] + "..."
        
        # Формируем запись
        header = f"[{i}] {title}"
        if date:
            header += f" ({date})"
        
        context_parts.append(f"{header}\nURL: {url}\n{content}")
        
        # Добавляем citation
        citations.append({
            "index": i,
            "source": title,
            "url": url,
            "doc_type": doc_type,
            "date": date,
            "content": content[:200]
        })
    
    new_state["context"] = "\n\n".join(context_parts)
    new_state["citations"] = citations
    
    logger.info(f"[GarantRetrieval] Formatted context: {len(new_state['context'])} chars")
    
    return new_state


# ============== Graph Builder ==============

def create_garant_retrieval_subgraph():
    """
    Создать sub-graph для ГАРАНТ retrieval.
    
    Returns:
        Compiled sub-graph
    """
    logger.info("[GarantRetrieval] Creating ГАРАНТ retrieval subgraph")
    
    graph = StateGraph(GarantRetrievalState)
    
    # Добавляем узлы
    graph.add_node("classify_query", classify_query_node)
    graph.add_node("search_garant", search_garant_node)
    graph.add_node("format_results", format_results_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "classify_query")
    graph.add_edge("classify_query", "search_garant")
    graph.add_edge("search_garant", "format_results")
    graph.add_edge("format_results", END)
    
    # Компилируем
    compiled = graph.compile()
    
    logger.info("[GarantRetrieval] Subgraph created successfully")
    return compiled

