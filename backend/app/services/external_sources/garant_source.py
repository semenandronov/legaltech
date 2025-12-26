"""Garant legal database source"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging

logger = logging.getLogger(__name__)


class GarantSource(BaseSource):
    """
    Source for searching Garant legal database.
    
    Garant is one of the major Russian legal information systems
    containing laws, regulations, court decisions, and legal articles.
    
    Note: This implementation uses a mock/placeholder API.
    For production, you need to obtain API access from Garant.
    """
    
    def __init__(self):
        super().__init__(name="garant", enabled=True)
        # Garant API credentials (to be configured)
        self.api_key = getattr(config, 'GARANT_API_KEY', None)
        self.api_url = getattr(config, 'GARANT_API_URL', 'https://api.garant.ru/v1')
        
    async def initialize(self) -> bool:
        """Initialize Garant source"""
        if self.api_key:
            self._initialized = True
            logger.info("Garant source initialized with API key")
        else:
            # Disable if not configured
            self.enabled = False
            self._initialized = False
            logger.info("Garant source: API key not configured, source disabled")
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
        
        # Build request body
        request_body = {
            "query": query,
            "limit": max_results,
            "offset": 0,
        }
        
        # Add filters
        if filters:
            if filters.get("doc_type"):
                request_body["doc_type"] = filters["doc_type"]
            if filters.get("date_from"):
                request_body["date_from"] = filters["date_from"]
            if filters.get("date_to"):
                request_body["date_to"] = filters["date_to"]
            if filters.get("jurisdiction"):
                request_body["jurisdiction"] = filters["jurisdiction"]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/search",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 401:
                        logger.error("Garant API: Unauthorized - check API key")
                        return []
                    elif response.status == 403:
                        logger.error("Garant API: Forbidden - check permissions")
                        return []
                    elif response.status != 200:
                        logger.error(f"Garant API error: {response.status}")
                        return []
                    
                    data = await response.json()
                    return self._parse_garant_response(data)
                    
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
        
        items = data.get("items", [])
        
        for item in items:
            try:
                # Map Garant document types to readable names
                doc_type = item.get("type", "document")
                doc_type_names = {
                    "law": "Закон",
                    "decree": "Указ",
                    "resolution": "Постановление",
                    "order": "Приказ",
                    "court_decision": "Судебное решение",
                    "article": "Статья",
                    "commentary": "Комментарий",
                }
                doc_type_name = doc_type_names.get(doc_type, "Документ")
                
                result = SourceResult(
                    content=item.get("snippet", item.get("text", "")),
                    title=item.get("title", "Без названия"),
                    source_name="garant",
                    url=item.get("url"),
                    relevance_score=item.get("relevance", 0.5),
                    metadata={
                        "doc_type": doc_type,
                        "doc_type_name": doc_type_name,
                        "doc_id": item.get("id"),
                        "doc_number": item.get("number"),
                        "doc_date": item.get("date"),
                        "issuing_authority": item.get("authority"),
                    }
                )
                results.append(result)
                
            except Exception as e:
                logger.warning(f"Error parsing Garant item: {e}")
                continue
        
        logger.info(f"Parsed {len(results)} results from Garant API")
        return results
    
    async def health_check(self) -> bool:
        """Check if Garant API is healthy"""
        if not self.api_key:
            return False
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_url}/health",
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
        info["description"] = "Гарант - правовая информационная система"
        return info

