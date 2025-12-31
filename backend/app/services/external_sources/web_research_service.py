"""Web Research Service - структурированный процесс веб-исследований"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging
import asyncio
from app.services.external_sources.web_search import WebSearchSource
from app.services.external_sources.source_router import get_source_router
import hashlib
import json

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    """Результат исследования"""
    query: str
    sources: List[Dict[str, Any]]
    summary: str
    key_findings: List[str]
    confidence: float
    timestamp: str
    cache_key: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            "query": self.query,
            "sources": self.sources,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "cache_key": self.cache_key
        }


class WebResearchService:
    """Сервис для структурированных веб-исследований"""
    
    def __init__(self):
        self.web_search = WebSearchSource()
        self.source_router = get_source_router()
        self.cache: Dict[str, ResearchResult] = {}
        logger.info("WebResearchService initialized")
    
    def _make_cache_key(self, query: str, filters: Optional[Dict[str, Any]] = None) -> str:
        """Создать ключ кэша для запроса"""
        cache_data = {
            "query": query.lower().strip(),
            "filters": filters or {}
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    async def research(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
        validate_sources: bool = True
    ) -> ResearchResult:
        """
        Выполнить структурированное исследование
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
            filters: Фильтры для поиска
            use_cache: Использовать кэш
            validate_sources: Валидировать источники
        
        Returns:
            ResearchResult с результатами исследования
        """
        # Проверяем кэш
        if use_cache:
            cache_key = self._make_cache_key(query, filters)
            if cache_key in self.cache:
                logger.info(f"[WebResearch] Using cached result for query: {query[:50]}...")
                return self.cache[cache_key]
        
        logger.info(f"[WebResearch] Starting research for query: {query[:50]}...")
        
        # Выполняем поиск
        try:
            search_results = await self.web_search.search(
                query=query,
                max_results=max_results,
                filters=filters
            )
        except Exception as e:
            logger.error(f"[WebResearch] Search error: {e}", exc_info=True)
            # Возвращаем пустой результат при ошибке
            return ResearchResult(
                query=query,
                sources=[],
                summary="Ошибка при выполнении поиска",
                key_findings=[],
                confidence=0.0,
                timestamp=datetime.now().isoformat()
            )
        
        # Валидируем источники
        if validate_sources:
            search_results = self._validate_sources(search_results)
        
        # Извлекаем ключевые находки
        key_findings = self._extract_key_findings(search_results)
        
        # Формируем резюме
        summary = self._generate_summary(search_results, key_findings)
        
        # Вычисляем уверенность
        confidence = self._calculate_confidence(search_results, key_findings)
        
        # Создаем результат
        result = ResearchResult(
            query=query,
            sources=[self._format_source(r) for r in search_results],
            summary=summary,
            key_findings=key_findings,
            confidence=confidence,
            timestamp=datetime.now().isoformat(),
            cache_key=self._make_cache_key(query, filters) if use_cache else None
        )
        
        # Сохраняем в кэш
        if use_cache and result.cache_key:
            self.cache[result.cache_key] = result
            logger.debug(f"[WebResearch] Cached result with key: {result.cache_key}")
        
        logger.info(f"[WebResearch] Research completed: {len(search_results)} sources, confidence: {confidence:.2f}")
        return result
    
    def _validate_sources(self, sources: List[Any]) -> List[Any]:
        """Валидировать источники (удалить дубликаты, проверить релевантность)"""
        validated = []
        seen_urls = set()
        
        for source in sources:
            # Проверяем наличие URL
            url = getattr(source, 'url', None) or source.metadata.get('url', None) if hasattr(source, 'metadata') else None
            
            if url:
                # Удаляем дубликаты
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                
                # Проверяем релевантность (можно добавить дополнительную логику)
                validated.append(source)
            else:
                # Источники без URL тоже валидны
                validated.append(source)
        
        logger.debug(f"[WebResearch] Validated {len(validated)}/{len(sources)} sources")
        return validated
    
    def _extract_key_findings(self, sources: List[Any]) -> List[str]:
        """Извлечь ключевые находки из результатов поиска"""
        findings = []
        
        # Простое извлечение - можно улучшить с помощью LLM
        for source in sources[:5]:  # Берем первые 5 результатов
            content = getattr(source, 'content', None) or getattr(source, 'page_content', None) or ""
            if content:
                # Извлекаем первые несколько предложений
                sentences = content.split('.')[:3]
                findings.extend([s.strip() for s in sentences if s.strip()])
        
        return findings[:10]  # Ограничиваем до 10 находок
    
    def _generate_summary(self, sources: List[Any], key_findings: List[str]) -> str:
        """Сгенерировать резюме исследования"""
        if not sources:
            return "Результаты не найдены"
        
        summary_parts = [
            f"Найдено {len(sources)} источников.",
            f"Ключевые находки: {len(key_findings)}.",
        ]
        
        if key_findings:
            summary_parts.append("\nОсновные находки:\n" + "\n".join(f"- {f}" for f in key_findings[:5]))
        
        return "\n".join(summary_parts)
    
    def _calculate_confidence(self, sources: List[Any], key_findings: List[str]) -> float:
        """Вычислить уверенность в результатах"""
        if not sources:
            return 0.0
        
        # Базовая метрика уверенности
        # Можно улучшить, учитывая качество источников, количество находок и т.д.
        base_confidence = min(len(sources) / 10.0, 1.0)  # Максимум при 10+ источниках
        
        # Увеличиваем уверенность при наличии ключевых находок
        if key_findings:
            base_confidence = min(base_confidence + 0.2, 1.0)
        
        return base_confidence
    
    def _format_source(self, source: Any) -> Dict[str, Any]:
        """Форматировать источник для результата"""
        content = getattr(source, 'content', None) or getattr(source, 'page_content', None) or ""
        url = getattr(source, 'url', None) or (source.metadata.get('url', None) if hasattr(source, 'metadata') else None)
        title = getattr(source, 'title', None) or (source.metadata.get('title', None) if hasattr(source, 'metadata') else None)
        
        return {
            "content": content[:500] if content else "",  # Ограничиваем длину
            "url": url or "",
            "title": title or "",
            "source": getattr(source, 'source', 'web')
        }
    
    def clear_cache(self):
        """Очистить кэш"""
        self.cache.clear()
        logger.info("[WebResearch] Cache cleared")
    
    def get_cached_result(self, query: str, filters: Optional[Dict[str, Any]] = None) -> Optional[ResearchResult]:
        """Получить закэшированный результат"""
        cache_key = self._make_cache_key(query, filters)
        return self.cache.get(cache_key)


# Global service instance
_web_research_service_instance: Optional[WebResearchService] = None


def get_web_research_service() -> WebResearchService:
    """Get global web research service instance"""
    global _web_research_service_instance
    if _web_research_service_instance is None:
        _web_research_service_instance = WebResearchService()
    return _web_research_service_instance

