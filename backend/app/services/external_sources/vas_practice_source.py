"""ВАС практика source for searching Supreme Arbitration Court practice"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging

logger = logging.getLogger(__name__)


class VASPracticeSource(BaseSource):
    """
    Источник для поиска практики ВАС (Высший Арбитражный Суд)
    
    ВАЖНО: ВАС был упразднен в 2014, но его практика остается актуальной.
    В production нужно интегрировать с базой практики ВАС или использовать
    архивные источники.
    """
    
    def __init__(self):
        super().__init__(name="vas", enabled=True)
        self.base_url = "https://www.arbitr.ru"  # Сайт арбитражных судов
    
    async def initialize(self) -> bool:
        """Initialize ВАС practice source"""
        try:
            self._initialized = True
            logger.info("ВАС practice source initialized (using web_search fallback)")
        except Exception as e:
            logger.warning(f"ВАС practice source initialization warning: {e}")
            self._initialized = True
        return self._initialized
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Поиск практики ВАС
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
            filters: Фильтры (дата, тип практики)
        
        Returns:
            Список результатов с практикой ВАС
        """
        try:
            # Улучшаем запрос для поиска практики ВАС
            enhanced_query = f"{query} ВАС Высший Арбитражный Суд практика постановление"
            
            # Используем web_search как fallback
            from .web_search import WebSearchSource
            web_source = WebSearchSource()
            await web_source.ensure_initialized()
            
            web_results = await web_source.search(
                query=enhanced_query,
                max_results=max_results * 2  # Больше результатов для фильтрации
            )
            
            # Фильтруем результаты, связанные с ВАС
            vas_results = []
            for result in web_results:
                content_lower = (result.content or "").lower()
                title_lower = (result.title or "").lower()
                
                # Проверяем упоминание ВАС
                if any(keyword in content_lower or keyword in title_lower 
                       for keyword in ["вас", "высший арбитражный", "постановление пленума"]):
                    vas_result = SourceResult(
                        content=result.content,
                        title=result.title,
                        source_name="vas",
                        url=result.url,
                        relevance_score=result.relevance_score * 1.1,  # Повышаем релевантность
                        metadata={
                            **result.metadata,
                            "source_type": "court_practice",
                            "court": "vas",
                            "court_level": "supreme"
                        }
                    )
                    vas_results.append(vas_result)
            
            # Сортируем по релевантности
            vas_results.sort(key=lambda r: r.relevance_score, reverse=True)
            
            if not vas_results:
                logger.warning(f"No ВАС practice results found for query: {query}")
                vas_results.append(SourceResult(
                    content=f"Поиск практики ВАС по запросу '{query}' не дал результатов. "
                           f"Попробуйте использовать более общий запрос.",
                    title="Результаты поиска практики ВАС",
                    source_name="vas",
                    relevance_score=0.5
                ))
            
            logger.info(f"ВАС practice: Found {len(vas_results)} results for query: {query[:50]}")
            return vas_results[:max_results]
            
        except Exception as e:
            logger.error(f"Error searching ВАС practice: {e}", exc_info=True)
            return [SourceResult(
                content=f"Ошибка при поиске практики ВАС: {str(e)}",
                title="Ошибка поиска",
                source_name="vas",
                relevance_score=0.0
            )]
    
    async def health_check(self) -> bool:
        """Check if ВАС practice source is healthy"""
        try:
            return self._initialized
        except Exception:
            return False
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "initialized": self._initialized,
            "description": "Поиск практики ВАС (Высший Арбитражный Суд)"
        }

