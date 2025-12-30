"""BM25 Retriever for sparse search (keyword-based)"""
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
import logging
import re

logger = logging.getLogger(__name__)

# Try to import rank_bm25
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
    logger.info("✅ rank_bm25 imported successfully")
except ImportError as e:
    logger.warning(f"rank_bm25 not available: {e}. BM25 retrieval will not work.")
    BM25_AVAILABLE = False
    BM25Okapi = None


class BM25Retriever:
    """
    BM25 retriever для sparse search (keyword-based поиск)
    
    Используется в комбинации с dense search (semantic search) для hybrid search.
    """
    
    def __init__(self):
        """Initialize BM25 retriever"""
        self.available = BM25_AVAILABLE
        self.indices: Dict[str, Any] = {}  # case_id -> (bm25_index, documents, tokenized_docs)
        logger.info(f"BM25Retriever initialized (available: {self.available})")
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Токенизация текста для BM25
        
        Args:
            text: Текст для токенизации
            
        Returns:
            List of tokens (lowercased words)
        """
        # Простая токенизация: разбиваем по пробелам и пунктуации, приводим к нижнему регистру
        # Убираем специальные символы, оставляем только буквы и цифры
        text = text.lower()
        # Разбиваем по пробелам и знакам пунктуации
        tokens = re.findall(r'\b\w+\b', text)
        return tokens
    
    def build_index(self, case_id: str, documents: List[Document]) -> bool:
        """
        Строит BM25 индекс для документов дела
        
        Args:
            case_id: ID дела
            documents: Список документов для индексации
            
        Returns:
            True если индекс успешно построен, False иначе
        """
        if not self.available:
            logger.warning("BM25 not available, cannot build index")
            return False
        
        if not documents:
            logger.warning(f"No documents provided for case {case_id}, cannot build index")
            return False
        
        try:
            # Токенизируем все документы
            tokenized_docs = []
            valid_documents = []
            
            for doc in documents:
                if not hasattr(doc, 'page_content') or not doc.page_content:
                    continue
                
                tokens = self._tokenize(doc.page_content)
                if tokens:  # Пропускаем пустые документы
                    tokenized_docs.append(tokens)
                    valid_documents.append(doc)
            
            if not tokenized_docs:
                logger.warning(f"No valid documents to index for case {case_id}")
                return False
            
            # Строим BM25 индекс
            bm25_index = BM25Okapi(tokenized_docs)
            
            # Сохраняем индекс и документы
            self.indices[case_id] = {
                "bm25": bm25_index,
                "documents": valid_documents,
                "tokenized_docs": tokenized_docs
            }
            
            logger.info(f"Built BM25 index for case {case_id} with {len(valid_documents)} documents")
            return True
            
        except Exception as e:
            logger.error(f"Error building BM25 index for case {case_id}: {e}", exc_info=True)
            return False
    
    def retrieve(
        self,
        case_id: str,
        query: str,
        k: int = 10
    ) -> List[Document]:
        """
        Выполняет поиск по BM25 индексу
        
        Args:
            case_id: ID дела
            query: Поисковый запрос
            k: Количество документов для возврата
            
        Returns:
            List of Documents, отсортированных по релевантности (BM25 score)
        """
        if not self.available:
            logger.warning("BM25 not available, returning empty list")
            return []
        
        if case_id not in self.indices:
            logger.warning(f"BM25 index not found for case {case_id}")
            return []
        
        try:
            index_data = self.indices[case_id]
            bm25_index = index_data["bm25"]
            documents = index_data["documents"]
            
            # Токенизируем запрос
            query_tokens = self._tokenize(query)
            
            if not query_tokens:
                logger.warning(f"Query '{query}' produced no tokens")
                return []
            
            # Получаем BM25 scores для всех документов
            scores = bm25_index.get_scores(query_tokens)
            
            # Сортируем документы по score (по убыванию)
            doc_scores = list(zip(documents, scores))
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Возвращаем top-k документов
            top_docs = [doc for doc, score in doc_scores[:k]]
            
            # Добавляем score в metadata для последующего использования в hybrid search
            for i, (doc, score) in enumerate(doc_scores[:k]):
                if hasattr(doc, 'metadata'):
                    doc.metadata['bm25_score'] = float(score)
                else:
                    # Если metadata нет, создаем его
                    doc.metadata = {'bm25_score': float(score)}
            
            logger.debug(f"BM25 retrieved {len(top_docs)} documents for case {case_id} with query: {query[:50]}...")
            return top_docs
            
        except Exception as e:
            logger.error(f"Error retrieving documents with BM25 for case {case_id}: {e}", exc_info=True)
            return []
    
    def has_index(self, case_id: str) -> bool:
        """
        Проверяет, существует ли индекс для дела
        
        Args:
            case_id: ID дела
            
        Returns:
            True если индекс существует, False иначе
        """
        return case_id in self.indices
    
    def remove_index(self, case_id: str) -> bool:
        """
        Удаляет индекс для дела (для освобождения памяти)
        
        Args:
            case_id: ID дела
            
        Returns:
            True если индекс был удален, False если его не было
        """
        if case_id in self.indices:
            del self.indices[case_id]
            logger.info(f"Removed BM25 index for case {case_id}")
            return True
        return False
    
    def get_index_size(self, case_id: str) -> Optional[int]:
        """
        Возвращает размер индекса (количество документов)
        
        Args:
            case_id: ID дела
            
        Returns:
            Количество документов в индексе или None если индекс не существует
        """
        if case_id not in self.indices:
            return None
        return len(self.indices[case_id]["documents"])

