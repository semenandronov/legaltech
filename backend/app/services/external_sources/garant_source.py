"""Garant legal database source"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging
import json

logger = logging.getLogger(__name__)


class GarantSource(BaseSource):
    """
    Source for searching Garant legal database.
    
    Garant is one of the major Russian legal information systems
    containing laws, regulations, court decisions, and legal articles.
    
    Implements Garant API v2.1.0
    Documentation: https://api.garant.ru
    """
    
    def __init__(self):
        super().__init__(name="garant", enabled=True)
        # Garant API credentials (to be configured)
        self.api_key = getattr(config, 'GARANT_API_KEY', None)
        self.api_url = getattr(config, 'GARANT_API_URL', 'https://api.garant.ru/v2')
        
        # Normalize API key - remove "Bearer " prefix if present (we add it in headers)
        if self.api_key:
            self.api_key = str(self.api_key).strip()
            if self.api_key.startswith("Bearer "):
                self.api_key = self.api_key[7:].strip()
            # Log key status (but not the actual key value for security)
            logger.info(f"GarantSource initialized: API key present (length: {len(self.api_key)}), URL: {self.api_url}")
        else:
            logger.warning("GarantSource initialized: GARANT_API_KEY not found in config")
        
    async def initialize(self) -> bool:
        """Initialize Garant source"""
        if self.api_key and len(self.api_key) > 0:
            self._initialized = True
            self.enabled = True
            logger.info("Garant source initialized with API key")
        else:
            # Disable if not configured
            self.enabled = False
            self._initialized = False
            logger.warning("Garant source: API key not configured or empty, source disabled")
        return self._initialized
    
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search Garant legal database
        
        Args:
            query: Search query
            max_results: Maximum number of results
            filters: Optional filters:
                - doc_type: "law", "court_decision", "article", "commentary"
                - date_from: Start date (YYYY-MM-DD)
                - date_to: End date (YYYY-MM-DD)
                - jurisdiction: "federal", "regional"
            
        Returns:
            List of SourceResult
        """
        if not self.api_key:
            logger.warning("Garant source: API key not configured")
            return []
        
        if not query.strip():
            return []
        
        try:
            return await self._search_garant_api(query, max_results, filters)
        except Exception as e:
            logger.error(f"Garant search error: {e}", exc_info=True)
            return []
    
    async def _search_garant_api(
        self,
        query: str,
        max_results: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search using Garant API
        
        Args:
            query: Search query
            max_results: Maximum results
            filters: Optional filters
            
        Returns:
            List of SourceResult
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        # Determine if query uses Garant query language
        use_query_language = False
        if filters and filters.get("use_query_language"):
            use_query_language = True
        else:
            # Auto-detect if query contains Garant commands
            garant_commands = ["MorphoText", "Type", "Date", "RDate", "MorphoName", 
                             "Adopted", "Number", "Correspondents", "Respondents", 
                             "SortDate", "Changed"]
            use_query_language = any(query.startswith(cmd) for cmd in garant_commands)
        
        # Build request body according to API v2.1.0
        # Для обычных текстовых запросов автоматически используем MorphoText()
        garant_query = query
        if not use_query_language and query.strip():
            # Обертываем обычный текст в MorphoText для поиска по словам
            garant_query = f"MorphoText({query})"
            use_query_language = True
        
        request_body = {
            "text": garant_query,
            "isQuery": use_query_language,
            "env": "internet",
            "sort": filters.get("sort", 0) if filters else 0,  # 0 - по релевантности, 1 - по дате
            "sortOrder": filters.get("sort_order", 0) if filters else 0,  # 0 - по возрастанию, 1 - по убыванию
            "page": 1,
        }
        
        logger.info(f"Garant API request: text='{garant_query}', isQuery={use_query_language}, URL={self.api_url}/search")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/search",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 401:
                        logger.error(f"Garant API: Unauthorized - check API key. Response: {response_text[:200]}")
                        return []
                    elif response.status == 403:
                        logger.error(f"Garant API: Forbidden - check permissions. Response: {response_text[:200]}")
                        return []
                    elif response.status != 200:
                        logger.error(f"Garant API error: status={response.status}, response={response_text[:500]}")
                        return []
                    
                    try:
                        data = await response.json()
                        logger.info(f"Garant API response: status={response.status}, keys={list(data.keys()) if isinstance(data, dict) else 'not_dict'}")
                        return self._parse_garant_response(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Garant API: Failed to parse JSON response. Status: {response.status}, Response: {response_text[:500]}, Error: {e}")
                        return []
                    
        except aiohttp.ClientError as e:
            logger.error(f"Garant API connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"Garant API error: {e}", exc_info=True)
            return []
    
    def _parse_garant_response(self, data: Dict[str, Any]) -> List[SourceResult]:
        """
        Parse Garant API response
        
        Args:
            data: API response data
            
        Returns:
            List of SourceResult
        """
        results = []
        
        # Parse API v2.1.0 response structure
        items = data.get("items", [])
        total = data.get("total", 0)
        
        logger.info(f"Garant API returned {len(items)} items (total: {total})")
        
        for item in items:
            try:
                # Parse API v2.1.0 response structure
                doc_id = item.get("id") or item.get("docId") or item.get("documentId")
                title = item.get("title") or item.get("name") or "Без названия"
                snippet = item.get("snippet") or item.get("text") or item.get("preview") or ""
                
                # URL документа
                url = item.get("url")
                if not url and doc_id:
                    # Формируем URL если его нет
                    url = f"https://internet.garant.ru/#/document/{doc_id}"
                
                # Метаданные
                metadata = {
                    "doc_id": doc_id,
                    "doc_number": item.get("number"),
                    "doc_date": item.get("date"),
                    "doc_type": item.get("type"),
                    "issuing_authority": item.get("authority") or item.get("adoptedBy"),
                }
                
                # Релевантность (если есть)
                relevance = item.get("relevance") or item.get("score") or 0.5
                
                result = SourceResult(
                    content=snippet,
                    title=title,
                    source_name="garant",
                    url=url,
                    relevance_score=float(relevance) if isinstance(relevance, (int, float)) else 0.5,
                    metadata=metadata
                )
                results.append(result)
                
            except Exception as e:
                logger.warning(f"Error parsing Garant item: {e}, item: {item}")
                continue
        
        logger.info(f"Parsed {len(results)} results from Garant API")
        return results
    
    async def health_check(self) -> bool:
        """Check if Garant API is healthy"""
        if not self.api_key:
            return False
        
        try:
            # Простой поиск для проверки доступности API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            
            request_body = {
                "text": "MorphoText(тест)",
                "isQuery": True,
                "env": "internet",
                "sort": 0,
                "sortOrder": 0,
                "page": 1,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/search",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
                    
        except Exception as e:
            logger.warning(f"Garant health check failed: {e}")
            return False
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        info = super().get_info()
        info["api_configured"] = bool(self.api_key)
        info["api_version"] = "2.1.0"
        info["description"] = "Гарант - правовая информационная система"
        return info

