"""Garant legal database tools for LangChain agents"""
from typing import Optional
from langchain_core.tools import tool
from app.services.external_sources.garant_source import GarantSource
from app.services.external_sources.source_router import get_source_router
import logging
import asyncio
import concurrent.futures

logger = logging.getLogger(__name__)

# Глобальный экземпляр GarantSource
_garant_source = None


def get_garant_source() -> Optional[GarantSource]:
    """Получить экземпляр GarantSource"""
    global _garant_source
    if _garant_source is None:
        # Пытаемся получить из source_router
        try:
            router = get_source_router()
            garant_source = router.get_source("garant")
            if garant_source and isinstance(garant_source, GarantSource):
                _garant_source = garant_source
                logger.info("[Garant Tools] Using GarantSource from source_router")
            else:
                # Создаем новый экземпляр
                _garant_source = GarantSource()
                asyncio.run(_garant_source.initialize())
                logger.info("[Garant Tools] Created new GarantSource instance")
        except Exception as e:
            logger.warning(f"[Garant Tools] Failed to get GarantSource from router: {e}, creating new instance")
            _garant_source = GarantSource()
            try:
                asyncio.run(_garant_source.initialize())
            except Exception as init_error:
                logger.error(f"[Garant Tools] Failed to initialize GarantSource: {init_error}")
                return None
    return _garant_source


def _garant_search_sync(query: str, doc_type: str = "all", max_results: int = 10) -> str:
    """
    Синхронная обертка для поиска в ГАРАНТ
    
    Args:
        query: Поисковый запрос
        doc_type: Тип документа (all, law, court_decision, article, commentary)
        max_results: Количество результатов
    
    Returns:
        Форматированная строка с результатами
    """
    garant_source = get_garant_source()
    if not garant_source:
        return "Ошибка: ГАРАНТ не настроен. Проверьте GARANT_API_KEY в конфигурации."
    
    if not garant_source.api_key:
        return "Ошибка: API ключ ГАРАНТ не настроен."
    
    # Подготавливаем фильтры
    filters = None
    if doc_type and doc_type != "all":
        filters = {"doc_type": doc_type}
    
    try:
        # Вызываем async метод синхронно
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если loop уже запущен, используем ThreadPoolExecutor
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        garant_source.search(query, max_results=max_results, filters=filters)
                    )
                    results = future.result()
            else:
                results = loop.run_until_complete(
                    garant_source.search(query, max_results=max_results, filters=filters)
                )
        except RuntimeError:
            # Нет event loop, создаем новый
            results = asyncio.run(
                garant_source.search(query, max_results=max_results, filters=filters)
            )
        
        if not results:
            return f"Не найдено результатов по запросу: {query}\n\nПопробуйте изменить формулировку запроса."
        
        # Форматируем результаты для LLM
        formatted_parts = []
        for i, result in enumerate(results, 1):
            title = result.title or "Без названия"
            url = result.url or ""
            content = result.content[:1000] if result.content else ""
            
            # Извлекаем метаданные
            metadata = getattr(result, 'metadata', {}) or {}
            doc_type_info = metadata.get('doc_type', '')
            doc_date = metadata.get('doc_date', '')
            doc_number = metadata.get('doc_number', '')
            
            formatted_parts.append(f"\n{'='*60}")
            formatted_parts.append(f"ДОКУМЕНТ {i} ИЗ ГАРАНТ")
            formatted_parts.append(f"{'='*60}")
            formatted_parts.append(f"Название: {title}")
            
            if doc_type_info:
                formatted_parts.append(f"Тип: {doc_type_info}")
            if doc_date:
                formatted_parts.append(f"Дата: {doc_date}")
            if doc_number:
                formatted_parts.append(f"Номер: {doc_number}")
            if url:
                formatted_parts.append(f"Ссылка: {url}")
            
            if content:
                formatted_parts.append(f"\nСодержание:\n{content}")
                if len(result.content) > 1000:
                    formatted_parts.append(f"\n[... документ обрезан, полный текст доступен по ссылке ...]")
            
            formatted_parts.append(f"{'='*60}\n")
        
        return "\n".join(formatted_parts)
    
    except Exception as e:
        logger.error(f"[Garant Tools] Error in search: {e}", exc_info=True)
        return f"Ошибка поиска в ГАРАНТ: {str(e)}"


