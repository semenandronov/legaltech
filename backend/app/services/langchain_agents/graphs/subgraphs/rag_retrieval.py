"""
Sub-graph для RAG retrieval.

Извлекает контекст из документов дела с использованием
различных стратегий поиска.

# АРХИТЕКТУРА
```
START
  ↓
prepare_query (подготовка запроса, multi-query expansion)
  ↓
retrieve_documents (поиск документов)
  ↓
format_context (форматирование результатов)
  ↓
END
```

# ИСПОЛЬЗОВАНИЕ
```python
from langgraph.types import Send

def dispatch_retrievals(state):
    return [
        Send("rag_retrieval", {
            "query": state["question"],
            "case_id": state["case_id"]
        })
    ]
```
"""
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import BaseMessage, AIMessage
from sqlalchemy.orm import Session
import logging
import operator

logger = logging.getLogger(__name__)


# ============== State Definition ==============

class RAGRetrievalState(TypedDict):
    """
    Состояние sub-graph для RAG retrieval.
    """
    # Входные данные
    query: str
    case_id: str
    user_id: Optional[str]
    
    # Настройки
    retrieval_strategy: str  # "multi_query", "similarity", "mmr"
    k: int  # Количество документов
    max_context_chars: int
    
    # Промежуточные результаты
    expanded_queries: Optional[List[str]]
    retrieved_documents: Optional[List[Dict[str, Any]]]
    
    # Результаты
    context: str
    citations: List[Dict[str, Any]]
    
    # Метаданные
    errors: Optional[List[str]]


def create_initial_rag_state(
    query: str,
    case_id: str,
    user_id: str = None,
    retrieval_strategy: str = "multi_query",
    k: int = 5,
    max_context_chars: int = 4000
) -> RAGRetrievalState:
    """Создать начальное состояние для RAG retrieval."""
    return RAGRetrievalState(
        query=query,
        case_id=case_id,
        user_id=user_id,
        retrieval_strategy=retrieval_strategy,
        k=k,
        max_context_chars=max_context_chars,
        expanded_queries=None,
        retrieved_documents=None,
        context="",
        citations=[],
        errors=None
    )


# ============== Node Functions ==============

def prepare_query_node(state: RAGRetrievalState) -> RAGRetrievalState:
    """
    Узел подготовки запроса.
    
    Выполняет multi-query expansion если стратегия = "multi_query".
    """
    query = state["query"]
    strategy = state.get("retrieval_strategy", "multi_query")
    
    logger.info(f"[RAGRetrieval] Preparing query with strategy: {strategy}")
    
    new_state = dict(state)
    
    if strategy == "multi_query":
        try:
            from app.services.llm_factory import create_llm
            
            llm = create_llm()
            
            expansion_prompt = f"""Сгенерируй 3 альтернативных формулировки для поискового запроса.
            
Оригинальный запрос: {query}

Требования:
1. Каждая формулировка должна искать ту же информацию, но другими словами
2. Используй синонимы и перефразирование
3. Сохраняй юридический контекст

Ответь в формате JSON:
["формулировка 1", "формулировка 2", "формулировка 3"]"""

            response = llm.invoke(expansion_prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            import json
            import re
            json_match = re.search(r'\[[\s\S]*?\]', response_text)
            if json_match:
                expanded = json.loads(json_match.group())
                new_state["expanded_queries"] = [query] + expanded
            else:
                new_state["expanded_queries"] = [query]
                
            logger.info(f"[RAGRetrieval] Expanded to {len(new_state['expanded_queries'])} queries")
            
        except Exception as e:
            logger.warning(f"[RAGRetrieval] Query expansion failed: {e}")
            new_state["expanded_queries"] = [query]
    else:
        new_state["expanded_queries"] = [query]
    
    return new_state


def retrieve_documents_node(
    state: RAGRetrievalState,
    rag_service=None,
    db: Session = None
) -> RAGRetrievalState:
    """
    Узел поиска документов.
    """
    case_id = state["case_id"]
    queries = state.get("expanded_queries", [state["query"]])
    k = state.get("k", 5)
    strategy = state.get("retrieval_strategy", "multi_query")
    
    logger.info(f"[RAGRetrieval] Retrieving documents for case {case_id}")
    
    new_state = dict(state)
    
    try:
        if not rag_service:
            from app.services.rag_service import RAGService
            rag_service = RAGService()
        
        all_docs = []
        seen_ids = set()
        
        for query in queries:
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=k,
                retrieval_strategy="similarity" if strategy == "multi_query" else strategy,
                db=db
            )
            
            for doc in docs:
                doc_id = doc.metadata.get("id", doc.page_content[:50])
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    all_docs.append({
                        "content": doc.page_content,
                        "metadata": doc.metadata
                    })
        
        # Ограничиваем количество
        new_state["retrieved_documents"] = all_docs[:k * 2]  # Берём больше для multi-query
        
        logger.info(f"[RAGRetrieval] Retrieved {len(new_state['retrieved_documents'])} unique documents")
        
    except Exception as e:
        logger.error(f"[RAGRetrieval] Retrieval error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Retrieval error: {str(e)}"]
        new_state["retrieved_documents"] = []
    
    return new_state


