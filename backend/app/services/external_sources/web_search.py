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
        # #region agent log
        import json as json_module
        import time
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                f.write(json_module.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A",
                    "location": "web_search.py:18",
                    "message": "WebSearchSource __init__ started",
                    "data": {
                        "has_YANDEX_SEARCH_API_KEY": hasattr(config, 'YANDEX_SEARCH_API_KEY'),
                        "YANDEX_SEARCH_API_KEY_value": getattr(config, 'YANDEX_SEARCH_API_KEY', None) is not None,
                        "has_YANDEX_API_KEY": hasattr(config, 'YANDEX_API_KEY'),
                        "YANDEX_API_KEY_value": bool(getattr(config, 'YANDEX_API_KEY', '')),
                        "YANDEX_FOLDER_ID": bool(getattr(config, 'YANDEX_FOLDER_ID', ''))
                    },
                    "timestamp": int(time.time() * 1000)
                }, ensure_ascii=False) + '\n')
        except:
            pass
        # #endregion
        # Используем YANDEX_API_KEY вместо YANDEX_SEARCH_API_KEY (которой нет в конфиге)
        self.api_key = getattr(config, 'YANDEX_SEARCH_API_KEY', None) or getattr(config, 'YANDEX_API_KEY', None)
        self.folder_id = config.YANDEX_FOLDER_ID
        self.base_url = "https://yandex.ru/search/xml"
        # #region agent log
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                f.write(json_module.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A",
                    "location": "web_search.py:22",
                    "message": "WebSearchSource __init__ completed",
                    "data": {
                        "api_key_set": self.api_key is not None,
                        "folder_id_set": bool(self.folder_id),
                        "api_key_length": len(self.api_key) if self.api_key else 0
                    },
                    "timestamp": int(time.time() * 1000)
                }, ensure_ascii=False) + '\n')
        except:
            pass
        # #endregion
    
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
            # #region agent log
            import json as json_module
            import time
            try:
                with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                    f.write(json_module.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "web_search.py:63",
                        "message": "Checking API credentials before search",
                        "data": {
                            "has_api_key": self.api_key is not None,
                            "has_folder_id": bool(self.folder_id),
                            "api_key_length": len(self.api_key) if self.api_key else 0,
                            "folder_id_length": len(self.folder_id) if self.folder_id else 0,
                            "query": enhanced_query[:100]
                        },
                        "timestamp": int(time.time() * 1000)
                    }, ensure_ascii=False) + '\n')
            except:
                pass
            # #endregion
            if self.api_key and self.folder_id:
                # #region agent log
                try:
                    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                        f.write(json_module.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "C",
                            "location": "web_search.py:66",
                            "message": "Calling Yandex Search API",
                            "data": {"query": enhanced_query[:100], "max_results": max_results},
                            "timestamp": int(time.time() * 1000)
                        }, ensure_ascii=False) + '\n')
                except:
                    pass
                # #endregion
                return await self._search_yandex_api(enhanced_query, max_results, filters)
            else:
                # Fallback: return empty results with a note
                # #region agent log
                try:
                    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
                        f.write(json_module.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "B",
                            "location": "web_search.py:70",
                            "message": "No API configured - returning empty results",
                            "data": {
                                "api_key_missing": self.api_key is None,
                                "folder_id_missing": not bool(self.folder_id)
                            },
                            "timestamp": int(time.time() * 1000)
                        }, ensure_ascii=False) + '\n')
                except:
                    pass
                # #endregion
                logger.warning("Web search: No API configured, returning empty results")
                return []
        except Exception as e:
            logger.error(f"Web search error: {e}", exc_info=True)
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
        Search using Yandex Search API
        
        Args:
            query: Search query
            max_results: Maximum results
            filters: Optional filters
            
        Returns:
            List of SourceResult
        """
        # Build request parameters for Yandex Search API
        params = {
            "folderid": self.folder_id,
            "apikey": self.api_key,
            "query": query,
            "l10n": "ru",
            "sortby": "rlv",  # Sort by relevance
            "filter": "moderate",
            "maxpassages": "3",
            "groupby": f"attr=d.mode=deep.groups-on-page={max_results}.docs-in-group=1",
        }
        
        # Add site restriction if specified
        if filters and filters.get("sites"):
            sites = filters["sites"]
            if isinstance(sites, list):
                site_query = " | ".join(f"site:{s}" for s in sites)
                params["query"] = f"({params['query']}) ({site_query})"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.base_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Yandex Search API error: {response.status}")
                        return []
                    
                    # Parse XML response
                    content = await response.text()
                    return self._parse_yandex_response(content)
                    
        except aiohttp.ClientError as e:
            logger.error(f"Yandex Search API connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"Yandex Search API error: {e}", exc_info=True)
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
            root = ET.fromstring(xml_content)
            
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
                        logger.warning(f"Error parsing doc element: {e}")
                        continue
            
            logger.info(f"Parsed {len(results)} results from Yandex Search API")
            
        except ET.ParseError as e:
            logger.error(f"Error parsing Yandex XML response: {e}")
        except Exception as e:
            logger.error(f"Error processing Yandex response: {e}", exc_info=True)
        
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

