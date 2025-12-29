"""МойАрбитр source for searching Russian court decisions"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging

logger = logging.getLogger(__name__)


class MoyArbitrSource(BaseSource):
    """
    Источник для поиска судебных решений в МойАрбитр
    
    ВАЖНО: Это заглушка. В production нужно интегрировать с реальным API МойАрбитр
    или использовать парсинг сайта moyarbitr.ru
    """
    
    def __init__(self):
        super().__init__(name="moyarbitr", enabled=True)
        # В production здесь должны быть credentials для API
        self.api_key = getattr(config, 'MOYARBITR_API_KEY', None)
        self.base_url = "https://moyarbitr.ru"  # Пример URL
    
    async def initialize(self) -> bool:
        """Initialize МойАрбитр source"""
        # Проверяем доступность API или сайта
        try:
            # В production: проверка API доступности
            # Пока используем fallback на web_search
            self._initialized = True
            logger.info("МойАрбитр source initialized (using web_search fallback)")
        except Exception as e:
            logger.warning(f"МойАрбитр source initialization warning: {e}")
            self._initialized = True  # Все равно включаем, будет fallback
        return self._initialized
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Поиск судебных решений в МойАрбитр
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
            filters: Фильтры (дата, суд, тип дела)
        
        Returns:
            Список результатов с судебными решениями
        """
        try:
            # В production: реальный API вызов
            # Пока используем fallback на web_search с уточнением запроса
            
            # Добавляем ключевые слова для поиска судебных решений
            enhanced_query = f"{query} site:moyarbitr.ru решение суда"
            
            # Используем web_search как fallback
            from .web_search import WebSearchSource
            web_source = WebSearchSource()
            await web_source.ensure_initialized()
            
            web_results = await web_source.search(
                query=enhanced_query,
                max_results=max_results
            )
            
            # Преобразуем результаты в формат МойАрбитр
            moyarbitr_results = []
            for result in web_results:
                # Фильтруем только результаты с moyarbitr.ru
                if "moyarbitr.ru" in (result.url or ""):
                    moyarbitr_result = SourceResult(
                        content=result.content,
                        title=result.title,
                        source_name="moyarbitr",
                        url=result.url,
                        relevance_score=result.relevance_score,
                        metadata={
                            **result.metadata,
                            "source_type": "court_decision",
                            "court": "arbitration"  # Арбитражный суд
                        }
                    )
                    moyarbitr_results.append(moyarbitr_result)
            
            if not moyarbitr_results:
                logger.warning(f"No МойАрбитр results found for query: {query}")
                # Возвращаем хотя бы один результат с информацией
                moyarbitr_results.append(SourceResult(
                    content=f"Поиск в МойАрбитр по запросу '{query}' не дал результатов. "
                           f"Попробуйте изменить формулировку или использовать другой источник.",
                    title="Результаты поиска в МойАрбитр",
                    source_name="moyarbitr",
                    relevance_score=0.5
                ))
            
            logger.info(f"МойАрбитр: Found {len(moyarbitr_results)} results for query: {query[:50]}")
            return moyarbitr_results[:max_results]
            
        except Exception as e:
            logger.error(f"Error searching МойАрбитр: {e}", exc_info=True)
            # Возвращаем пустой результат с ошибкой
            return [SourceResult(
                content=f"Ошибка при поиске в МойАрбитр: {str(e)}",
                title="Ошибка поиска",
                source_name="moyarbitr",
                relevance_score=0.0
            )]
    
    async def health_check(self) -> bool:
        """Check if МойАрбитр source is healthy"""
        try:
            # В production: проверка API
            return self._initialized
        except Exception:
            return False
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "initialized": self._initialized,
            "description": "Поиск судебных решений в МойАрбитр (арбитражные суды)"
        }

