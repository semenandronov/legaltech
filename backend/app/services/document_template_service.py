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
        max_results: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Поиск шаблона в Гаранте
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
            
        Returns:
            Первый найденный шаблон из Гаранта или None
        """
        # #region agent log
        import time
        _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"document_template_service.py:148","message":"search_in_garant called","data":{"query":query,"max_results":max_results},"timestamp":int(time.time()*1000)})
        # #endregion
        
        garant_source = self._get_garant_source()
        
        # #region agent log
        import time
        _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"document_template_service.py:152","message":"GarantSource check","data":{"garant_source_available":garant_source is not None,"has_api_key":hasattr(garant_source,'api_key') and garant_source.api_key is not None if garant_source else False},"timestamp":int(time.time()*1000)})
        # #endregion
        
        if not garant_source:
            logger.warning("GarantSource not available")
            return None
        
        try:
            # Ищем документы в Гаранте - убираем фильтр doc_type для более широкого поиска
            # #region agent log
            import time
            _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"document_template_service.py:160","message":"Calling garant_source.search","data":{"query":query,"max_results":max_results},"timestamp":int(time.time()*1000)})
            # #endregion
            
            results = await garant_source.search(
                query=query,
                max_results=max_results,
                filters=None  # Убираем фильтр doc_type для более широкого поиска
            )
            
            # #region agent log
            import time
            _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"document_template_service.py:167","message":"Garant search results","data":{"results_count":len(results) if results else 0,"first_result_title":results[0].title if results and len(results) > 0 else None,"first_result_metadata":results[0].metadata if results and len(results) > 0 else None},"timestamp":int(time.time()*1000)})
            # #endregion
            
            if not results:
                logger.warning(f"No results from Garant for query: {query}")
                return None
            
            # Пробуем получить полный текст для каждого результата, пока не найдем валидный
            # Увеличиваем количество попыток, так как многие документы могут быть недоступны (404)
            max_attempts = min(30, len(results))
            html_content = None
            result_to_use = None
            doc_id_to_use = None
            
            for i, result in enumerate(results[:max_attempts]):
                doc_id = result.metadata.get("doc_id") or result.metadata.get("topic")
                
                # #region agent log
                import time
                _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"document_template_service.py:220","message":"Trying result","data":{"index":i,"doc_id":doc_id,"doc_id_type":type(doc_id).__name__,"title":result.title if hasattr(result,'title') else None,"all_metadata_keys":list(result.metadata.keys()) if hasattr(result,'metadata') else []},"timestamp":int(time.time()*1000)})
                # #endregion
                
                if not doc_id:
                    logger.warning(f"No doc_id in Garant result {i}, metadata keys: {list(result.metadata.keys()) if hasattr(result, 'metadata') else 'no metadata'}")
                    continue
                
                # Убеждаемся, что doc_id - строка (API ожидает строку)
                doc_id = str(doc_id).strip()
                
                # Получаем HTML шаблон
                # #region agent log
                import time
                _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"document_template_service.py:222","message":"Calling get_document_full_text","data":{"doc_id":doc_id,"attempt":i+1},"timestamp":int(time.time()*1000)})
                # #endregion
                
                html_content = await garant_source.get_document_full_text(doc_id, format="html")
                
                # #region agent log
                import time
                _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"document_template_service.py:227","message":"get_document_full_text result","data":{"doc_id":doc_id,"html_content_length":len(html_content) if html_content else 0,"success":html_content is not None},"timestamp":int(time.time()*1000)})
                # #endregion
                
                if html_content:
                    # Успешно получили контент, используем этот результат
                    logger.info(f"Successfully retrieved document {doc_id} (attempt {i+1})")
                    result_to_use = result
                    doc_id_to_use = doc_id
                    break
                else:
                    logger.warning(f"Failed to get full text for document {doc_id} (attempt {i+1}), trying next...")
            
            if not html_content or not result_to_use:
                # Если все попытки не удались
                logger.error(f"Failed to get full text for any of {max_attempts} results from Garant (total results available: {len(results)})")
                # #region agent log
                import time
                _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"document_template_service.py:256","message":"All attempts failed","data":{"max_attempts":max_attempts,"total_results":len(results),"attempted_doc_ids":[r.metadata.get("doc_id") or r.metadata.get("topic") for r in results[:max_attempts]]},"timestamp":int(time.time()*1000)})
                # #endregion
                return None
            
            return {
                "doc_id": doc_id_to_use,
                "title": result_to_use.title if hasattr(result_to_use, 'title') else "Документ из Гаранта",
                "content": html_content,
                "metadata": result_to_use.metadata if hasattr(result_to_use, 'metadata') else {},
                "url": result_to_use.url if hasattr(result_to_use, 'url') else None
            }
        except Exception as e:
            # #region agent log
            import time
            _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"document_template_service.py:266","message":"Exception in search_in_garant","data":{"error":str(e),"error_type":type(e).__name__},"timestamp":int(time.time()*1000)})
            # #endregion
            logger.error(f"Error searching in Garant: {e}", exc_info=True)
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
            Сохраненный шаблон
        """
        # Извлекаем ключевые слова
        keywords = self._extract_keywords(query or title, title)
        
        # Создаем шаблон
        template = DocumentTemplate(
            title=title,
            content=content,
            source=source,
            source_doc_id=source_doc_id,
            keywords=keywords,
            user_id=user_id,
            garant_metadata=garant_metadata or {}
        )
        
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        
        logger.info(f"Saved template: {title} with {len(keywords)} keywords")
        return template

