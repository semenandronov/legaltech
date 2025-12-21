"""Document processor service using LangChain"""
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from app.config import config
from app.services.yandex_embeddings import YandexEmbeddings
from app.services.legal_splitter import LegalTextSplitter
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
    
    def split_documents(
        self,
        text: str,
        filename: str,
        metadata: Dict[str, Any] = None
    ) -> List[Document]:
        """
        Split document text into chunks
        
        Args:
            text: Document text
            filename: Source filename
            metadata: Additional metadata
            
        Returns:
            List of Document objects with metadata
        """
        # Create base metadata
        doc_metadata = {
            "source_file": filename,
            **(metadata or {})
        }
        
        # Split text
        chunks = self.text_splitter.split_text(text)
        
        # Create Document objects with metadata
        documents = []
        for i, chunk_text in enumerate(chunks):
            chunk_metadata = {
                **doc_metadata,
                "chunk_index": i,
                "source_start_line": None,  # Will be calculated if possible
                "source_end_line": None,
                "source_page": None
            }
            documents.append(Document(page_content=chunk_text, metadata=chunk_metadata))
        
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

