"""
Утилиты для langchain_agents.

Содержит общие функции, используемые агентами и графами.
"""
from typing import Dict, Any, Optional
import json
import re
import logging

logger = logging.getLogger(__name__)


def extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Извлечь JSON из ответа LLM.
    
    Args:
        response_text: Текст ответа LLM
    
    Returns:
        Распарсенный JSON или None
    """
    if not response_text:
        return None
    
    # Пробуем найти JSON в markdown блоке
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Пробуем найти JSON напрямую
    try:
        # Ищем первый { и последний }
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = response_text[start:end + 1]
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # Пробуем найти массив JSON
    try:
        start = response_text.find('[')
        end = response_text.rfind(']')
        if start != -1 and end != -1 and end > start:
            json_str = response_text[start:end + 1]
            return {"items": json.loads(json_str)}
    except json.JSONDecodeError:
        pass
    
    return None


def get_garant_source():
    """
    Получить источник ГАРАНТ.
    
    Returns:
        GarantSource instance или None
    """
    try:
        from app.services.external_sources.garant_source import GarantSource
        from app.config import config
        
        api_key = getattr(config, 'GARANT_API_KEY', None)
        if not api_key:
            logger.warning("[Utils] GARANT_API_KEY not configured")
            return None
        
        return GarantSource(api_key=api_key)
    except ImportError as e:
        logger.warning(f"[Utils] GarantSource not available: {e}")
        return None
    except Exception as e:
        logger.error(f"[Utils] Error creating GarantSource: {e}")
        return None


async def search_garant(query: str, max_results: int = 5) -> str:
    """
    Поиск в ГАРАНТ.
    
    Args:
        query: Поисковый запрос
        max_results: Максимальное количество результатов
    
    Returns:
        Результаты поиска в текстовом формате
    """
    garant_source = get_garant_source()
    if not garant_source:
        return "ГАРАНТ API недоступен."
    
    try:
        results = await garant_source.search(query=query, max_results=max_results)
        
        if not results:
            return f"По запросу '{query}' ничего не найдено в ГАРАНТ."
        
        formatted = []
        for i, doc in enumerate(results, 1):
            title = doc.get("title", "Без названия")
            content = doc.get("content", "")[:500]
            doc_type = doc.get("doc_type", "document")
            formatted.append(f"[{i}] {title} ({doc_type}):\n{content}")
        
        return "\n\n".join(formatted)
    except Exception as e:
        logger.error(f"[Utils] ГАРАНТ search error: {e}")
        return f"Ошибка поиска в ГАРАНТ: {str(e)}"


async def get_garant_full_text(doc_id: str) -> str:
    """
    Получить полный текст документа из ГАРАНТ.
    
    Args:
        doc_id: ID документа или ссылка на статью
    
    Returns:
        Полный текст документа
    """
    garant_source = get_garant_source()
    if not garant_source:
        return "ГАРАНТ API недоступен."
    
    try:
        # Пробуем получить документ по ID
        if hasattr(garant_source, 'get_document'):
            result = await garant_source.get_document(doc_id)
            if result:
                return result.get("content", "Документ не найден")
        
        # Fallback - поиск по запросу
        results = await garant_source.search(query=doc_id, max_results=1)
        if results:
            return results[0].get("content", "Документ не найден")
        
        return f"Документ '{doc_id}' не найден в ГАРАНТ."
    except Exception as e:
        logger.error(f"[Utils] ГАРАНТ get_full_text error: {e}")
        return f"Ошибка получения документа: {str(e)}"


# Sync wrapper для инструментов
class GarantFullTextTool:
    """Обёртка для get_garant_full_text как инструмент."""
    
    def invoke(self, params: Dict[str, Any]) -> str:
        """Синхронный вызов."""
        import asyncio
        doc_id = params.get("doc_id", "")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, get_garant_full_text(doc_id))
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(get_garant_full_text(doc_id))
        except RuntimeError:
            return asyncio.run(get_garant_full_text(doc_id))


get_garant_full_text_tool = GarantFullTextTool()
