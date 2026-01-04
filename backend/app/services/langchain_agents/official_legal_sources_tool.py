"""Official legal sources search tools using Yandex Web Search API"""
from langchain_core.tools import tool
from typing import Optional
from app.services.external_sources.web_search import WebSearchSource
import logging
import asyncio
import concurrent.futures

logger = logging.getLogger(__name__)

# Глобальный экземпляр WebSearchSource
_web_search_source = None


def get_web_search_source():
    """Получить экземпляр WebSearchSource"""
    global _web_search_source
    if _web_search_source is None:
        _web_search_source = WebSearchSource()
    return _web_search_source


def _yandex_search_sync(query: str, site: str, top_k: int = 5) -> str:
    """
    Wrapper над Yandex Web Search API с фильтрацией по домену (синхронная версия)
    
    Args:
        query: Поисковый запрос
        site: Домен для фильтрации (pravo.gov.ru, vsrf.ru, kad.arbitr.ru)
        top_k: Количество результатов
    
    Returns:
        Структурированный текст с результатами
    """
    web_search = get_web_search_source()
    
    # Используем существующий метод с фильтром по домену
    filters = {"sites": [site]} if site else None
    
    try:
        # Вызываем async метод синхронно
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если loop уже запущен, пробуем использовать nest_asyncio
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    results = loop.run_until_complete(
                        web_search.search(query, max_results=top_k, filters=filters)
                    )
                except ImportError:
                    # nest_asyncio не установлен, создаем новый loop в отдельном потоке
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            web_search.search(query, max_results=top_k, filters=filters)
                        )
                        results = future.result()
            else:
                results = loop.run_until_complete(
                    web_search.search(query, max_results=top_k, filters=filters)
                )
        except RuntimeError:
            # Нет event loop, создаем новый
            results = asyncio.run(
                web_search.search(query, max_results=top_k, filters=filters)
            )
        
        # Форматируем результаты
        formatted_results = []
        for i, result in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {result.title or 'Без названия'}\n"
                f"   URL: {result.url or ''}\n"
                f"   Сниппет: {result.content[:200] if result.content else ''}...\n"
            )
        
        return "\n".join(formatted_results) if formatted_results else "Результаты не найдены"
    
    except Exception as e:
        logger.error(f"Error in Yandex search for {site}: {e}")
        return f"Ошибка поиска: {str(e)}"


@tool
def search_legislation_tool(query: str) -> str:
    """
    Поиск норм права на pravo.gov.ru (официальное законодательство)
    
    Используй этот инструмент когда:
    - Нужна конкретная статья кодекса (ГК, ГПК, АПК)
    - Нужна норма права для анализа
    - Нужно проверить действующее законодательство
    
    Args:
        query: Поисковый запрос (например: "статья 393 ГК РФ")
    
    Returns:
        Структурированные результаты поиска с pravo.gov.ru
    """
    logger.info(f"[Legislation Tool] Searching: {query}")
    return _yandex_search_sync(query, "pravo.gov.ru", top_k=5)


@tool
def search_supreme_court_tool(query: str) -> str:
    """
    Поиск позиций Верховного Суда РФ на vsrf.ru
    
    Используй этот инструмент когда:
    - Нужны разъяснения Верховного Суда
    - Нужна позиция ВС по конкретному вопросу
    - Нужны постановления Пленума ВС
    
    Args:
        query: Поисковый запрос (например: "разъяснения о возмещении убытков")
    
    Returns:
        Структурированные результаты поиска с vsrf.ru
    """
    logger.info(f"[Supreme Court Tool] Searching: {query}")
    return _yandex_search_sync(query, "vsrf.ru", top_k=5)


@tool
def search_case_law_tool(query: str) -> str:
    """
    Поиск судебной практики на kad.arbitr.ru (картотека арбитражных дел)
    
    Используй этот инструмент когда:
    - Нужны аналогичные дела
    - Нужны прецеденты
    - Нужна практика судов по конкретному вопросу
    
    Args:
        query: Поисковый запрос (например: "решения по договорам поставки")
    
    Returns:
        Структурированные результаты поиска с kad.arbitr.ru
    """
    logger.info(f"[Case Law Tool] Searching: {query}")
    return _yandex_search_sync(query, "kad.arbitr.ru", top_k=5)


@tool
def smart_legal_search_tool(query: str) -> str:
    """
    Умный поиск с автоматическим выбором источника
    
    Используй этот инструмент когда:
    - Не уверен, какой именно сайт нужен
    - Нужна информация из нескольких источников
    - Запрос общий и может быть в разных источниках
    
    Args:
        query: Поисковый запрос
    
    Returns:
        Результаты поиска с автоматически выбранного источника
    """
    from app.services.legal_reasoning_model import LegalReasoningModel, SourceType
    
    logger.info(f"[Smart Legal Search] Auto-selecting source for: {query}")
    
    # Используем LegalReasoningModel для выбора источника
    reasoning_model = LegalReasoningModel()
    task = reasoning_model.identify_task_type(query)
    source = reasoning_model.determine_source_type(task)
    
    if source == SourceType.PRAVO:
        return search_legislation_tool.invoke(query)
    elif source == SourceType.VS:
        return search_supreme_court_tool.invoke(query)
    elif source == SourceType.KAD:
        return search_case_law_tool.invoke(query)
    else:
        # Fallback: поиск без фильтрации
        return _yandex_search_sync(query, "", top_k=5)

