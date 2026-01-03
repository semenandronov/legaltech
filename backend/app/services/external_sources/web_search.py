"""Web search source using Yandex Search API"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging
import re

logger = logging.getLogger(__name__)


class WebSearchSource(BaseSource):
    """
    Web search source using Yandex Search API.
    Falls back to a simple search if Yandex API is not configured.
    """
    
    def __init__(self):
        super().__init__(name="web_search", enabled=True)
        # Используем YANDEX_API_KEY вместо YANDEX_SEARCH_API_KEY (которой нет в конфиге)
        yandex_search_key = getattr(config, 'YANDEX_SEARCH_API_KEY', None)
        yandex_api_key = getattr(config, 'YANDEX_API_KEY', None)
        self.api_key = yandex_search_key or yandex_api_key
        self.folder_id = config.YANDEX_FOLDER_ID
        
        # Детальное логирование для отладки
        logger.info(f"[WebSearch] Initialization: YANDEX_SEARCH_API_KEY={bool(yandex_search_key)}, "
                   f"YANDEX_API_KEY={bool(yandex_api_key)}, "
                   f"YANDEX_FOLDER_ID={bool(self.folder_id)}, "
                   f"api_key_set={self.api_key is not None}, "
                   f"api_key_length={len(self.api_key) if self.api_key else 0}, "
                   f"folder_id_length={len(self.folder_id) if self.folder_id else 0}")
        
        # Yandex Search API v2 через Yandex Cloud gateway
        # Старый v1 (XML) отключен с 31 декабря 2025
        # Используем endpoint для v2 согласно документации: https://yandex.cloud/ru/docs/search-api
        # Правильный endpoint: https://searchapi.api.cloud.yandex.net/v2/web/search
        self.base_url = "https://searchapi.api.cloud.yandex.net/v2/web/search"
    
    async def initialize(self) -> bool:
        """Initialize web search source"""
        # Check if we have the necessary credentials
        if self.api_key and self.folder_id:
            self._initialized = True
            logger.info("Web search source initialized with Yandex Search API")
        else:
            # Can still work with fallback
            self._initialized = True
            logger.warning(
                "Web search source: Yandex Search API not configured, "
                "using fallback mode"
            )
        return self._initialized
    
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search the web for relevant content
        
        Args:
            query: Search query
            max_results: Maximum number of results
            filters: Optional filters (e.g., site restriction, language)
            
        Returns:
            List of SourceResult
        """
        if not query.strip():
            return []
        
        # Enhance query for legal context
        enhanced_query = self._enhance_legal_query(query, filters)
        
        try:
            # Детальное логирование для отладки
            logger.info(f"[WebSearch] Search request: query='{enhanced_query[:100]}', "
                       f"has_api_key={self.api_key is not None}, "
                       f"api_key_length={len(self.api_key) if self.api_key else 0}, "
                       f"has_folder_id={bool(self.folder_id)}, "
                       f"folder_id_length={len(self.folder_id) if self.folder_id else 0}")
            
            if self.api_key and self.folder_id:
                logger.info(f"[WebSearch] Calling Yandex Search API with query: {enhanced_query[:100]}")
                return await self._search_yandex_api(enhanced_query, max_results, filters)
            else:
                # Fallback: return empty results with a note
                logger.warning(f"[WebSearch] No API configured - api_key={self.api_key is not None}, "
                             f"folder_id={bool(self.folder_id)}. Returning empty results.")
                return []
        except Exception as e:
            logger.warning(f"Web search error: {e}")
            return []
    
    def _enhance_legal_query(
        self, 
        query: str, 
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Enhance query for legal search context
        
        Args:
            query: Original query
            filters: Optional filters with context
            
        Returns:
            Enhanced query
        """
        # Add legal context if not already present
        legal_terms = ["закон", "право", "юридический", "суд", "договор", "контракт"]
        query_lower = query.lower()
        
        has_legal_context = any(term in query_lower for term in legal_terms)
        
        if not has_legal_context and filters:
            context = filters.get("context", "")
            if context:
                return f"{query} {context}"
        
        return query
    
    async def _search_yandex_api(
        self,
        query: str,
        max_results: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search using Yandex Search API v2 (Yandex Cloud gateway)
        
        Args:
            query: Search query
            max_results: Maximum results
            filters: Optional filters
            
        Returns:
            List of SourceResult
        """
        logger.info(f"[WebSearch] Starting Yandex Search API v2 request: query='{query[:100]}', "
                   f"max_results={max_results}, base_url={self.base_url}")
        
        # Yandex Search API v2 использует JSON формат и POST запросы
        # Согласно документации: https://yandex.cloud/ru/docs/search-api
        # Правильный формат запроса для v2
        request_body = {
            "query": {
                "searchType": "SEARCH_TYPE_COM",
                "queryText": query,
                "familyMode": "FAMILY_MODE_MODERATE"
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": max_results,
                "docsInGroup": 1
            },
            "responseFormat": "FORMAT_XML",
            "folderId": self.folder_id
        }
        
        # Add site restriction if specified
        if filters and filters.get("sites"):
            sites = filters["sites"]
            if isinstance(sites, list):
                # В v2 можно использовать фильтры по доменам через queryText
                if len(sites) == 1:
                    request_body["query"]["queryText"] = f"{query} site:{sites[0]}"
        
        # Правильная аутентификация через заголовки для v2
        # Поддерживаем как API ключ, так и IAM токен
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"[WebSearch] Sending POST request to Yandex Search API v2: url={self.base_url}, "
                           f"has_headers={bool(headers)}, body_keys={list(request_body.keys())}")
                
                async with session.post(
                    self.base_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    # Читаем ответ один раз
                    content = await response.text()
                    
                    logger.info(f"[WebSearch] Received response: status={response.status}, "
                               f"content_type={response.headers.get('Content-Type', '')}, "
                               f"content_length={len(content)}")
                    logger.debug(f"[WebSearch] Response preview: {content[:1000]}")
                    
                    if response.status != 200:
                        logger.warning(f"[WebSearch] Yandex Search API v2 error: status={response.status}, "
                                     f"error_text={content[:500]}")
                        return []
                    
                    # Parse XML response (v2 использует XML или HTML формат)
                    logger.info(f"[WebSearch] Parsing XML response: content_length={len(content)}")
                    return self._parse_yandex_response(content)
                    
        except aiohttp.ClientError as e:
            logger.warning(f"[WebSearch] Yandex Search API v2 connection error: {e}")
            return []
        except Exception as e:
            logger.warning(f"[WebSearch] Yandex Search API v2 error: {e}")
            return []
    
    def _parse_yandex_response(self, xml_content: str) -> List[SourceResult]:
        """
        Parse Yandex Search API XML response
        
        Args:
            xml_content: XML response string
            
        Returns:
            List of SourceResult
        """
        results = []
        
        try:
            import xml.etree.ElementTree as ET
            
            # Логируем полную структуру XML для отладки
            logger.info(f"[WebSearch] XML response (full, {len(xml_content)} chars): {xml_content}")
            logger.info(f"[WebSearch] XML response preview (first 1000 chars): {xml_content[:1000]}")
            
            root = ET.fromstring(xml_content)
            
            # Логируем корневой элемент и его дочерние элементы
            root_children = [child.tag for child in root]
            logger.info(f"[WebSearch] Root element: {root.tag}, namespace: {root.tag.split('}')[0] if '}' in root.tag else 'none'}, children: {root_children}")
            
            # Пробуем разные варианты структуры XML
            # Вариант 1: Стандартная структура с group и doc
            groups = root.findall(".//group")
            logger.info(f"[WebSearch] Found {len(groups)} groups using .//group")
            
            # Также пробуем с namespace
            if not groups:
                # Пробуем найти group без namespace
                for elem in root.iter():
                    if 'group' in elem.tag.lower():
                        logger.info(f"[WebSearch] Found group-like element: {elem.tag}")
            
            if not groups:
                # Вариант 2: Прямые doc элементы
                docs = root.findall(".//doc")
                logger.info(f"[WebSearch] Found {len(docs)} direct doc elements using .//doc")
                
                if not docs:
                    # Вариант 3: Проверяем все элементы
                    all_elements = list(root.iter())
                    element_tags = [elem.tag for elem in all_elements[:30]]
                    logger.info(f"[WebSearch] All XML elements (first 30): {element_tags}")
                    
                    # Ищем любые элементы, которые могут содержать результаты
                    for elem in root.iter():
                        if elem.text and len(elem.text.strip()) > 10:
                            logger.info(f"[WebSearch] Element with text: tag={elem.tag}, text_preview={elem.text[:100]}")
            
            # Find all doc elements
            for group in root.findall(".//group"):
                for doc in group.findall(".//doc"):
                    try:
                        url_elem = doc.find("url")
                        title_elem = doc.find("title")
                        passages = doc.findall(".//passage")
                        
                        url = url_elem.text if url_elem is not None else ""
                        title = self._clean_html(title_elem.text) if title_elem is not None else "Без названия"
                        
                        # Combine passages for content
                        content_parts = []
                        for passage in passages:
                            if passage.text:
                                content_parts.append(self._clean_html(passage.text))
                        
                        content = " ".join(content_parts) if content_parts else ""
                        
                        if content or title:
                            result = SourceResult(
                                content=content,
                                title=title,
                                source_name="web_search",
                                url=url,
                                relevance_score=0.7,  # Default score for web results
                                metadata={
                                    "domain": self._extract_domain(url),
                                }
                            )
                            results.append(result)
                            
                    except Exception as e:
                        logger.warning(f"[WebSearch] Error parsing doc element: {e}")
                        continue
            
            # Если не нашли через group, пробуем напрямую
            if not results:
                for doc in root.findall(".//doc"):
                    try:
                        url_elem = doc.find("url")
                        title_elem = doc.find("title")
                        passages = doc.findall(".//passage")
                        
                        url = url_elem.text if url_elem is not None else ""
                        title = self._clean_html(title_elem.text) if title_elem is not None else "Без названия"
                        
                        content_parts = []
                        for passage in passages:
                            if passage.text:
                                content_parts.append(self._clean_html(passage.text))
                        
                        content = " ".join(content_parts) if content_parts else ""
                        
                        if content or title:
                            result = SourceResult(
                                content=content,
                                title=title,
                                source_name="web_search",
                                url=url,
                                relevance_score=0.7,
                                metadata={
                                    "domain": self._extract_domain(url),
                                }
                            )
                            results.append(result)
                            
                    except Exception as e:
                        logger.warning(f"[WebSearch] Error parsing direct doc element: {e}")
                        continue
            
            logger.info(f"[WebSearch] Parsed {len(results)} results from Yandex Search API")
            
        except ET.ParseError as e:
            logger.warning(f"[WebSearch] Error parsing Yandex XML response: {e}")
        except Exception as e:
            logger.warning(f"[WebSearch] Error processing Yandex response: {e}")
        
        return results
    
    def _parse_yandex_v2_response(self, json_content: str) -> List[SourceResult]:
        """
        Parse Yandex Search API v2 JSON response
        
        Args:
            json_content: JSON response string
            
        Returns:
            List of SourceResult
        """
        results = []
        
        try:
            import json
            import base64
            
            data = json.loads(json_content)
            
            # Логируем структуру JSON для отладки
            logger.info(f"[WebSearch] JSON keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            
            # Yandex Search API v2 может возвращать rawData в Base64
            # Согласно документации: https://yandex.cloud/ru/docs/search-api
            if isinstance(data, dict) and "rawData" in data:
                # Декодируем Base64 данные
                try:
                    raw_data_b64 = data["rawData"]
                    raw_data_bytes = base64.b64decode(raw_data_b64)
                    raw_data_str = raw_data_bytes.decode('utf-8')
                    data = json.loads(raw_data_str)
                    logger.info(f"[WebSearch] Decoded rawData, new keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
                except Exception as decode_error:
                    logger.warning(f"[WebSearch] Failed to decode rawData: {decode_error}")
            
            # Yandex Search API v2 структура ответа
            # Проверяем разные возможные структуры
            items = []
            
            if isinstance(data, dict):
                # Вариант 1: результаты в поле "results" или "items"
                if "results" in data:
                    items = data["results"]
                elif "items" in data:
                    items = data["items"]
                elif "response" in data:
                    # Вложенная структура
                    response = data["response"]
                    if isinstance(response, dict):
                        if "results" in response:
                            items = response["results"]
                        elif "items" in response:
                            items = response["items"]
                        elif "groups" in response:
                            # Группированные результаты
                            for group in response["groups"]:
                                if "items" in group:
                                    items.extend(group["items"])
                elif "groups" in data:
                    # Прямые группы
                    for group in data["groups"]:
                        if "items" in group:
                            items.extend(group["items"])
                elif "web" in data:
                    # Структура с web результатами
                    web_data = data["web"]
                    if isinstance(web_data, dict):
                        if "results" in web_data:
                            items = web_data["results"]
                        elif "items" in web_data:
                            items = web_data["items"]
            
            logger.info(f"[WebSearch] Found {len(items)} items in JSON response")
            
            # Парсим каждый элемент
            for item in items:
                try:
                    if isinstance(item, dict):
                        # Извлекаем данные из элемента
                        url = item.get("url", item.get("link", ""))
                        title = item.get("title", item.get("headline", "Без названия"))
                        # Контент может быть в разных полях
                        content = item.get("snippet", item.get("description", item.get("text", "")))
                        
                        # Очищаем HTML из контента
                        if content:
                            content = self._clean_html(content)
                        
                        if content or title:
                            result = SourceResult(
                                content=content,
                                title=self._clean_html(title),
                                source_name="web_search",
                                url=url,
                                relevance_score=item.get("relevance", 0.7),
                                metadata={
                                    "domain": self._extract_domain(url),
                                }
                            )
                            results.append(result)
                            
                except Exception as e:
                    logger.warning(f"[WebSearch] Error parsing item: {e}, item: {str(item)[:200]}")
                    continue
            
            logger.info(f"[WebSearch] Parsed {len(results)} results from Yandex Search API v2")
            
        except json.JSONDecodeError as e:
            logger.warning(f"[WebSearch] Error parsing Yandex JSON response: {e}")
        except Exception as e:
            logger.warning(f"[WebSearch] Error processing Yandex v2 response: {e}")
        
        return results
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text"""
        if not text:
            return ""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        if not url:
            return ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return ""
    
    async def health_check(self) -> bool:
        """Check if web search is healthy"""
        # Basic check - just verify we're initialized
        return self._initialized
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        info = super().get_info()
        info["api_configured"] = bool(self.api_key and self.folder_id)
        return info

