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
        # В документации примеры показывают пробел после команды: MorphoText (налог)
        garant_query = query
        
        # Если есть фильтры, добавляем их через язык запросов ГАРАНТ
        # Согласно документации API v2.1.0, используем команды и операторы
        filter_parts = []
        text_parts = []
        
        if filters:
            # Фильтр по типу документа
            if filters.get("doc_type"):
                doc_type = filters["doc_type"]
                # Маппинг наших типов на типы ГАРАНТ согласно документации
                if doc_type == "court_decision":
                    # Для судебных решений используем несколько типов через ИЛИ для максимального охвата
                    # Согласно документации: Type(Решение) | Type(Постановление) | Type(Определение)
                    filter_parts.append("BOOL(Type(Решение) | Type(Постановление) | Type(Определение) | Type(Приговор))")
                    logger.info("Applied court decision filter: multiple types with OR operator")
                else:
                    type_mapping = {
                        "law": "Акт",
                        "article": "Статья",
                        "commentary": "Комментарий"
                    }
                    garant_type = type_mapping.get(doc_type, doc_type)
                    filter_parts.append(f"Type({garant_type})")
                    logger.info(f"Applied doc_type filter: Type({garant_type})")
            
            # Фильтр по дате документа (Date)
            if filters.get("date_from") or filters.get("date_to"):
                date_from = filters.get("date_from", "")
                date_to = filters.get("date_to", "")
                # Преобразуем формат даты из YYYY-MM-DD в DD.MM.YYYY для ГАРАНТ
                if date_from:
                    try:
                        from datetime import datetime
                        d = datetime.strptime(date_from, "%Y-%m-%d")
                        date_from = d.strftime("%d.%m.%Y")
                    except:
                        pass
                if date_to:
                    try:
                        from datetime import datetime
                        d = datetime.strptime(date_to, "%Y-%m-%d")
                        date_to = d.strftime("%d.%m.%Y")
                    except:
                        pass
                filter_parts.append(f"Date({date_from};{date_to})")
                logger.info(f"Applied date filter: Date({date_from};{date_to})")
            
            # Фильтр по дате регистрации в Минюсте (RDate)
            if filters.get("rdate_from") or filters.get("rdate_to"):
                rdate_from = filters.get("rdate_from", "")
                rdate_to = filters.get("rdate_to", "")
                if rdate_from:
                    try:
                        from datetime import datetime
                        d = datetime.strptime(rdate_from, "%Y-%m-%d")
                        rdate_from = d.strftime("%d.%m.%Y")
                    except:
                        pass
                if rdate_to:
                    try:
                        from datetime import datetime
                        d = datetime.strptime(rdate_to, "%Y-%m-%d")
                        rdate_to = d.strftime("%d.%m.%Y")
                    except:
                        pass
                filter_parts.append(f"RDate({rdate_from};{rdate_to})")
            
            # Фильтр по органу, принявшему документ (Adopted)
            if filters.get("adopted_by"):
                adopted_by = filters.get("adopted_by")
                filter_parts.append(f"Adopted({adopted_by})")
            
            # Фильтр по номеру документа (Number)
            if filters.get("doc_number"):
                doc_number = filters.get("doc_number")
                filter_parts.append(f"Number({doc_number})")
        
        # Формируем основной текстовый запрос
        # Если запрос уже использует язык ГАРАНТ, используем его как есть
        if use_query_language:
            text_parts.append(query.strip())
        elif query.strip():
            # Для обычных текстовых запросов используем MorphoText для поиска по словам
            # Согласно документации: MorphoText (текст) - пробел после команды
            text_parts.append(f"MorphoText ({query.strip()})")
            use_query_language = True
        
        # Объединяем все части запроса
        # Если есть фильтры, объединяем через оператор И (&)
        if filter_parts and text_parts:
            garant_query = " & ".join(text_parts + filter_parts)
        elif filter_parts:
            # Только фильтры без текста
            garant_query = " & ".join(filter_parts)
            use_query_language = True
        elif text_parts:
            # Только текст
            garant_query = text_parts[0]
        else:
            # Fallback
            garant_query = query.strip()
            use_query_language = False
        
        logger.info(f"Final Garant query: '{garant_query}', isQuery={use_query_language}")
        
        # Согласно документации API v2.1.0, результаты приходят постранично
        # Нужно делать несколько запросов если max_results больше чем на одной странице
        # Обычно на странице 10-20 результатов, будем запрашивать по 20 на страницу
        results_per_page = 20
        all_results = []
        page = 1
        max_pages = (max_results + results_per_page - 1) // results_per_page  # Округление вверх
        
        logger.info(f"Garant API: requesting up to {max_results} results, {max_pages} pages")
        
        try:
            async with aiohttp.ClientSession() as session:
                while page <= max_pages and len(all_results) < max_results:
                    request_body = {
                        "text": garant_query,
                        "isQuery": use_query_language,
                        "env": "internet",
                        "sort": filters.get("sort", 0) if filters else 0,  # 0 - по релевантности, 1 - по дате
                        "sortOrder": filters.get("sort_order", 0) if filters else 0,  # 0 - по возрастанию, 1 - по убыванию
                        "page": page,
                    }
                    
                    logger.info(f"Garant API request page {page}: text='{garant_query}', isQuery={use_query_language}, URL={self.api_url}/search")
                    
                    async with session.post(
                        f"{self.api_url}/search",
                        json=request_body,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        response_status = response.status
                        response_text = await response.text()
                        
                        logger.info(f"Garant API response page {page}: status={response_status}, response_length={len(response_text)}")
                        
                        if response_status == 401:
                            logger.error(f"Garant API: Unauthorized - check API key. Response: {response_text[:200]}")
                            break
                        elif response_status == 403:
                            logger.error(f"Garant API: Forbidden - check permissions. Response: {response_text[:200]}")
                            break
                        elif response_status != 200:
                            logger.error(f"Garant API error: status={response_status}, response={response_text[:500]}")
                            break
                        
                        try:
                            import json as json_module
                            data = json_module.loads(response_text)
                            
                            # Парсим результаты со страницы
                            page_results = self._parse_garant_response(data)
                            all_results.extend(page_results)
                            
                            # Проверяем, есть ли еще страницы
                            total = data.get("totalDocs", 0) or data.get("total", 0)
                            items_count = len(data.get("documents", []) or data.get("items", []))
                            
                            logger.info(f"Garant API page {page}: got {items_count} items, total={total}, collected={len(all_results)}")
                            
                            # Если на странице меньше результатов чем ожидалось, значит это последняя страница
                            if items_count < results_per_page:
                                break
                            
                            # Если уже собрали достаточно результатов
                            if len(all_results) >= max_results:
                                break
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"Garant API: Failed to parse JSON response. Status: {response.status}, Response: {response_text[:500]}, Error: {e}")
                            break
                    
                    page += 1
                
                # Ограничиваем результаты до max_results
                return all_results[:max_results]
                    
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
        # API возвращает документы в поле "documents", а не "items"
        items = data.get("documents", []) or data.get("items", [])
        total = data.get("totalDocs", 0) or data.get("total", 0) or len(items)
        
        logger.info(f"Garant API returned {len(items)} items (total: {total})")
        
        # Логируем первые несколько результатов для отладки
        if items:
            logger.info(f"First result sample: title='{items[0].get('title', 'N/A')[:100]}', type='{items[0].get('type', 'N/A')}', doc_id='{items[0].get('topic', 'N/A')}'")
        
        for item in items:
            try:
                # Parse API v2.1.0 response structure
                # В API v2 поле с ID документа называется "topic" согласно документации
                doc_id = item.get("topic") or item.get("id") or item.get("docId") or item.get("documentId")
                title = item.get("title") or item.get("name") or "Без названия"
                
                # Получаем содержимое - приоритет: snippet, text, preview
                snippet = item.get("snippet") or item.get("text") or item.get("preview") or ""
                
                # Если snippet короткий, пытаемся получить больше текста
                if len(snippet) < 100 and item.get("text"):
                    snippet = item.get("text")
                
                # URL документа
                url = item.get("url")
                if url and url.startswith("/#/"):
                    # Если URL относительный, добавляем базовый домен
                    url = f"https://internet.garant.ru{url}"
                elif not url and doc_id:
                    # Формируем URL если его нет - согласно документации формат: /#/document/{topic}
                    url = f"https://internet.garant.ru/#/document/{doc_id}"
                
                # Метаданные - извлекаем все доступные поля
                metadata = {
                    "doc_id": doc_id,
                    "doc_number": item.get("number"),
                    "doc_date": item.get("date"),
                    "doc_type": item.get("type"),
                    "issuing_authority": item.get("authority") or item.get("adoptedBy"),
                    "sort_date": item.get("sortDate"),  # Дата добавления в систему
                    "changed_date": item.get("changedDate"),  # Дата изменения
                }
                
                # Релевантность - нормализуем в диапазон 0-1
                relevance = item.get("relevance") or item.get("score") or 0.5
                if isinstance(relevance, (int, float)):
                    # Если релевантность в другом формате, нормализуем
                    if relevance > 1.0:
                        relevance = min(relevance / 100.0, 1.0)
                    relevance = max(0.0, min(1.0, float(relevance)))
                else:
                    relevance = 0.5
                
                # Если snippet пустой, используем title как content
                if not snippet and title:
                    snippet = title
                
                result = SourceResult(
                    content=snippet,
                    title=title,
                    source_name="garant",
                    url=url,
                    relevance_score=relevance,
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
                "text": "MorphoText (тест)",  # Согласно документации: пробел после команды
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

