"""Legal Research Tool for searching precedents and case law"""
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from app.services.external_sources.source_router import get_source_router
import logging

logger = logging.getLogger(__name__)


@tool
def legal_research_tool(
    query: str,
    source: str = "all",  # moyarbitr, vas, egrul, fedres, all
    max_results: int = 10
) -> str:
    """
    Поиск прецедентов и case law в российских источниках права
    
    Интеграция с:
    - МойАрбитр (moyarbitr) - поиск судебных решений
    - ВАС практика (vas) - практика Высшего Арбитражного Суда
    - ЕГРЮЛ (egrul) - информация о компаниях
    - Fedres (fedres) - информация о банкротстве
    
    Args:
        query: Поисковый запрос (например, "возмещение убытков по договору поставки")
        source: Источник для поиска (moyarbitr, vas, egrul, fedres, all)
        max_results: Максимальное количество результатов
    
    Returns:
        Форматированная строка с результатами поиска и цитатами
    """
    try:
        logger.info(f"[LegalResearch] Searching for: {query[:100]}... (source: {source})")
        
        # Получаем source router
        router = get_source_router()
        
        # Определяем источники для поиска
        sources_to_search = []
        if source == "all":
            sources_to_search = ["moyarbitr", "vas", "web"]  # web как fallback
        elif source == "moyarbitr":
            sources_to_search = ["moyarbitr", "web"]
        elif source == "vas":
            sources_to_search = ["vas", "web"]
        elif source == "egrul":
            sources_to_search = ["egrul"]
        elif source == "fedres":
            sources_to_search = ["fedres"]
        else:
            sources_to_search = [source, "web"]  # web как fallback
        
        # Выполняем поиск через source router
        import asyncio
        from app.utils.async_utils import run_async_safe
        
        search_results = run_async_safe(router.search(
            query=query,
            source_names=sources_to_search,
            max_results_per_source=max_results,
            parallel=True
        ))
        
        # Агрегируем результаты
        aggregated = router.aggregate_results(
            search_results,
            max_total=max_results * 2,  # Больше результатов для агрегации
            dedup_threshold=0.9
        )
        
        # Форматируем для LLM
        formatted = router.format_for_llm(
            aggregated,
            max_chars=10000  # Достаточно для контекста
        )
        
        if not formatted:
            return f"Не найдено результатов по запросу: {query}\n\nПопробуйте изменить формулировку запроса или использовать другой источник."
        
        # Добавляем метаинформацию
        result_count = len(aggregated)
        sources_used = list(search_results.keys())
        
        result_text = f"Найдено {result_count} результатов из источников: {', '.join(sources_used)}\n\n"
        result_text += formatted
        
        logger.info(f"[LegalResearch] Found {result_count} results from {len(sources_used)} sources")
        
        return result_text
        
    except Exception as e:
        logger.error(f"[LegalResearch] Error searching legal precedents: {e}", exc_info=True)
        return f"Ошибка при поиске прецедентов: {str(e)}\n\nПопробуйте использовать web_search для общего поиска."


@tool
def search_precedents_tool(
    legal_issue: str,
    case_type: Optional[str] = None,
    court_level: Optional[str] = None  # first_instance, appeal, cassation, supreme
) -> str:
    """
    Специализированный поиск прецедентов по юридическому вопросу
    
    Args:
        legal_issue: Юридический вопрос (например, "признание договора недействительным")
        case_type: Тип дела (contract_dispute, corporate, etc.)
        court_level: Уровень суда (first_instance, appeal, cassation, supreme)
    
    Returns:
        Форматированные результаты с релевантными прецедентами
    """
    try:
        # Формируем расширенный запрос
        query_parts = [legal_issue]
        
        if case_type:
            query_parts.append(f"тип дела: {case_type}")
        
        if court_level:
            query_parts.append(f"уровень суда: {court_level}")
        
        query = " ".join(query_parts)
        
        # Используем legal_research_tool
        return legal_research_tool.invoke({
            "query": query,
            "source": "moyarbitr",  # Фокус на судебные решения
            "max_results": 15
        })
        
    except Exception as e:
        logger.error(f"[LegalResearch] Error in search_precedents: {e}", exc_info=True)
        return f"Ошибка при поиске прецедентов: {str(e)}"


def get_legal_research_tools() -> List:
    """Возвращает список инструментов для legal research"""
    return [legal_research_tool, search_precedents_tool]

