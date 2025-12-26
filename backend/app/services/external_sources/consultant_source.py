"""Consultant Plus legal database source"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging

logger = logging.getLogger(__name__)


class ConsultantPlusSource(BaseSource):
    """
    Source for searching Consultant Plus legal database.
    
    Consultant Plus (КонсультантПлюс) is the leading Russian legal
    information system containing legislation, court decisions,
    regulatory documents, and legal analytics.
    
    Note: This implementation uses a placeholder API.
    For production, you need to obtain API access from Consultant Plus.
    """
    
    def __init__(self):
        super().__init__(name="consultant_plus", enabled=True)
        # Consultant Plus API credentials (to be configured)
        self.api_key = getattr(config, 'CONSULTANT_API_KEY', None)
        self.api_url = getattr(config, 'CONSULTANT_API_URL', 'https://api.consultant.ru/v1')
        
    async def initialize(self) -> bool:
        """Initialize Consultant Plus source"""
        if self.api_key:
            self._initialized = True
            logger.info("Consultant Plus source initialized with API key")
        else:
            # Disable if not configured
            self.enabled = False
            self._initialized = False
            logger.info("Consultant Plus source: API key not configured, source disabled")
        return self._initialized
    
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search Consultant Plus legal database
        
        Args:
            query: Search query
            max_results: Maximum number of results
            filters: Optional filters:
                - doc_type: "npa" (normative acts), "court", "article", "form"
                - date_from: Start date (YYYY-MM-DD)
                - date_to: End date (YYYY-MM-DD)
                - status: "active", "inactive", "all"
                - region: Region code
            
        Returns:
            List of SourceResult
        """
        if not self.api_key:
            logger.warning("Consultant Plus source: API key not configured")
            return []
        
        if not query.strip():
            return []
        
        try:
            return await self._search_consultant_api(query, max_results, filters)
        except Exception as e:
            logger.error(f"Consultant Plus search error: {e}", exc_info=True)
            return []
    
    async def _search_consultant_api(
        self,
        query: str,
        max_results: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search using Consultant Plus API
        
        Args:
            query: Search query
            max_results: Maximum results
            filters: Optional filters
            
        Returns:
            List of SourceResult
        """
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        # Build request body
        request_body = {
            "text": query,
            "count": max_results,
            "skip": 0,
            "sort": "relevance",  # or "date"
        }
        
        # Add filters
        if filters:
            filter_obj = {}
            if filters.get("doc_type"):
                filter_obj["type"] = filters["doc_type"]
            if filters.get("date_from"):
                filter_obj["dateFrom"] = filters["date_from"]
            if filters.get("date_to"):
                filter_obj["dateTo"] = filters["date_to"]
            if filters.get("status"):
                filter_obj["status"] = filters["status"]
            if filters.get("region"):
                filter_obj["region"] = filters["region"]
            
            if filter_obj:
                request_body["filters"] = filter_obj
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/documents/search",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 401:
                        logger.error("Consultant Plus API: Unauthorized - check API key")
                        return []
                    elif response.status == 403:
                        logger.error("Consultant Plus API: Forbidden - check permissions")
                        return []
                    elif response.status != 200:
                        logger.error(f"Consultant Plus API error: {response.status}")
                        return []
                    
                    data = await response.json()
                    return self._parse_consultant_response(data)
                    
        except aiohttp.ClientError as e:
            logger.error(f"Consultant Plus API connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"Consultant Plus API error: {e}", exc_info=True)
            return []
    
    def _parse_consultant_response(self, data: Dict[str, Any]) -> List[SourceResult]:
        """
        Parse Consultant Plus API response
        
        Args:
            data: API response data
            
        Returns:
            List of SourceResult
        """
        results = []
        
        documents = data.get("documents", data.get("items", []))
        
        for doc in documents:
            try:
                # Map document types to readable names
                doc_type = doc.get("type", "document")
                doc_type_names = {
                    "npa": "Нормативный правовой акт",
                    "federal_law": "Федеральный закон",
                    "codex": "Кодекс",
                    "decree": "Указ Президента",
                    "government_resolution": "Постановление Правительства",
                    "ministry_order": "Приказ министерства",
                    "court": "Судебный акт",
                    "court_decision": "Решение суда",
                    "arbitration": "Арбитражное решение",
                    "article": "Статья",
                    "consultation": "Консультация",
                    "form": "Форма документа",
                }
                doc_type_name = doc_type_names.get(doc_type, "Документ")
                
                # Get status badge
                status = doc.get("status", "unknown")
                status_names = {
                    "active": "Действующий",
                    "inactive": "Утратил силу",
                    "pending": "Не вступил в силу",
                }
                status_name = status_names.get(status, "")
                
                result = SourceResult(
                    content=doc.get("excerpt", doc.get("snippet", "")),
                    title=doc.get("name", doc.get("title", "Без названия")),
                    source_name="consultant_plus",
                    url=doc.get("link", doc.get("url")),
                    relevance_score=doc.get("score", doc.get("relevance", 0.5)),
                    metadata={
                        "doc_type": doc_type,
                        "doc_type_name": doc_type_name,
                        "doc_id": doc.get("id"),
                        "doc_number": doc.get("number"),
                        "doc_date": doc.get("date"),
                        "status": status,
                        "status_name": status_name,
                        "issuing_authority": doc.get("authority", doc.get("publisher")),
                        "effective_date": doc.get("effectiveDate"),
                    }
                )
                results.append(result)
                
            except Exception as e:
                logger.warning(f"Error parsing Consultant Plus item: {e}")
                continue
        
        logger.info(f"Parsed {len(results)} results from Consultant Plus API")
        return results
    
    async def health_check(self) -> bool:
        """Check if Consultant Plus API is healthy"""
        if not self.api_key:
            return False
        
        try:
            headers = {
                "X-API-Key": self.api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_url}/status",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
                    
        except Exception as e:
            logger.warning(f"Consultant Plus health check failed: {e}")
            return False
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        info = super().get_info()
        info["api_configured"] = bool(self.api_key)
        info["description"] = "КонсультантПлюс - справочная правовая система"
        return info