def _garant_full_text_sync(doc_id: str) -> str:
    """
    Синхронная обертка для получения полного текста из ГАРАНТ
    
    Args:
        doc_id: ID документа из результатов search_garant
    
    Returns:
        Полный текст документа
    """
    garant_source = get_garant_source()
    if not garant_source:
        return "Ошибка: ГАРАНТ не настроен."
    
    if not garant_source.api_key:
        return "Ошибка: API ключ ГАРАНТ не настроен."
    
    if not doc_id:
        return "Ошибка: не указан ID документа."
    
    try:
        # Вызываем async метод синхронно
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        garant_source.get_document_full_text(doc_id, format="html")
                    )
                    full_text = future.result()
            else:
                full_text = loop.run_until_complete(
                    garant_source.get_document_full_text(doc_id, format="html")
                )
        except RuntimeError:
            full_text = asyncio.run(
                garant_source.get_document_full_text(doc_id, format="html")
            )
        
        if not full_text:
            return f"Не удалось получить полный текст документа {doc_id}."
        
        # Парсим HTML и извлекаем текст
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(full_text, 'html.parser')
            text_content = soup.get_text(separator='\n', strip=True)
            return text_content[:10000]  # Ограничиваем размер для безопасности
        except ImportError:
            # Если BeautifulSoup не установлен, используем простую очистку HTML
            import re
            text_content = re.sub(r'<[^>]+>', '', full_text)
            return text_content[:10000]
    
    except Exception as e:
        logger.error(f"[Garant Tools] Error getting full text: {e}", exc_info=True)
        return f"Ошибка получения полного текста: {str(e)}"


@tool
def search_garant(query: str, doc_type: str = "all", max_results: int = 10) -> str:
    """
    Поиск в правовой базе ГАРАНТ.
    
    Используй этот инструмент когда:
    - Нужна статья кодекса (ГК, ГПК, АПК, УК)
    - Нужен закон или нормативный акт
    - Нужно судебное решение или практика
    - Нужен комментарий к норме права
    
    НЕ ИСПОЛЬЗУЙ когда:
    - Пользователь спрашивает про свои документы ("мой договор", "в иске")
    - Нужны факты из конкретного дела пользователя
    
    Args:
        query: Поисковый запрос (например: "статья 393 ГК РФ" или "судебные решения по банкротству")
        doc_type: Тип документа (all, law, court_decision, article, commentary). 
                  Используй "all" для общего поиска, или конкретный тип для фильтрации.
        max_results: Количество результатов (по умолчанию 10, максимум 20)
    
    Returns:
        Форматированная строка с результатами поиска из ГАРАНТ, включая названия, даты, ссылки и содержание документов.
    """
    logger.info(f"[Garant Tools] Searching: {query[:100]}... (doc_type={doc_type}, max_results={max_results})")
    return _garant_search_sync(query, doc_type, max_results)


@tool
def get_garant_full_text(doc_id: str) -> str:
    """
    Получить полный текст документа из ГАРАНТ.
    
    Используй этот инструмент после search_garant когда:
    - Нужен полный текст статьи или документа
    - Пользователь явно просит "полный текст" или "весь текст"
    - Нужны все детали документа, а не только краткое содержание
    
    Args:
        doc_id: ID документа из результатов search_garant (поле "doc_id" в метаданных результата)
    
    Returns:
        Полный текст документа в читаемом формате (HTML теги удалены)
    """
    logger.info(f"[Garant Tools] Getting full text for document: {doc_id}")
    return _garant_full_text_sync(doc_id)


