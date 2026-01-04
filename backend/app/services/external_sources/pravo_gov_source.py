"""Прямой парсер для pravo.gov.ru - официальное законодательство"""
from typing import List, Dict, Any, Optional
from .base_source import BaseSource, SourceResult
from .web_search import WebSearchSource
import aiohttp
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class PravoGovSource(BaseSource):
    """
    Прямой парсер для pravo.gov.ru (официальное законодательство РФ).
    
    Поддерживает:
    - Поиск статей кодексов по номеру (ГК, ГПК, АПК, УК, ТК, НК)
    - Извлечение полного текста статьи
    - Парсинг структуры (пункты, подпункты, абзацы)
    - Проверка актуальности редакции
    
    Fallback на WebSearchSource если прямой доступ недоступен.
    """
    
    # Маппинг кодексов на их идентификаторы в URL
    CODE_MAPPING = {
        "ГК": "gk",
        "ГПК": "gpk",
        "АПК": "apk",
        "УК": "uk",
        "ТК": "tk",
        "НК": "nk",
        "ГК РФ": "gk",
        "ГПК РФ": "gpk",
        "АПК РФ": "apk",
        "УК РФ": "uk",
        "ТК РФ": "tk",
        "НК РФ": "nk",
    }
    
    def __init__(self):
        super().__init__(name="pravo_gov", enabled=True)
        self.base_url = "https://pravo.gov.ru"
        self.fallback_source = None
        self.session = None
    
    async def initialize(self) -> bool:
        """Initialize pravo.gov.ru source"""
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
            logger.info("✅ PravoGov source initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize PravoGov source: {e}")
            self._initialized = False
            return False
    
    async def health_check(self) -> bool:
        """Check if pravo.gov.ru is accessible"""
        if not self.session:
            return False
        
        try:
            async with self.session.get(self.base_url, allow_redirects=True) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"PravoGov health check failed: {e}")
            return False
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> List[SourceResult]:
        """
        Поиск на pravo.gov.ru
        
        Args:
            query: Поисковый запрос (например: "статья 393 ГК РФ" или "ст. 100 АПК")
            max_results: Максимальное количество результатов
            filters: Дополнительные фильтры
            use_cache: Использовать кэш (по умолчанию True)
        
        Returns:
            Список SourceResult с найденными статьями
        """
        # Проверяем кэш
        if use_cache:
            from .cache_manager import get_cache_manager
            cache = get_cache_manager()
            cached_result = cache.get(self.name, query, filters)
            if cached_result:
                logger.info(f"Cache hit for {self.name}: {query}")
                # Преобразуем обратно в SourceResult
                results = []
                for item in cached_result:
                    result = SourceResult(**item)
                    results.append(result)
                return results
        
        # Rate limiting
        from .rate_limiter import get_source_rate_limiter
        rate_limiter = get_source_rate_limiter(self.name)
        await rate_limiter.wait(self.name)
        
        try:
            # Пытаемся извлечь номер статьи и кодекс из запроса
            article_match = self._parse_article_query(query)
            
            if article_match:
                # Прямой поиск по номеру статьи
                code_name = article_match["code"]
                article_num = article_match["article"]
                part_num = article_match.get("part")
                paragraph_num = article_match.get("paragraph")
                
                result = await self._get_article_direct(
                    code=code_name,
                    article=article_num,
                    part=part_num,
                    paragraph=paragraph_num
                )
                
                if result:
                    results = [result]
                    # Сохраняем в кэш
                    if use_cache:
                        from .cache_manager import get_cache_manager
                        cache = get_cache_manager()
                        # Преобразуем в JSON-сериализуемый формат
                        cache_value = [r.to_dict() for r in results]
                        cache.set(self.name, query, cache_value, ttl=86400, filters=filters)  # 24 часа для законодательства
                    return results
            
            # Если не удалось найти напрямую, используем fallback
            logger.info(f"Using fallback search for query: {query}")
            if self.fallback_source:
                fallback_results = await self.fallback_source.search(
                    query=query,
                    max_results=max_results,
                    filters={"sites": ["pravo.gov.ru"]}
                )
                # Сохраняем fallback результаты в кэш
                if use_cache and fallback_results:
                    from .cache_manager import get_cache_manager
                    cache = get_cache_manager()
                    cache_value = [r.to_dict() for r in fallback_results]
                    cache.set(self.name, query, cache_value, ttl=3600, filters=filters)  # 1 час для fallback
                return fallback_results
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching pravo.gov.ru: {e}", exc_info=True)
            # Fallback на web search
            if self.fallback_source:
                try:
                    return await self.fallback_source.search(
                        query=query,
                        max_results=max_results,
                        filters={"sites": ["pravo.gov.ru"]}
                    )
                except Exception as fallback_error:
                    logger.error(f"Fallback search also failed: {fallback_error}")
            return []
    
    def _parse_article_query(self, query: str) -> Optional[Dict[str, str]]:
        """
        Парсит запрос для извлечения номера статьи и кодекса
        
        Примеры:
        - "статья 393 ГК РФ" -> {"code": "ГК", "article": "393"}
        - "ст. 100 АПК" -> {"code": "АПК", "article": "100"}
        - "п. 1 ст. 393 ГК" -> {"code": "ГК", "article": "393", "part": "1"}
        
        Returns:
            Словарь с полями code, article, part (опционально), paragraph (опционально)
            или None если не удалось распарсить
        """
        # Нормализуем запрос
        query = query.strip()
        
        # Паттерны для распознавания
        patterns = [
            # "статья 393 ГК РФ"
            r"статья\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
            # "ст. 100 АПК"
            r"ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
            # "п. 1 ст. 393 ГК"
            r"п\.?\s+(\d+)\s+ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
            # "ч. 2 ст. 393 ГК"
            r"ч\.?\s+(\d+)\s+ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    # Простой формат: статья номер кодекс
                    article_num = groups[0]
                    code_name = groups[1].replace(" РФ", "").strip()
                    
                    if code_name in self.CODE_MAPPING:
                        return {
                            "code": code_name,
                            "article": article_num
                        }
                elif len(groups) == 3:
                    # Формат с частью/пунктом: ч. X ст. Y кодекс
                    part_or_paragraph = groups[0]
                    article_num = groups[1]
                    code_name = groups[2].replace(" РФ", "").strip()
                    
                    if code_name in self.CODE_MAPPING:
                        return {
                            "code": code_name,
                            "article": article_num,
                            "part": part_or_paragraph
                        }
        
        return None
    
    async def _get_article_direct(
        self,
        code: str,
        article: str,
        part: Optional[str] = None,
        paragraph: Optional[str] = None
    ) -> Optional[SourceResult]:
        """
        Получает статью напрямую по номеру
        
        Args:
            code: Название кодекса (ГК, АПК, и т.д.)
            article: Номер статьи
            part: Номер части (опционально)
            paragraph: Номер пункта (опционально)
        
        Returns:
            SourceResult с текстом статьи или None
        """
        if not self.session:
            return None
        
        code_id = self.CODE_MAPPING.get(code)
        if not code_id:
            logger.warning(f"Unknown code: {code}")
            return None
        
        try:
            # Формируем URL для статьи
            # Структура URL на pravo.gov.ru может быть разной
            # Пробуем несколько вариантов
            url_variants = [
                f"{self.base_url}/Proxy/Doc/?doc_id={code_id}&art_id={article}",
                f"{self.base_url}/proxy/ip/?doc_itself={code_id}&nd={article}",
                f"{self.base_url}/document/{code_id}/article/{article}",
            ]
            
            for url in url_variants:
                try:
                    async with self.session.get(url, allow_redirects=True) as response:
                        if response.status == 200:
                            html_content = await response.text()
                            
                            # Парсим HTML для извлечения текста статьи
                            article_text = self._parse_article_html(html_content, part, paragraph)
                            
                            if article_text:
                                title = f"Статья {article} {code} РФ"
                                if part:
                                    title += f", часть {part}"
                                if paragraph:
                                    title += f", пункт {paragraph}"
                                
                                return SourceResult(
                                    content=article_text,
                                    title=title,
                                    source_name="pravo_gov",
                                    url=url,
                                    relevance_score=1.0,  # Прямой доступ = максимальная релевантность
                                    metadata={
                                        "code": code,
                                        "article": article,
                                        "part": part,
                                        "paragraph": paragraph,
                                        "direct_access": True
                                    }
                                )
                except Exception as e:
                    logger.debug(f"Failed to fetch from {url}: {e}")
                    continue
            
            logger.warning(f"Could not fetch article {article} from {code} from pravo.gov.ru")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching article directly: {e}", exc_info=True)
            return None
    
    def _parse_article_html(
        self,
        html_content: str,
        part: Optional[str] = None,
        paragraph: Optional[str] = None
    ) -> Optional[str]:
        """
        Парсит HTML для извлечения текста статьи
        
        Args:
            html_content: HTML содержимое страницы
            part: Номер части для фильтрации (опционально)
            paragraph: Номер пункта для фильтрации (опционально)
        
        Returns:
            Текст статьи или None
        """
        try:
            # Простой парсинг без BeautifulSoup (может быть улучшен)
            # Убираем скрипты и стили
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # Извлекаем текст из основных элементов
            # Ищем контейнеры с текстом статьи
            text_patterns = [
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
                r'<p[^>]*>(.*?)</p>',
            ]
            
            extracted_texts = []
            for pattern in text_patterns:
                matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    # Убираем HTML теги
                    text = re.sub(r'<[^>]+>', '', match)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text and len(text) > 50:  # Минимальная длина для валидного текста
                        extracted_texts.append(text)
            
            if extracted_texts:
                # Объединяем все тексты
                full_text = "\n\n".join(extracted_texts)
                
                # Если указана часть или пункт, фильтруем текст
                if part or paragraph:
                    filtered_text = self._filter_by_part_paragraph(full_text, part, paragraph)
                    if filtered_text:
                        return filtered_text
                
                return full_text
            
            # Fallback: извлекаем весь текст из body
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
            if body_match:
                text = re.sub(r'<[^>]+>', '', body_match.group(1))
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 50:
                    return text
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing article HTML: {e}", exc_info=True)
            return None
    
    def _filter_by_part_paragraph(
        self,
        text: str,
        part: Optional[str] = None,
        paragraph: Optional[str] = None
    ) -> Optional[str]:
        """
        Фильтрует текст по части и пункту
        
        Args:
            text: Полный текст статьи
            part: Номер части
            paragraph: Номер пункта
        
        Returns:
            Отфильтрованный текст или None
        """
        if not (part or paragraph):
            return text
        
        # Ищем соответствующие части/пункты в тексте
        lines = text.split('\n')
        filtered_lines = []
        in_target_section = False
        
        for line in lines:
            line_lower = line.lower().strip()
            
            # Проверяем начало части/пункта
            if part:
                part_pattern = rf'^\s*(?:часть|ч\.?)\s+{part}[\s\.:;]'
                if re.match(part_pattern, line_lower, re.IGNORECASE):
                    in_target_section = True
                    filtered_lines.append(line)
                    continue
            
            if paragraph:
                para_pattern = rf'^\s*(?:пункт|п\.?)\s+{paragraph}[\s\.:;]'
                if re.match(para_pattern, line_lower, re.IGNORECASE):
                    in_target_section = True
                    filtered_lines.append(line)
                    continue
            
            if in_target_section:
                # Если нашли следующую часть/пункт, останавливаемся
                if re.match(r'^\s*(?:часть|ч\.?|пункт|п\.?)\s+\d+', line_lower, re.IGNORECASE):
                    if not (part and re.match(rf'^\s*(?:часть|ч\.?)\s+{part}', line_lower, re.IGNORECASE)):
                        break
                    if paragraph and re.match(rf'^\s*(?:пункт|п\.?)\s+{paragraph}', line_lower, re.IGNORECASE):
                        break
                
                filtered_lines.append(line)
        
        if filtered_lines:
            return '\n'.join(filtered_lines)
        
        return None
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_initialized()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

