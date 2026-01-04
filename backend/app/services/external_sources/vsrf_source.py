"""Прямой парсер для vsrf.ru - постановления Пленума ВС РФ"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from .web_search import WebSearchSource
import aiohttp
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class VSRFSource(BaseSource):
    """
    Прямой парсер для vsrf.ru (Верховный Суд РФ).
    
    Поддерживает:
    - Поиск постановлений Пленума ВС РФ
    - Поиск обзоров судебной практики
    - Извлечение полного текста разъяснений
    - Структурированные метаданные (дата, номер, название)
    
    Fallback на WebSearchSource если прямой доступ недоступен.
    """
    
    def __init__(self):
        super().__init__(name="vsrf", enabled=True)
        self.base_url = "https://vsrf.ru"
        self.fallback_source = None
        self.session = None
    
    async def initialize(self) -> bool:
        """Initialize vsrf.ru source"""
        try:
            # Создаем aiohttp session
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
            # Инициализируем fallback source
            self.fallback_source = WebSearchSource()
            await self.fallback_source.ensure_initialized()
            
            self._initialized = True
            logger.info("✅ VSRF source initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize VSRF source: {e}")
            self._initialized = False
            return False
    
    async def health_check(self) -> bool:
        """Check if vsrf.ru is accessible"""
        if not self.session:
            return False
        
        try:
            async with self.session.get(self.base_url, allow_redirects=True) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"VSRF health check failed: {e}")
            return False
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Поиск на vsrf.ru
        
        Args:
            query: Поисковый запрос (например: "постановление пленума о возмещении убытков")
            max_results: Максимальное количество результатов
            filters: Дополнительные фильтры (дата, тип документа)
        
        Returns:
            Список SourceResult с найденными постановлениями
        """
        try:
            # Пытаемся найти постановление напрямую
            # Формируем поисковый запрос
            search_url = f"{self.base_url}/search"
            
            if self.session:
                try:
                    # Параметры поиска
                    params = {
                        "q": query,
                        "limit": max_results
                    }
                    
                    async with self.session.get(search_url, params=params, allow_redirects=True) as response:
                        if response.status == 200:
                            html_content = await response.text()
                            results = self._parse_search_results(html_content, max_results)
                            
                            if results:
                                return results
                except Exception as e:
                    logger.debug(f"Direct search failed: {e}")
            
            # Fallback на web search
            logger.info(f"Using fallback search for query: {query}")
            if self.fallback_source:
                fallback_results = await self.fallback_source.search(
                    query=query,
                    max_results=max_results,
                    filters={"sites": ["vsrf.ru"]}
                )
                return fallback_results
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching vsrf.ru: {e}", exc_info=True)
            # Fallback на web search
            if self.fallback_source:
                try:
                    return await self.fallback_source.search(
                        query=query,
                        max_results=max_results,
                        filters={"sites": ["vsrf.ru"]}
                    )
                except Exception as fallback_error:
                    logger.error(f"Fallback search also failed: {fallback_error}")
            return []
    
    def _parse_search_results(self, html_content: str, max_results: int) -> List[SourceResult]:
        """
        Парсит результаты поиска из HTML
        
        Args:
            html_content: HTML содержимое страницы результатов
            max_results: Максимальное количество результатов
        
        Returns:
            Список SourceResult
        """
        results = []
        
        try:
            # Убираем скрипты и стили
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # Ищем ссылки на документы
            # Паттерны для поиска ссылок на постановления
            link_patterns = [
                r'<a[^>]*href="([^"]*postanovlenie[^"]*)"[^>]*>(.*?)</a>',
                r'<a[^>]*href="([^"]*documents[^"]*)"[^>]*>(.*?)</a>',
                r'<a[^>]*href="([^"]*plenum[^"]*)"[^>]*>(.*?)</a>',
            ]
            
            found_links = set()
            for pattern in link_patterns:
                matches = re.finditer(pattern, html_content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    if len(results) >= max_results:
                        break
                    
                    href = match.group(1)
                    link_text = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                    
                    # Нормализуем URL
                    if not href.startswith('http'):
                        if href.startswith('/'):
                            href = f"{self.base_url}{href}"
                        else:
                            href = f"{self.base_url}/{href}"
                    
                    if href not in found_links and link_text:
                        found_links.add(href)
                        results.append(SourceResult(
                            content=link_text,  # Временно используем заголовок
                            title=link_text,
                            source_name="vsrf",
                            url=href,
                            relevance_score=0.8,
                            metadata={
                                "type": "search_result",
                                "needs_fetch": True  # Нужно получить полный текст
                            }
                        ))
            
            # Если нашли ссылки, получаем полный текст для первых результатов
            if results and self.session:
                for i, result in enumerate(results[:3]):  # Получаем текст для первых 3
                    if result.metadata.get("needs_fetch"):
                        full_text = await self._fetch_document_text(result.url)
                        if full_text:
                            result.content = full_text
                            result.metadata.pop("needs_fetch", None)
            
            return results[:max_results]
            
        except Exception as e:
            logger.error(f"Error parsing search results: {e}", exc_info=True)
            return results
    
    async def _fetch_document_text(self, url: str) -> Optional[str]:
        """
        Получает полный текст документа по URL
        
        Args:
            url: URL документа
        
        Returns:
            Текст документа или None
        """
        if not self.session:
            return None
        
        try:
            async with self.session.get(url, allow_redirects=True) as response:
                if response.status == 200:
                    html_content = await response.text()
                    return self._parse_document_html(html_content)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching document from {url}: {e}")
            return None
    
    def _parse_document_html(self, html_content: str) -> Optional[str]:
        """
        Парсит HTML документа для извлечения текста
        
        Args:
            html_content: HTML содержимое страницы документа
        
        Returns:
            Текст документа или None
        """
        try:
            # Убираем скрипты и стили
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # Ищем основной контент документа
            content_patterns = [
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*document[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
            ]
            
            extracted_texts = []
            for pattern in content_patterns:
                matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    # Убираем HTML теги
                    text = re.sub(r'<[^>]+>', '', match)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text and len(text) > 100:  # Минимальная длина для валидного текста
                        extracted_texts.append(text)
            
            if extracted_texts:
                # Объединяем все тексты
                full_text = "\n\n".join(extracted_texts)
                return full_text
            
            # Fallback: извлекаем весь текст из body
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
            if body_match:
                text = re.sub(r'<[^>]+>', '', body_match.group(1))
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 100:
                    return text
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing document HTML: {e}", exc_info=True)
            return None
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_initialized()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

