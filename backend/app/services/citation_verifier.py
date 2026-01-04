"""Citation Verifier - проверяет что цитаты и факты действительно присутствуют в документах"""
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
import logging
import re
from difflib import SequenceMatcher
import numpy as np

logger = logging.getLogger(__name__)

# Lazy import for embeddings (only if needed)
_yandex_embeddings = None


def _get_yandex_embeddings():
    """Lazy initialization of Yandex embeddings"""
    global _yandex_embeddings
    if _yandex_embeddings is None:
        try:
            from app.services.yandex_embeddings import YandexEmbeddings
            _yandex_embeddings = YandexEmbeddings()
            logger.info("Initialized Yandex embeddings for citation verification")
        except Exception as e:
            logger.warning(f"Failed to initialize Yandex embeddings: {e}. Semantic verification will be disabled.")
            _yandex_embeddings = False  # Mark as unavailable
    return _yandex_embeddings


class CitationVerifier:
    """
    Проверяет что цитаты и извлеченные факты реально присутствуют в исходных документах.
    
    Используется для обнаружения hallucination - когда агент "придумывает" факты,
    которых нет в документах.
    
    Поддерживает два метода проверки:
    1. Text similarity (SequenceMatcher) - быстрый, но менее точный
    2. Semantic similarity (embeddings) - более точный, но требует API вызов
    """
    
    def __init__(
        self, 
        similarity_threshold: float = 0.7,
        use_embeddings: bool = True,
        embedding_threshold: float = 0.75
    ):
        """
        Initialize citation verifier
        
        Args:
            similarity_threshold: Минимальный порог text similarity (0.0-1.0) для совпадения
            use_embeddings: Использовать embedding-based проверку (более точная, но медленнее)
            embedding_threshold: Минимальный порог semantic similarity для embeddings (0.0-1.0)
        """
        self.similarity_threshold = similarity_threshold
        self.use_embeddings = use_embeddings
        self.embedding_threshold = embedding_threshold
        self.embeddings_available = False
        
        if use_embeddings:
            embeddings = _get_yandex_embeddings()
            self.embeddings_available = embeddings is not False and embeddings is not None
        
        logger.info(
            f"CitationVerifier initialized: threshold={similarity_threshold}, "
            f"use_embeddings={use_embeddings}, embeddings_available={self.embeddings_available}"
        )
    
    def _normalize_text(self, text: str) -> str:
        """
        Нормализует текст для сравнения (убирает пробелы, приводит к нижнему регистру)
        
        Args:
            text: Текст для нормализации
            
        Returns:
            Нормализованный текст
        """
        # Убираем лишние пробелы, приводим к нижнему регистру
        text = re.sub(r'\s+', ' ', text.lower().strip())
        # Убираем знаки пунктуации (опционально, можно оставить для более точного сравнения)
        # text = re.sub(r'[^\w\s]', '', text)
        return text
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Вычисляет similarity между двумя текстами (0.0-1.0) используя text matching
        
        Args:
            text1: Первый текст
            text2: Второй текст
            
        Returns:
            Similarity score (0.0-1.0)
        """
        normalized1 = self._normalize_text(text1)
        normalized2 = self._normalize_text(text2)
        
        # Используем SequenceMatcher для вычисления similarity
        similarity = SequenceMatcher(None, normalized1, normalized2).ratio()
        return similarity
    
    def _calculate_semantic_similarity(self, text1: str, text2: str) -> Optional[float]:
        """
        Вычисляет semantic similarity между двумя текстами используя embeddings
        
        Args:
            text1: Первый текст
            text2: Второй текст
            
        Returns:
            Semantic similarity score (0.0-1.0) или None если embeddings недоступны
        """
        if not self.embeddings_available:
            return None
        
        try:
            embeddings = _get_yandex_embeddings()
            if not embeddings:
                return None
            
            # Получаем embeddings для обоих текстов
            vec1 = np.array(embeddings.embed_query(text1))
            vec2 = np.array(embeddings.embed_query(text2))
            
            # Вычисляем cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            similarity = dot_product / (norm1 * norm2)
            # Normalize to [0, 1] range (cosine similarity is [-1, 1], but embeddings usually give [0, 1])
            return max(0.0, min(1.0, similarity))
            
        except Exception as e:
            logger.warning(f"Error calculating semantic similarity: {e}")
            return None
    
    def _find_text_in_documents(
        self,
        search_text: str,
        source_documents: List[Document],
        tolerance: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Ищет текст в документах с учетом tolerance (fuzzy matching)
        
        Args:
            search_text: Текст для поиска
            source_documents: Список документов для поиска
            tolerance: Максимальное количество символов для fuzzy matching
            
        Returns:
            List of matches with metadata
        """
        matches = []
        normalized_search = self._normalize_text(search_text)
        
        for doc in source_documents:
            if not hasattr(doc, 'page_content'):
                continue
            
            doc_text = doc.page_content
            normalized_doc = self._normalize_text(doc_text)
            
            # Ищем точное вхождение (после нормализации)
            if normalized_search in normalized_doc:
                # Находим позицию в оригинальном тексте
                start_pos = normalized_doc.find(normalized_search)
                end_pos = start_pos + len(normalized_search)
                
                # Берем контекст вокруг совпадения
                context_start = max(0, start_pos - tolerance)
                context_end = min(len(doc_text), end_pos + tolerance)
                context = doc_text[context_start:context_end]
                
                # Даже для exact match проверяем semantic similarity если включено
                semantic_similarity = None
                if self.use_embeddings and self.embeddings_available:
                    semantic_similarity = self._calculate_semantic_similarity(search_text, context)
                
                # Для exact match используем semantic similarity если доступно, иначе 1.0
                if semantic_similarity is not None:
                    combined_similarity = 0.3 * 1.0 + 0.7 * semantic_similarity  # Weighted: 30% exact, 70% semantic
                else:
                    combined_similarity = 1.0
                
                matches.append({
                    "document": doc,
                    "source_file": doc.metadata.get('source_file', 'unknown'),
                    "source_page": doc.metadata.get('source_page'),
                    "match_text": search_text,
                    "context": context,
                    "similarity": combined_similarity,
                    "text_similarity": 1.0,
                    "semantic_similarity": semantic_similarity,
                    "match_type": "exact_semantic" if semantic_similarity else "exact"
                })
            else:
                # Fuzzy matching: ищем похожие подстроки
                # Разбиваем search_text на слова и ищем каждое слово
                search_words = normalized_search.split()
                if len(search_words) > 0:
                    # Ищем первое слово для начала поиска
                    first_word = search_words[0]
                    if first_word in normalized_doc:
                        # Находим позицию первого слова
                        start_pos = normalized_doc.find(first_word)
                        # Берем окно текста вокруг
                        window_start = max(0, start_pos - tolerance)
                        window_end = min(len(normalized_doc), start_pos + len(normalized_search) + tolerance)
                        window_text = normalized_doc[window_start:window_end]
                        
                        # Вычисляем similarity между search_text и window_text
                        similarity = self._calculate_similarity(normalized_search, window_text)
                        
                        if similarity >= self.similarity_threshold:
                            # Находим соответствующий текст в оригинальном документе
                            original_window = doc_text[window_start:window_end]
                            
                            # Если используем embeddings, вычисляем semantic similarity
                            semantic_similarity = None
                            if self.use_embeddings and self.embeddings_available:
                                semantic_similarity = self._calculate_semantic_similarity(search_text, window_text)
                            
                            # Комбинируем text и semantic similarity (weighted average)
                            if semantic_similarity is not None:
                                # Используем взвешенное среднее: 40% text similarity, 60% semantic similarity
                                combined_similarity = 0.4 * similarity + 0.6 * semantic_similarity
                            else:
                                combined_similarity = similarity
                            
                            if combined_similarity >= self.similarity_threshold:
                                matches.append({
                                    "document": doc,
                                    "source_file": doc.metadata.get('source_file', 'unknown'),
                                    "source_page": doc.metadata.get('source_page'),
                                    "match_text": search_text,
                                    "context": original_window,
                                    "similarity": combined_similarity,
                                    "text_similarity": similarity,
                                    "semantic_similarity": semantic_similarity,
                                    "match_type": "fuzzy_semantic" if semantic_similarity else "fuzzy"
                                })
        
        # Сортируем по similarity (по убыванию)
        matches.sort(key=lambda x: x['similarity'], reverse=True)
        return matches
    
    def verify_citation(
        self,
        citation_text: str,
        source_documents: List[Document],
        tolerance: int = 50
    ) -> Dict[str, Any]:
        """
        Проверяет что цитата реально присутствует в исходных документах
        
        Args:
            citation_text: Цитата для проверки
            source_documents: Список документов для поиска
            tolerance: Максимальное количество символов для fuzzy matching
            
        Returns:
            Dictionary with verification result:
            {
                "verified": bool,
                "matches": List[Dict],  # Список найденных совпадений
                "confidence": float,  # Уверенность в верификации (0.0-1.0)
                "best_match": Optional[Dict]  # Лучшее совпадение
            }
        """
        if not citation_text or not citation_text.strip():
            return {
                "verified": False,
                "matches": [],
                "confidence": 0.0,
                "best_match": None,
                "error": "Empty citation text"
            }
        
        if not source_documents:
            return {
                "verified": False,
                "matches": [],
                "confidence": 0.0,
                "best_match": None,
                "error": "No source documents provided"
            }
        
        try:
            matches = self._find_text_in_documents(citation_text, source_documents, tolerance)
            
            if matches:
                best_match = matches[0]
                verified = best_match['similarity'] >= self.similarity_threshold
                confidence = best_match['similarity']
                
                return {
                    "verified": verified,
                    "matches": matches,
                    "confidence": confidence,
                    "best_match": best_match
                }
            else:
                return {
                    "verified": False,
                    "matches": [],
                    "confidence": 0.0,
                    "best_match": None
                }
        except Exception as e:
            logger.error(f"Error verifying citation: {e}", exc_info=True)
            return {
                "verified": False,
                "matches": [],
                "confidence": 0.0,
                "best_match": None,
                "error": str(e)
            }
    
    def verify_extracted_fact(
        self,
        fact: Dict[str, Any],
        source_documents: List[Document],
        tolerance: int = 100
    ) -> Dict[str, Any]:
        """
        Проверяет что извлеченный факт реально присутствует в документах
        
        Args:
            fact: Dictionary с извлеченным фактом (должен содержать reasoning, description, value)
            source_documents: Список документов для поиска
            tolerance: Максимальное количество символов для fuzzy matching
            
        Returns:
            Dictionary with verification result (same format as verify_citation)
        """
        # Извлекаем текст для проверки из разных полей факта
        # Приоритет: reasoning > description > value
        
        text_to_verify = None
        
        if isinstance(fact, dict):
            text_to_verify = (
                fact.get('reasoning') or 
                fact.get('description') or 
                str(fact.get('value', ''))
            )
        else:
            # Если fact - объект, пытаемся получить атрибуты
            text_to_verify = (
                getattr(fact, 'reasoning', None) or
                getattr(fact, 'description', None) or
                str(getattr(fact, 'value', ''))
            )
        
        if not text_to_verify:
            return {
                "verified": False,
                "matches": [],
                "confidence": 0.0,
                "best_match": None,
                "error": "No text found in fact for verification"
            }
        
        # Используем verify_citation для проверки
        return self.verify_citation(text_to_verify, source_documents, tolerance)
    
    def verify_multiple_facts(
        self,
        facts: List[Dict[str, Any]],
        source_documents: List[Document],
        tolerance: int = 100
    ) -> Dict[str, Any]:
        """
        Проверяет несколько фактов одновременно
        
        Args:
            facts: List of fact dictionaries
            source_documents: Список документов для поиска
            tolerance: Максимальное количество символов для fuzzy matching
            
        Returns:
            Dictionary with verification statistics:
            {
                "total_facts": int,
                "verified_count": int,
                "unverified_count": int,
                "average_confidence": float,
                "verification_results": List[Dict]  # Результаты для каждого факта
            }
        """
        verification_results = []
        verified_count = 0
        total_confidence = 0.0
        
        for fact in facts:
            result = self.verify_extracted_fact(fact, source_documents, tolerance)
            verification_results.append({
                "fact": fact,
                "verification": result
            })
            
            if result.get("verified", False):
                verified_count += 1
                total_confidence += result.get("confidence", 0.0)
        
        total_facts = len(facts)
        average_confidence = total_confidence / total_facts if total_facts > 0 else 0.0
        
        return {
            "total_facts": total_facts,
            "verified_count": verified_count,
            "unverified_count": total_facts - verified_count,
            "average_confidence": average_confidence,
            "verification_rate": verified_count / total_facts if total_facts > 0 else 0.0,
            "verification_results": verification_results
        }

