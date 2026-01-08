"""Document processor service using LangChain"""
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from app.config import config
from app.services.yandex_embeddings import YandexEmbeddings
from app.services.legal_splitter import LegalTextSplitter
from app.services.bm25_retriever import BM25Retriever
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Service for processing documents with LangChain"""
    
    def __init__(self):
        """Initialize document processor"""
        # Use LegalTextSplitter optimized for legal documents
        self.text_splitter = LegalTextSplitter(
            chunk_size=1200,  # Optimal for legal documents
            chunk_overlap=300  # Better overlap for context preservation
        )
        
        # Initialize embeddings - только Yandex, без fallback
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
            raise ValueError(
                "YANDEX_API_KEY или YANDEX_IAM_TOKEN должны быть настроены. "
                "OpenRouter больше не используется."
            )
        
        if not config.YANDEX_FOLDER_ID:
            raise ValueError(
                "YANDEX_FOLDER_ID должен быть настроен для работы Yandex embeddings."
            )
        
        try:
            self.embeddings = YandexEmbeddings()
            logger.info("✅ Using Yandex embeddings")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex embeddings: {e}")
            raise ValueError(f"Ошибка инициализации Yandex embeddings: {str(e)}")
        
        # Initialize PGVector store (only vector store supported)
        try:
            from app.services.pgvector_store import CaseVectorStore
            self.vector_store = CaseVectorStore(embeddings=self.embeddings)
            logger.info("✅ Using PGVector store (production-ready, multi-tenant)")
        except Exception as e:
            logger.error(f"Failed to initialize PGVector store: {e}", exc_info=True)
            raise ValueError(f"Ошибка инициализации PGVector store: {str(e)}")
        
        # Initialize BM25 retriever for hybrid search
        self.bm25_retriever = BM25Retriever()
    
    def split_documents(
        self,
        text: str,
        filename: str,
        metadata: Dict[str, Any] = None,
        file_id: Optional[str] = None
    ) -> List[Document]:
        """
        Split document text into chunks with provenance metadata
        
        Phase 1: Updated to use split_documents_with_metadata for char_start/char_end tracking
        
        Args:
            text: Document text
            filename: Source filename
            metadata: Additional metadata
            file_id: File ID for generating doc_id (optional)
            
        Returns:
            List of Document objects with metadata including char_start, char_end, doc_id
        """
        import uuid
        
        # Create base metadata
        doc_metadata = {
            "source_file": filename,
            **(metadata or {})
        }
        
        # Generate doc_id for this document (Phase 1.4)
        # Use file_id if available, otherwise generate UUID
        doc_id = file_id if file_id else str(uuid.uuid4())
        doc_metadata["doc_id"] = doc_id
        
        # Use split_documents_with_metadata to get char_start and char_end
        documents = self.text_splitter.split_documents_with_metadata(
            text=text,
            filename=filename,
            metadata=doc_metadata
        )
        
        # Ensure all documents have doc_id in metadata
        for doc in documents:
            doc.metadata["doc_id"] = doc_id
            # char_start and char_end are already added by split_documents_with_metadata
        
        return documents
    
    def create_embeddings(self, documents: List[Document], batch_size: int = 100) -> List[List[float]]:
        """
        Create embeddings for documents with batch processing
        
        Args:
            documents: List of Document objects
            batch_size: Number of documents to process in each batch (default: 100)
            
        Returns:
            List of embedding vectors
        """
        texts = [doc.page_content for doc in documents]
        
        # Process in batches to avoid memory issues and rate limits
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self.embeddings.embed_documents(batch_texts)
            all_embeddings.extend(batch_embeddings)
            logger.debug(f"Processed embeddings batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")
        
        return all_embeddings
    
    def store_in_vector_db(
        self,
        case_id: str,
        documents: List[Document],
        db: Session,
        original_files: Dict[str, bytes] = None
    ) -> str:
        """
        Store documents in PGVector database
        
        Args:
            case_id: Case identifier
            documents: List of Document objects
            db: Database session (not used, kept for API compatibility)
            original_files: Ignored (kept for API compatibility)
            
        Returns:
            collection_name
        """
        if not documents:
            raise ValueError(f"No documents provided for case {case_id}. Cannot store in PGVector without documents.")
        
        logger.info(f"Storing {len(documents)} document chunks in PGVector for case {case_id}")
        
        try:
            # Add case_id to all document metadata for multi-tenant filtering
            for doc in documents:
                doc.metadata["case_id"] = case_id
            
            # Store documents in PGVector
            ids = self.vector_store.add_documents(documents, case_id=case_id)
            logger.info(f"✅ Stored {len(ids)} documents in PGVector for case {case_id}")
            
            # Return collection name as identifier
            return self.vector_store.collection_name
        except Exception as e:
            logger.error(f"Failed to store documents in PGVector for case {case_id}: {e}", exc_info=True)
            raise
    
    def retrieve_relevant_chunks(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        distance_threshold: float = 1.5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve relevant document chunks using PGVector search
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of chunks to retrieve
            distance_threshold: Maximum distance threshold (for filtering)
            db: Optional database session (not used, kept for API compatibility)
            
        Returns:
            List of relevant Document objects with scores
        """
        try:
            # Search in PGVector with case_id filter (multi-tenant isolation)
            documents = self.vector_store.similarity_search(
                query=query,
                case_id=case_id,
                k=k
            )
            
            # Filter by distance threshold if provided
            if distance_threshold < 1.5:  # Only filter if threshold is meaningful
                # Get documents with scores
                docs_with_scores = self.vector_store.similarity_search_with_score(
                    query=query,
                    case_id=case_id,
                    k=k * 2  # Get more to filter
                )
                # Filter by distance threshold
                filtered_docs = []
                for doc, score in docs_with_scores:
                    # Score is distance (lower = better)
                    if score <= distance_threshold:
                        filtered_docs.append(doc)
                        if len(filtered_docs) >= k:
                            break
                documents = filtered_docs
            
            if not documents:
                logger.warning(f"No relevant chunks found for case {case_id} in PGVector")
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving chunks from PGVector for case {case_id}: {e}", exc_info=True)
            raise
    
    def hybrid_search(
        self,
        case_id: str,
        query: str,
        k: int = 10,
        alpha: float = 0.7,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Hybrid search: объединяет dense search (semantic) и sparse search (BM25)
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of documents to retrieve
            alpha: Weight for dense search (0.0-1.0), sparse weight = 1.0 - alpha
                  alpha=0.7 означает 70% weight для dense, 30% для sparse
            db: Optional database session (not used, kept for API compatibility)
            
        Returns:
            List of relevant Document objects with combined scores
        """
        try:
            # 1. Dense search (semantic search via PGVector)
            dense_docs = self.retrieve_relevant_chunks(
                case_id=case_id,
                query=query,
                k=k * 2,  # Get more documents for better ranking
                db=db
            )
            
            # 2. Sparse search (BM25)
            # Сначала нужно убедиться, что индекс построен
            # Для этого получаем все документы дела (можно кешировать)
            if not self.bm25_retriever.has_index(case_id):
                logger.info(f"BM25 index not found for case {case_id}, building index...")
                # Получаем все документы дела из vector store для построения индекса
                # Используем простой запрос для получения всех документов
                try:
                    all_docs = self.retrieve_relevant_chunks(
                        case_id=case_id,
                        query="",  # Пустой запрос для получения всех документов (если поддерживается)
                        k=1000,  # Большое количество для получения всех документов
                        db=db
                    )
                    if all_docs:
                        # Если пустой запрос не работает, используем документы из dense search
                        if len(all_docs) < 10:
                            all_docs = dense_docs
                        
                        # Строим индекс
                        self.bm25_retriever.build_index(case_id, all_docs)
                except Exception as e:
                    logger.warning(f"Could not build BM25 index for case {case_id}: {e}")
            
            # Выполняем BM25 поиск
            sparse_docs = self.bm25_retriever.retrieve(case_id, query, k=k * 2)
            
            # 3. Reciprocal Rank Fusion (RRF) для объединения результатов
            # RRF score = sum(1 / (k + rank)) для каждого ранга документа
            rrf_scores: Dict[str, float] = {}
            rrf_docs: Dict[str, Document] = {}
            
            # Добавляем документы из dense search
            for rank, doc in enumerate(dense_docs, start=1):
                doc_id = self._get_doc_id(doc)
                # RRF: alpha weight для dense search
                rrf_score = alpha * (1.0 / (60 + rank))  # k=60 для RRF
                if doc_id not in rrf_scores:
                    rrf_scores[doc_id] = 0.0
                    rrf_docs[doc_id] = doc
                rrf_scores[doc_id] += rrf_score
                
                # Сохраняем similarity_score если есть
                if hasattr(doc, 'metadata') and 'similarity_score' not in doc.metadata:
                    doc.metadata['similarity_score'] = 1.0 - (rank / len(dense_docs))
            
            # Добавляем документы из sparse search
            for rank, doc in enumerate(sparse_docs, start=1):
                doc_id = self._get_doc_id(doc)
                # RRF: (1-alpha) weight для sparse search
                rrf_score = (1.0 - alpha) * (1.0 / (60 + rank))
                if doc_id not in rrf_scores:
                    rrf_scores[doc_id] = 0.0
                    rrf_docs[doc_id] = doc
                rrf_scores[doc_id] += rrf_score
                
                # Сохраняем bm25_score если есть
                if hasattr(doc, 'metadata') and 'bm25_score' not in doc.metadata:
                    doc.metadata['bm25_score'] = 0.0
            
            # Сортируем по RRF score (по убыванию)
            sorted_docs = sorted(
                rrf_docs.items(),
                key=lambda x: rrf_scores[x[0]],
                reverse=True
            )
            
            # Возвращаем top-k документов
            result_docs = [doc for doc_id, doc in sorted_docs[:k]]
            
            # Добавляем combined_score в metadata
            for i, (doc_id, doc) in enumerate(sorted_docs[:k]):
                if hasattr(doc, 'metadata'):
                    doc.metadata['combined_score'] = float(rrf_scores[doc_id])
                else:
                    doc.metadata = {'combined_score': float(rrf_scores[doc_id])}
            
            logger.info(f"Hybrid search for case {case_id} returned {len(result_docs)} documents (alpha={alpha})")
            return result_docs
            
        except Exception as e:
            logger.error(f"Error in hybrid search for case {case_id}: {e}", exc_info=True)
            # Fallback to dense search only
            logger.warning("Falling back to dense search only")
            return self.retrieve_relevant_chunks(case_id, query, k=k, db=db)
    
    def _get_doc_id(self, doc: Document) -> str:
        """
        Генерирует уникальный ID для документа для использования в RRF
        
        Args:
            doc: Document object
            
        Returns:
            String ID for the document
        """
        # Используем комбинацию source_file и chunk_index если доступно
        if hasattr(doc, 'metadata'):
            source = doc.metadata.get('source_file', 'unknown')
            chunk_idx = doc.metadata.get('chunk_index', 0)
            return f"{source}:{chunk_idx}"
        else:
            # Fallback: используем hash от содержимого
            return str(hash(doc.page_content[:100]))
    
    def get_index_id(self, case_id: str, db: Optional[Session] = None) -> Optional[str]:
        """
        Get collection identifier for case (PGVector)
        
        Args:
            case_id: Case identifier
            db: Optional database session (not used, kept for API compatibility)
            
        Returns:
            collection_name (all cases share collection, filtered by metadata)
        """
        # For PGVector, return collection name (all cases share collection, filtered by metadata)
        return self.vector_store.collection_name

