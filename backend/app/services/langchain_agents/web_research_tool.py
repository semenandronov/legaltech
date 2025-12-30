"""Web Research Tool for agents"""
from typing import Dict, Any
from langchain_core.tools import tool
from app.services.external_sources.web_research_service import get_web_research_service
import logging
import asyncio

logger = logging.getLogger(__name__)


@tool
def web_research_tool(
    query: str,
    max_results: int = 10,
    validate_sources: bool = True
) -> str:
    """
    Выполнить структурированное веб-исследование по запросу.
    
    Используйте для поиска информации в интернете, прецедентов, верификации фактов.
    
    Args:
        query: Поисковый запрос
        max_results: Максимальное количество результатов (по умолчанию 10)
        validate_sources: Валидировать источники (по умолчанию True)
    
    Returns:
        Форматированная строка с результатами исследования
    """
    try:
        service = get_web_research_service()
        result = asyncio.run(service.research(
            query=query,
            max_results=max_results,
            validate_sources=validate_sources
        ))
        
        # Форматируем результат для агента
        formatted = f"Исследование по запросу: {query}\n\n"
        formatted += f"Резюме: {result.summary}\n\n"
        formatted += f"Уверенность: {result.confidence:.2f}\n\n"
        
        if result.key_findings:
            formatted += "Ключевые находки:\n"
            for finding in result.key_findings[:5]:
                formatted += f"- {finding}\n"
            formatted += "\n"
        
        if result.sources:
            formatted += f"Источники ({len(result.sources)}):\n"
            for i, source in enumerate(result.sources[:5], 1):
                formatted += f"{i}. {source.get('title', 'Без названия')}\n"
                if source.get('url'):
                    formatted += f"   URL: {source['url']}\n"
                if source.get('content'):
                    formatted += f"   Содержание: {source['content'][:200]}...\n"
                formatted += "\n"
        
        logger.info(f"Web research completed for query: {query[:50]}...")
        return formatted
        
    except Exception as e:
        logger.error(f"Error in web research: {e}", exc_info=True)
        return f"Ошибка при выполнении веб-исследования: {str(e)}"

