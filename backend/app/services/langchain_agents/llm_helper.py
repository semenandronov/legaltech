"""Helper functions for direct LLM calls without agents (YandexGPT doesn't support tools)"""
from typing import List, Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from app.services.yandex_llm import ChatYandexGPT
from app.services.rag_service import RAGService
from app.config import config
from sqlalchemy.orm import Session
import logging
import json

logger = logging.getLogger(__name__)


def direct_llm_call_with_rag(
    case_id: str,
    system_prompt: str,
    user_query: str,
    rag_service: RAGService,
    db: Optional[Session] = None,
    k: int = 20,
    temperature: float = 0.1,
    model: Optional[str] = None
) -> str:
    """
    Прямой вызов LLM с RAG контекстом (без агентов и инструментов)
    
    Args:
        case_id: Case ID
        system_prompt: System prompt for LLM
        user_query: User query
        rag_service: RAG service instance
        db: Optional database session
        k: Number of documents to retrieve
        temperature: Temperature for generation
        model: Model name (optional)
    
    Returns:
        LLM response text
    """
    # Инициализируем LLM
    llm = ChatYandexGPT(
        model=model or config.YANDEX_GPT_MODEL or "yandexgpt-lite",
        temperature=temperature,
    )
    
    # Получаем релевантные документы через RAG
    relevant_docs = rag_service.retrieve_context(case_id, user_query, k=k, db=db)
    
    if not relevant_docs:
        logger.warning(f"No documents found for query in case {case_id}")
        # Все равно вызываем LLM, но без контекста
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{user_query}\n\nПримечание: Релевантные документы не найдены.")
        ]
    else:
        # Формируем промпт с контекстом
        sources_text = rag_service.format_sources_for_prompt(relevant_docs)
        full_user_prompt = f"""{user_query}

Контекст из документов:
{sources_text}

Верни результат в формате JSON, если это требуется задачей."""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=full_user_prompt)
        ]
    
    # Прямой вызов LLM
    try:
        response = llm.invoke(messages)
        response_text = response.content if hasattr(response, 'content') else str(response)
        return response_text
    except Exception as e:
        logger.error(f"Error in direct LLM call: {e}", exc_info=True)
        raise


def extract_json_from_response(response_text: str) -> Optional[Any]:
    """
    Извлекает JSON из текстового ответа LLM
    
    Args:
        response_text: LLM response text
    
    Returns:
        Parsed JSON object or None if extraction failed
    """
    try:
        # Пробуем найти JSON в markdown блоке
        if "```json" in response_text:
            json_text = response_text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_text)
        elif "```" in response_text:
            # Пробуем любой code block
            parts = response_text.split("```")
            for i in range(1, len(parts), 2):
                try:
                    return json.loads(parts[i].strip())
                except:
                    continue
        
        # Пробуем найти JSON массив или объект
        if "[" in response_text and "]" in response_text:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                return json.loads(json_text)
        
        if "{" in response_text and "}" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                return json.loads(json_text)
        
        # Пробуем распарсить весь текст как JSON
        return json.loads(response_text.strip())
    except Exception as e:
        logger.debug(f"Could not extract JSON from response: {e}")
        return None

