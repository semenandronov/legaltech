"""Garant legal database source"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from app.config import config
import aiohttp
import logging
import json

logger = logging.getLogger(__name__)

# Константы для таймаутов с учетом ограничений Render
# Render имеет максимальный timeout ~300 секунд для HTTP запросов
# Используем консервативные значения для безопасности
GARANT_API_TIMEOUT_SEARCH = 25  # секунд для поиска
GARANT_API_TIMEOUT_EXPORT = 25  # секунд для экспорта документов
GARANT_API_TIMEOUT_LINKS = 50   # секунд для простановки ссылок (может быть долгим)
GARANT_API_TIMEOUT_INFO = 25   # секунд для получения информации о документе

# Ограничения для Render (безопасные значения)
MAX_TEXT_SIZE_FOR_LINKS = 10 * 1024 * 1024  # 10MB (API лимит 20MB, но используем меньше для безопасности)
MAX_FULL_TEXT_DOCS = 3  # Максимум документов для получения полного текста за раз
MAX_CONTENT_LENGTH = 5000  # Максимальная длина контента документа (символов)


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
        filters: Optional[Dict[str, Any]] = None,
        get_full_text: bool = False
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
            get_full_text: Если True, получает полный текст для каждого документа
            
        Returns:
            List of SourceResult
        """
        if not self.api_key:
            logger.warning("Garant source: API key not configured")
            return []
        
        if not query.strip():
            return []
        
        try:
            results = await self._search_garant_api(query, max_results, filters)
            
            # Если нужно получить полный текст
            if get_full_text:
                for result in results:
                    doc_id = result.metadata.get("doc_id")
                    if doc_id:
                        try:
                            full_text = await self.get_document_full_text(doc_id, format="html")
                            if full_text:
                                # Парсим HTML и извлекаем текст
                                try:
                                    from bs4 import BeautifulSoup
                                    soup = BeautifulSoup(full_text, 'html.parser')
                                    text_content = soup.get_text(separator='\n', strip=True)
                                    result.content = text_content[:5000]  # Ограничиваем размер
                                    logger.info(f"Got full text for document {doc_id}, length: {len(text_content)}")
                                except ImportError:
                                    # Если BeautifulSoup не установлен, используем простую очистку HTML
                                    import re
                                    text_content = re.sub(r'<[^>]+>', '', full_text)
                                    result.content = text_content[:5000]
                                    logger.info(f"Got full text for document {doc_id} (without BeautifulSoup)")
                        except Exception as e:
                            logger.warning(f"Failed to get full text for document {doc_id}: {e}")
            
            return results
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
        
        # ВСЕГДА используем поиск по смыслу (естественный язык)
        # Гарант сам найдет релевантные документы по смыслу запроса
        use_query_language = False
        
        # Используем запрос как есть для семантического поиска
        garant_query = query.strip() if query.strip() else ""
        
        # Если есть фильтры, их можно добавить, но основной поиск - по смыслу
        # Фильтры пока отключаем, чтобы не мешать семантическому поиску
        # В будущем можно добавить фильтрацию результатов после поиска
        if filters:
            logger.info(f"Filters provided but using semantic search: {filters}")
            # Фильтры можно применить к результатам после поиска, если нужно
        
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
                    
                    logger.info(f"[Garant API] Request page {page}: text='{garant_query[:100]}...', isQuery={use_query_language}, max_results={max_results}")
                    logger.debug(f"[Garant API] Full request: {request_body}")
                    
                    start_time = __import__('time').time()
                    
                    async with session.post(
                        f"{self.api_url}/search",
                        json=request_body,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=GARANT_API_TIMEOUT_SEARCH)
                    ) as response:
                        elapsed_time = __import__('time').time() - start_time
                        response_status = response.status
                        response_text = await response.text()
                        
                        logger.info(f"[Garant API] Response page {page}: status={response_status}, length={len(response_text)} chars, elapsed={elapsed_time:.2f}s")
                        
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
                # Сохраняем и doc_id и topic для совместимости
                metadata = {
                    "doc_id": doc_id,
                    "topic": doc_id,  # topic - это то же самое, что doc_id в API v2.1.0
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
    
    async def get_document_full_text(
        self,
        doc_id: str,
        format: str = "html"  # html, rtf, pdf, odt
    ) -> Optional[str]:
        """
        Получить полный текст документа из ГАРАНТ
        
        Args:
            doc_id: ID документа (topic)
            format: Формат экспорта (html, rtf, pdf, odt)
            
        Returns:
            Полный текст документа или None
        """
        if not self.api_key:
            logger.warning("[Garant API] API key not configured, cannot get document full text")
            return None
        
        if not doc_id:
            logger.warning("[Garant API] Document ID is empty")
            return None
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json" if format == "html" else "application/octet-stream",
        }
        
        # Согласно документации API v2.1.0
        # URL для экспорта: /v2/export/{format}
        endpoint_map = {
            "html": "/export/html",
            "rtf": "/export/rtf",
            "pdf": "/export/pdf",
            "odt": "/export/odt"
        }
        
        endpoint = endpoint_map.get(format.lower(), "/export/html")
        full_url = f"{self.api_url}{endpoint}"
        
        timeout_seconds = GARANT_API_TIMEOUT_EXPORT
        
        try:
            async with aiohttp.ClientSession() as session:
                # Убеждаемся, что doc_id - строка (API ожидает строку согласно документации)
                doc_id_str = str(doc_id).strip()
                
                request_body = {
                    "topic": doc_id_str,
                    "env": "internet"
                }
                
                logger.info(f"[Garant API] Requesting full text for document {doc_id_str} (type: {type(doc_id).__name__}) in format {format}")
                logger.debug(f"[Garant API] Endpoint: {full_url}, Request body: {request_body}")
                
                start_time = __import__('time').time()
                
                async with session.post(
                    full_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                ) as response:
                    elapsed_time = __import__('time').time() - start_time
                    
                    logger.info(f"[Garant API] Export response: status={response.status}, elapsed={elapsed_time:.2f}s")
                    
                    if response.status == 200:
                        try:
                            if format == "html":
                                content = await response.text()
                                logger.info(f"[Garant API] Successfully got HTML content, length: {len(content)} chars")
                                return content
                            else:
                                # Для бинарных форматов возвращаем base64
                                import base64
                                content = await response.read()
                                encoded = base64.b64encode(content).decode('utf-8')
                                logger.info(f"[Garant API] Successfully got {format} content, size: {len(content)} bytes, encoded: {len(encoded)} chars")
                                return encoded
                        except Exception as parse_error:
                            logger.error(f"[Garant API] Error parsing response content: {parse_error}", exc_info=True)
                            return None
                    elif response.status == 401:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Unauthorized (401) - check API key. Response: {error_text[:200]}")
                        return None
                    elif response.status == 403:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Forbidden (403) - check permissions or API limits. Response: {error_text[:200]}")
                        return None
                    elif response.status == 404:
                        error_text = await response.text()
                        logger.warning(f"[Garant API] Document not found (404) for doc_id={doc_id}. Response: {error_text[:200]}")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Export error: status={response.status}, doc_id={doc_id}, format={format}, response={error_text[:500]}")
                        return None
        except aiohttp.ClientTimeout:
            logger.error(f"[Garant API] Timeout ({timeout_seconds}s) while getting document {doc_id} in format {format}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"[Garant API] Client error getting document full text: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"[Garant API] Unexpected error getting document full text: {e}", exc_info=True)
            return None
    
    async def get_document_info(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о документе из ГАРАНТ
        
        Args:
            doc_id: ID документа (topic)
            
        Returns:
            Словарь с информацией о документе или None
        """
        if not self.api_key:
            logger.warning("[Garant API] API key not configured, cannot get document info")
            return None
        
        if not doc_id:
            logger.warning("[Garant API] Document ID is empty")
            return None
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        full_url = f"{self.api_url}/document/info"
        timeout_seconds = GARANT_API_TIMEOUT_INFO
        
        try:
            async with aiohttp.ClientSession() as session:
                request_body = {
                    "topic": doc_id,
                    "env": "internet"
                }
                
                logger.info(f"[Garant API] Requesting document info for {doc_id}")
                logger.debug(f"[Garant API] Endpoint: {full_url}, Request body: {request_body}")
                
                start_time = __import__('time').time()
                
                async with session.post(
                    full_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                ) as response:
                    elapsed_time = __import__('time').time() - start_time
                    
                    logger.info(f"[Garant API] Document info response: status={response.status}, elapsed={elapsed_time:.2f}s")
                    
                    if response.status == 200:
                        try:
                            data = await response.json()
                            logger.info(f"[Garant API] Successfully got document info, keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                            return data
                        except Exception as parse_error:
                            logger.error(f"[Garant API] Error parsing JSON response: {parse_error}", exc_info=True)
                            return None
                    elif response.status == 401:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Unauthorized (401) - check API key. Response: {error_text[:200]}")
                        return None
                    elif response.status == 403:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Forbidden (403) - check permissions. Response: {error_text[:200]}")
                        return None
                    elif response.status == 404:
                        error_text = await response.text()
                        logger.warning(f"[Garant API] Document not found (404) for doc_id={doc_id}. Response: {error_text[:200]}")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Document info error: status={response.status}, doc_id={doc_id}, response={error_text[:500]}")
                        return None
        except aiohttp.ClientTimeout:
            logger.error(f"[Garant API] Timeout ({timeout_seconds}s) while getting document info for {doc_id}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"[Garant API] Client error getting document info: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"[Garant API] Unexpected error getting document info: {e}", exc_info=True)
            return None
    
    async def insert_links(self, text: str) -> Optional[str]:
        """
        Простановка ссылок на документы ГАРАНТ в тексте
        
        Согласно документации API v2.1.0, метод автоматически находит
        упоминания документов в тексте и вставляет ссылки на них.
        
        Args:
            text: Текст для обработки (максимум 20Мб)
            
        Returns:
            Текст с проставленными ссылками или None
        """
        if not self.api_key:
            logger.warning("[Garant API] API key not configured, cannot insert links")
            return None
        
        if not text or not text.strip():
            logger.warning("[Garant API] Text is empty, cannot insert links")
            return None
        
        # Проверяем размер текста (лимит 20Мб согласно документации)
        text_bytes = text.encode('utf-8')
        text_size_mb = len(text_bytes) / (1024 * 1024)
        
        if len(text_bytes) > 20 * 1024 * 1024:  # 20Мб лимит
            logger.warning(f"[Garant API] Text too large for link insertion: {text_size_mb:.2f}MB (max 20MB)")
            return None
        
        # Для Render: ограничиваем размер текста для безопасности
        # (оставляем запас для обработки и избежания таймаутов)
        if len(text_bytes) > MAX_TEXT_SIZE_FOR_LINKS:
            logger.warning(f"[Garant API] Text size {text_size_mb:.2f}MB exceeds safe limit for Render ({MAX_TEXT_SIZE_FOR_LINKS / (1024*1024):.0f}MB), truncating")
            text = text[:MAX_TEXT_SIZE_FOR_LINKS]
            text_bytes = text.encode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        full_url = f"{self.api_url}/links"
        timeout_seconds = GARANT_API_TIMEOUT_LINKS
        
        try:
            async with aiohttp.ClientSession() as session:
                request_body = {
                    "text": text,
                    "env": "internet"
                }
                
                logger.info(f"[Garant API] Requesting link insertion for text ({text_size_mb:.2f}MB, {len(text)} chars)")
                logger.debug(f"[Garant API] Endpoint: {full_url}, Text preview: {text[:200]}...")
                
                start_time = __import__('time').time()
                
                async with session.post(
                    full_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                ) as response:
                    elapsed_time = __import__('time').time() - start_time
                    
                    logger.info(f"[Garant API] Link insertion response: status={response.status}, elapsed={elapsed_time:.2f}s")
                    
                    if response.status == 200:
                        try:
                            data = await response.json()
                            logger.debug(f"[Garant API] Response keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                            
                            # Согласно документации, ответ содержит текст с ссылками
                            # Пробуем разные возможные поля ответа
                            result_text = (
                                data.get("text") or 
                                data.get("result") or 
                                data.get("content") or
                                data.get("textWithLinks") or
                                (data if isinstance(data, str) else None)
                            )
                            
                            if result_text:
                                result_size = len(result_text.encode('utf-8')) / (1024 * 1024)
                                logger.info(f"[Garant API] Successfully inserted links, result length: {len(result_text)} chars ({result_size:.2f}MB)")
                                return result_text
                            else:
                                logger.warning(f"[Garant API] Response status 200 but no text found in response. Data: {data}")
                                return None
                        except Exception as parse_error:
                            logger.error(f"[Garant API] Error parsing JSON response: {parse_error}", exc_info=True)
                            return None
                    elif response.status == 401:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Unauthorized (401) - check API key. Response: {error_text[:200]}")
                        return None
                    elif response.status == 403:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Forbidden (403) - check permissions or monthly limit (1000 requests/month). Response: {error_text[:200]}")
                        return None
                    elif response.status == 413:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Payload too large (413) - text size {text_size_mb:.2f}MB exceeds limit. Response: {error_text[:200]}")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"[Garant API] Link insertion error: status={response.status}, text_size={text_size_mb:.2f}MB, response={error_text[:500]}")
                        return None
        except aiohttp.ClientTimeout:
            logger.error(f"[Garant API] Timeout ({timeout_seconds}s) while inserting links for text ({text_size_mb:.2f}MB)")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"[Garant API] Client error inserting links: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"[Garant API] Unexpected error inserting links: {e}", exc_info=True)
            return None
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        info = super().get_info()
        info["api_configured"] = bool(self.api_key)
        info["api_version"] = "2.1.0"
        info["description"] = "Гарант - правовая информационная система"
        return info

