"""Прямой парсер для kad.arbitr.ru - картотека арбитражных дел"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from .web_search import WebSearchSource
import aiohttp
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class KadArbitrSource(BaseSource):
    """
    Прямой парсер для kad.arbitr.ru (картотека арбитражных дел).
    
    Поддерживает:
    - Поиск дел по номеру (А40-12345/2023)
    - Поиск по участникам (ИНН, название)
    - Получение списка документов по делу
    - Скачивание текста решений (PDF parsing)
    
    Fallback на WebSearchSource если прямой доступ недоступен.
    """
    
    def __init__(self):
        super().__init__(name="kad_arbitr", enabled=True)
        self.base_url = "https://kad.arbitr.ru"
        self.fallback_source = None
        self.session = None
    
    async def initialize(self) -> bool:
        """Initialize kad.arbitr.ru source"""
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
            logger.info("✅ KadArbitr source initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize KadArbitr source: {e}")
            self._initialized = False
            return False
    
    async def health_check(self) -> bool:
        """Check if kad.arbitr.ru is accessible"""
        if not self.session:
            return False
        
        try:
            async with self.session.get(self.base_url, allow_redirects=True) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"KadArbitr health check failed: {e}")
            return False
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Поиск на kad.arbitr.ru
        
        Args:
            query: Поисковый запрос (например: "А40-12345/2023" или название участника)
            max_results: Максимальное количество результатов
            filters: Дополнительные фильтры (ИНН, суд, дата)
        
        Returns:
            Список SourceResult с найденными делами
        """
        try:
            # Пытаемся распарсить номер дела из запроса
            case_number = self._parse_case_number(query)
            
            if case_number:
                # Прямой поиск по номеру дела
                result = await self._get_case_by_number(case_number)
                if result:
                    return [result]
            
            # Если не удалось найти напрямую, используем fallback
            logger.info(f"Using fallback search for query: {query}")
            if self.fallback_source:
                fallback_results = await self.fallback_source.search(
                    query=query,
                    max_results=max_results,
                    filters={"sites": ["kad.arbitr.ru"]}
                )
                return fallback_results
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching kad.arbitr.ru: {e}", exc_info=True)
            # Fallback на web search
            if self.fallback_source:
                try:
                    return await self.fallback_source.search(
                        query=query,
                        max_results=max_results,
                        filters={"sites": ["kad.arbitr.ru"]}
                    )
                except Exception as fallback_error:
                    logger.error(f"Fallback search also failed: {fallback_error}")
            return []
    
    def _parse_case_number(self, query: str) -> Optional[str]:
        """
        Парсит номер дела из запроса
        
        Примеры:
        - "А40-12345/2023" -> "А40-12345/2023"
        - "дело А40-12345/2023" -> "А40-12345/2023"
        - "А40 12345/2023" -> "А40-12345/2023"
        
        Returns:
            Номер дела или None
        """
        # Паттерн для номеров арбитражных дел
        # Формат: [буквы][цифры]-[цифры]/[год]
        pattern = r'([А-Я]\d{1,3})[-\s]*(\d+)/(\d{4})'
        match = re.search(pattern, query, re.IGNORECASE)
        
        if match:
            court_prefix = match.group(1)
            case_number = match.group(2)
            year = match.group(3)
            return f"{court_prefix}-{case_number}/{year}"
        
        return None
    
    async def _get_case_by_number(self, case_number: str) -> Optional[SourceResult]:
        """
        Получает дело по номеру
        
        Args:
            case_number: Номер дела (например: "А40-12345/2023")
        
        Returns:
            SourceResult с информацией о деле или None
        """
        if not self.session:
            return None
        
        try:
            # Формируем URL для дела
            # Структура URL на kad.arbitr.ru
            url = f"{self.base_url}/Card/{case_number}"
            
            async with self.session.get(url, allow_redirects=True) as response:
                if response.status == 200:
                    html_content = await response.text()
                    
                    # Парсим HTML для извлечения информации о деле
                    case_info = self._parse_case_html(html_content, case_number)
                    
                    if case_info:
                        return SourceResult(
                            content=case_info["content"],
                            title=case_info["title"],
                            source_name="kad_arbitr",
                            url=url,
                            relevance_score=1.0,  # Прямой доступ = максимальная релевантность
                            metadata={
                                "case_number": case_number,
                                "court": case_info.get("court"),
                                "participants": case_info.get("participants", []),
                                "documents": case_info.get("documents", []),
                                "direct_access": True
                            }
                        )
            
            logger.warning(f"Could not fetch case {case_number} from kad.arbitr.ru")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching case directly: {e}", exc_info=True)
            return None
    
    def _parse_case_html(self, html_content: str, case_number: str) -> Optional[Dict[str, Any]]:
        """
        Парсит HTML для извлечения информации о деле
        
        Args:
            html_content: HTML содержимое страницы дела
            case_number: Номер дела
        
        Returns:
            Словарь с информацией о деле или None
        """
        try:
            # Убираем скрипты и стили
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # Извлекаем информацию о деле
            case_info = {
                "title": f"Дело {case_number}",
                "content": "",
                "court": None,
                "participants": [],
                "documents": []
            }
            
            # Ищем название суда
            court_patterns = [
                r'<[^>]*class="[^"]*court[^"]*"[^>]*>(.*?)</[^>]+>',
                r'Суд[:\s]+(.*?)(?:<|$)',
            ]
            
            for pattern in court_patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    court_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                    if court_text:
                        case_info["court"] = court_text
                        break
            
            # Ищем участников
            participant_patterns = [
                r'<[^>]*class="[^"]*participant[^"]*"[^>]*>(.*?)</[^>]+>',
                r'Истец[:\s]+(.*?)(?:<|$)',
                r'Ответчик[:\s]+(.*?)(?:<|$)',
            ]
            
            for pattern in participant_patterns:
                matches = re.finditer(pattern, html_content, re.IGNORECASE)
                for match in matches:
                    participant_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                    if participant_text and participant_text not in case_info["participants"]:
                        case_info["participants"].append(participant_text)
            
            # Ищем документы
            document_patterns = [
                r'<a[^>]*href="([^"]*document[^"]*)"[^>]*>(.*?)</a>',
                r'<a[^>]*href="([^"]*\.pdf)"[^>]*>(.*?)</a>',
            ]
            
            for pattern in document_patterns:
                matches = re.finditer(pattern, html_content, re.IGNORECASE)
                for match in matches:
                    doc_url = match.group(1)
                    doc_title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                    
                    # Нормализуем URL
                    if not doc_url.startswith('http'):
                        if doc_url.startswith('/'):
                            doc_url = f"{self.base_url}{doc_url}"
                        else:
                            doc_url = f"{self.base_url}/{doc_url}"
                    
                    if doc_title:
                        case_info["documents"].append({
                            "title": doc_title,
                            "url": doc_url
                        })
            
            # Извлекаем основной контент
            content_patterns = [
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*case[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*info[^"]*"[^>]*>(.*?)</div>',
            ]
            
            extracted_texts = []
            for pattern in content_patterns:
                matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    text = re.sub(r'<[^>]+>', '', match)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text and len(text) > 50:
                        extracted_texts.append(text)
            
            if extracted_texts:
                case_info["content"] = "\n\n".join(extracted_texts)
            
            # Формируем заголовок
            if case_info["court"]:
                case_info["title"] = f"{case_info['title']} ({case_info['court']})"
            
            return case_info
            
        except Exception as e:
            logger.error(f"Error parsing case HTML: {e}", exc_info=True)
            return None
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_initialized()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