def format_context_node(state: RAGRetrievalState) -> RAGRetrievalState:
    """
    Узел форматирования контекста.
    """
    documents = state.get("retrieved_documents", [])
    max_chars = state.get("max_context_chars", 4000)
    
    logger.info(f"[RAGRetrieval] Formatting {len(documents)} documents")
    
    new_state = dict(state)
    
    if not documents:
        new_state["context"] = ""
        new_state["citations"] = []
        return new_state
    
    # Форматируем контекст
    context_parts = []
    citations = []
    total_chars = 0
    
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        metadata = doc.get("metadata", {})
        
        # Проверяем лимит символов
        if total_chars + len(content) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 100:
                content = content[:remaining] + "..."
            else:
                break
        
        source = metadata.get("source", "Неизвестный источник")
        page = metadata.get("page")
        
        # Добавляем в контекст
        source_info = f"[{i}] {source}"
        if page:
            source_info += f", стр. {page}"
        
        context_parts.append(f"{source_info}:\n{content}")
        total_chars += len(content)
        
        # Добавляем citation
        citations.append({
            "index": i,
            "source": source,
            "page": page,
            "content": content[:200],
            "file_id": metadata.get("file_id")
        })
    
    new_state["context"] = "\n\n".join(context_parts)
    new_state["citations"] = citations
    
    logger.info(f"[RAGRetrieval] Formatted context: {len(new_state['context'])} chars, {len(citations)} citations")
    
    return new_state


# ============== Graph Builder ==============

def create_rag_retrieval_subgraph(
    rag_service=None,
    db: Session = None
):
    """
    Создать sub-graph для RAG retrieval.
    
    Args:
        rag_service: RAG service instance
        db: Database session
    
    Returns:
        Compiled sub-graph
    """
    logger.info("[RAGRetrieval] Creating RAG retrieval subgraph")
    
    graph = StateGraph(RAGRetrievalState)
    
    # Wrapper функции
    def retrieve_wrapper(state):
        return retrieve_documents_node(state, rag_service, db)
    
    # Добавляем узлы
    graph.add_node("prepare_query", prepare_query_node)
    graph.add_node("retrieve_documents", retrieve_wrapper)
    graph.add_node("format_context", format_context_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "prepare_query")
    graph.add_edge("prepare_query", "retrieve_documents")
    graph.add_edge("retrieve_documents", "format_context")
    graph.add_edge("format_context", END)
    
    # Компилируем
    compiled = graph.compile()
    
    logger.info("[RAGRetrieval] Subgraph created successfully")
    return compiled

