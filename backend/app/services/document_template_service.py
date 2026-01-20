"""Service for managing document templates"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.document_template import DocumentTemplate
from app.services.external_sources.garant_source import GarantSource
from app.services.external_sources.source_router import get_source_router, initialize_source_router
import logging
import re
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)


def _safe_debug_log(data: dict) -> None:
    """Безопасное логирование в debug.log с обработкой ошибок"""
    try:
        # Пытаемся найти путь к debug.log относительно корня проекта
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        log_path = os.path.join(base_dir, '.cursor', 'debug.log')
        
        # Создаем директорию если не существует
        log_dir = os.path.dirname(log_path)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Записываем лог
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
    except Exception:
        # Игнорируем ошибки логирования - это не критично
        pass


class DocumentTemplateService:
    """Service for managing cached document templates"""
    
    def __init__(self, db: Session):
        self.db = db
        self._garant_source = None
    
    def _get_garant_source(self) -> Optional[GarantSource]:
        """Получить экземпляр GarantSource"""
        if self._garant_source is None:
            try:
                # Инициализируем router с официальными источниками, если еще не инициализирован
                router = initialize_source_router(rag_service=None, register_official_sources=True)
                self._garant_source = router.get_source("garant")
                if self._garant_source is None:
                    logger.warning("GarantSource not registered in source router")
                elif not self._garant_source.enabled:
                    logger.warning("GarantSource is disabled (likely missing GARANT_API_KEY)")
            except Exception as e:
                logger.warning(f"Failed to get GarantSource: {e}")
        return self._garant_source
    
    def _extract_keywords(self, query: str, title: str = "") -> List[str]:
        """
        Извлечь ключевые слова из запроса и названия
        
        Args:
            query: Пользовательский запрос
            title: Название шаблона
            
        Returns:
            Список ключевых слов
        """
        keywords = set()
        
        # Нормализуем текст (нижний регистр, убираем пунктуацию)
        text = (query + " " + title).lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Разбиваем на слова
        words = text.split()
        
        # Фильтруем стоп-слова (можно расширить)
        stop_words = {
            "создай", "создать", "нужен", "нужно", "для", "из", "в", "на", "и", "или", 
            "а", "но", "как", "что", "это", "тот", "та", "те", "такой", "такая", 
            "такое", "такие", "мой", "моя", "мое", "мои", "твой", "твоя", "твое",
            "наш", "наша", "наше", "ваш", "ваша", "ваше", "его", "её", "их"
        }
        
        for word in words:
            if len(word) > 2 and word not in stop_words:
                keywords.add(word)
        
        # Добавляем фразы из 2-3 слов
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i+1]}"
            if len(phrase) > 5 and words[i] not in stop_words and words[i+1] not in stop_words:
                keywords.add(phrase)
        
        # Добавляем фразы из 3 слов
        for i in range(len(words) - 2):
            phrase = f"{words[i]} {words[i+1]} {words[i+2]}"
            if len(phrase) > 8 and all(w not in stop_words for w in [words[i], words[i+1], words[i+2]]):
                keywords.add(phrase)
        
        return list(keywords)
    
    async def find_similar_template(
        self, 
        query: str, 
        user_id: Optional[str] = None,
        threshold: float = 0.3
    ) -> Optional[DocumentTemplate]:
        """
        Найти похожий шаблон в кэше по запросу
        
        Args:
            query: Пользовательский запрос
            user_id: ID пользователя (для фильтрации)
            threshold: Минимальный порог совпадения (0-1)
            
        Returns:
            Найденный шаблон или None
        """
        query_keywords = set(self._extract_keywords(query))
        
        if not query_keywords:
            return None
        
        # Ищем шаблоны по ключевым словам
        templates = self.db.query(DocumentTemplate).filter(
            or_(
                DocumentTemplate.is_public == True,
                DocumentTemplate.user_id == user_id
            )
        ).all()
        
        best_match = None
        best_score = 0
        
        for template in templates:
            template_keywords = set(template.keywords or [])
            
            # Вычисляем коэффициент совпадения (Jaccard similarity)
            if template_keywords:
                intersection = query_keywords & template_keywords
                union = query_keywords | template_keywords
                score = len(intersection) / len(union) if union else 0
                
                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = template
        
        if best_match:
            # Обновляем статистику использования
            best_match.usage_count += 1
            best_match.last_used_at = datetime.utcnow()
            self.db.commit()
            logger.info(f"Found cached template: {best_match.title} (score: {best_score:.2f})")
        
        return best_match
    
    async def search_in_garant(
        self, 
        query: str, 
        max_results: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Поиск шаблона документа в Гаранте
        
        Согласно документации API v2.1.0:
        - Поиск: POST /v2/search с параметрами text, isQuery, env, sort, sortOrder, page
        - Экспорт: POST /v2/export/html с параметрами topic, env
        - Ограничение: не более 30 экспортов документов в месяц
        
        Args:
            query: Поисковый запрос (например "договор поставки образец")
            max_results: Максимальное количество результатов поиска
            
        Returns:
            Найденный шаблон с полным HTML контентом или None
        """
        logger.info(f"[Garant] Searching for template: {query}")
        
        garant_source = self._get_garant_source()
        
        if not garant_source:
            logger.warning("GarantSource not available")
            return None
        
        try:
            # Ищем документы в Гаранте
            # Используем семантический поиск (isQuery=false) для поиска по смыслу
            results = await garant_source.search(
                query=query,
                max_results=max_results,
                filters=None
            )
            
            if not results:
                logger.warning(f"No results from Garant for query: {query}")
                return None
            
            logger.info(f"[Garant] Found {len(results)} results, trying to export...")
            
            # Пробуем получить полный текст для каждого результата
            # Ограничение API: не более 30 экспортов в месяц
            max_attempts = min(10, len(results))  # Ограничиваем попытки чтобы не тратить лимит
            html_content = None
            result_to_use = None
            doc_id_to_use = None
            
            for i, result in enumerate(results[:max_attempts]):
                # Получаем topic (ID документа) из метаданных
                doc_id = result.metadata.get("topic") or result.metadata.get("doc_id")
                
                if not doc_id:
                    logger.debug(f"[Garant] Result {i}: no topic/doc_id in metadata")
                    continue
                
                doc_id = str(doc_id).strip()
                logger.info(f"[Garant] Trying to export document {i+1}/{max_attempts}: topic={doc_id}, title='{result.title[:50]}...'")
                
                # Получаем полный текст документа через API экспорта
                html_content = await garant_source.get_document_full_text(doc_id, format="html")
                
                if html_content and len(html_content) > 100:
                    # Успешно получили контент
                    logger.info(f"[Garant] Successfully exported document topic={doc_id}, content length={len(html_content)}")
                    result_to_use = result
                    doc_id_to_use = doc_id
                    break
                else:
                    logger.debug(f"[Garant] Failed to export document topic={doc_id}")
            
            if not html_content or not result_to_use:
                logger.warning(f"[Garant] Failed to export any of {max_attempts} documents")
                return None
            
            return {
                "doc_id": doc_id_to_use,
                "title": result_to_use.title if hasattr(result_to_use, 'title') else "Документ из Гаранта",
                "content": html_content,
                "metadata": result_to_use.metadata if hasattr(result_to_use, 'metadata') else {},
                "url": result_to_use.url if hasattr(result_to_use, 'url') else None
            }
            
        except Exception as e:
            logger.error(f"[Garant] Error searching: {e}", exc_info=True)
            return None
    
    async def save_template(
        self,
        title: str,
        content: str,
        source: str = "garant",
        source_doc_id: Optional[str] = None,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        garant_metadata: Optional[Dict[str, Any]] = None
    ) -> DocumentTemplate:
        """
        Сохранить шаблон в кэш
        
        Args:
            title: Название шаблона
            content: HTML содержимое
            source: Источник ("garant", "custom")
            source_doc_id: ID документа в источнике
            query: Исходный запрос пользователя (для извлечения ключевых слов)
            user_id: ID пользователя
            garant_metadata: Метаданные из Гаранта
            
        Returns:
            Сохраненный шаблон (существующий или новый)
        """
        # Проверяем, есть ли уже такой шаблон в БД (по source_doc_id)
        # Это предотвращает дублирование шаблонов из Гарант
        if source_doc_id:
            existing_template = self.db.query(DocumentTemplate).filter(
                DocumentTemplate.source == source,
                DocumentTemplate.source_doc_id == str(source_doc_id)
            ).first()
            
            if existing_template:
                # Обновляем ключевые слова (добавляем новые из текущего запроса)
                new_keywords = self._extract_keywords(query or title, title)
                existing_keywords = set(existing_template.keywords or [])
                merged_keywords = list(existing_keywords | set(new_keywords))
                
                existing_template.keywords = merged_keywords
                existing_template.usage_count += 1
                existing_template.last_used_at = datetime.utcnow()
                self.db.commit()
                
                logger.info(f"Template already exists in DB: {existing_template.title} (source_doc_id={source_doc_id}), updated keywords")
                return existing_template
        
        # Извлекаем ключевые слова
        keywords = self._extract_keywords(query or title, title)
        
        # Создаем шаблон
        # Шаблоны из Гаранта делаем публичными, чтобы другие пользователи тоже могли их использовать
        is_public = (source == "garant")
        
        template = DocumentTemplate(
            title=title,
            content=content,
            source=source,
            source_doc_id=source_doc_id,
            keywords=keywords,
            user_id=user_id,
            garant_metadata=garant_metadata or {},
            is_public=is_public
        )
        
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        
        logger.info(f"Saved NEW template: {title} with {len(keywords)} keywords, is_public={is_public}")
        return template

