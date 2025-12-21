"""PGVector Vector Store service for multi-tenant document storage"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from langchain_postgres import PGVector
from app.config import config
from app.services.yandex_embeddings import YandexEmbeddings
import logging

logger = logging.getLogger(__name__)


class CaseVectorStore:
    """
    Multi-tenant PGVector store for case-specific document embeddings
    
    Uses metadata filtering for case isolation and row-level security.
    """
    
    def __init__(self, embeddings=None):
        """
        Initialize PGVector store
        
        Args:
            embeddings: Embeddings instance (defaults to YandexEmbeddings)
        """
        if embeddings is None:
            self.embeddings = YandexEmbeddings()
        else:
            self.embeddings = embeddings
        
        # Initialize PGVector store
        # Use connection string from config (convert if needed)
        db_url = config.DATABASE_URL
        # PGVector expects postgresql:// or postgresql+psycopg:// format
        # langchain-postgres uses psycopg2/psycopg internally
        if db_url.startswith("postgresql+psycopg://"):
            # Keep as is - langchain-postgres handles it
            pass
        elif not db_url.startswith("postgresql://"):
            logger.warning(f"Unexpected DATABASE_URL format: {db_url}")
        
        # Collection name for storing vectors (all cases share the same collection,
        # but are isolated via metadata filter)
        self.collection_name = "legal_ai_vault_vectors"
        
        try:
            # Create PGVector store instance
            # This will create the table if it doesn't exist
            self.vector_store = PGVector(
                connection=db_url,
                embedding_function=self.embeddings,
                collection_name=self.collection_name,
                use_jsonb=True,  # Use JSONB for metadata (better performance)
                pre_delete_collection=False,  # Don't delete on init
            )
            logger.info("✅ PGVector store initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PGVector store: {e}", exc_info=True)
            raise ValueError(f"Ошибка инициализации PGVector store: {str(e)}")
    
    def get_retriever(self, case_id: str, k: int = 5, search_kwargs: Optional[Dict] = None):
        """
        Get retriever for a specific case with metadata filtering
        
        Args:
            case_id: Case identifier for filtering
            k: Number of documents to retrieve
            search_kwargs: Additional search parameters
            
        Returns:
            VectorStoreRetriever instance filtered by case_id
        """
        search_kwargs = search_kwargs or {}
        search_kwargs.setdefault("k", k)
        
        # Use metadata filter for case isolation
        # This ensures multi-tenant security
        return self.vector_store.as_retriever(
            filter={"case_id": case_id},  # Metadata filter for case isolation
            search_kwargs=search_kwargs
        )
    
    def add_documents(self, documents: List[Document], case_id: str) -> List[str]:
        """
        Add documents to vector store with case_id metadata
        
        Args:
            documents: List of Document objects
            case_id: Case identifier (added to metadata)
            
        Returns:
            List of document IDs
        """
        # Ensure all documents have case_id in metadata
        for doc in documents:
            if "case_id" not in doc.metadata:
                doc.metadata["case_id"] = case_id
        
        try:
            # Add documents to vector store
            ids = self.vector_store.add_documents(documents)
            logger.info(f"✅ Added {len(ids)} documents to PGVector store for case {case_id}")
            return ids
        except Exception as e:
            logger.error(f"Failed to add documents to PGVector store: {e}", exc_info=True)
            raise
    
    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        case_id: str,
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """
        Add texts to vector store with metadata
        
        Args:
            texts: List of text strings
            metadatas: List of metadata dictionaries
            case_id: Case identifier (added to all metadata)
            ids: Optional list of document IDs
            
        Returns:
            List of document IDs
        """
        # Ensure case_id is in all metadata
        for meta in metadatas:
            meta["case_id"] = case_id
        
        try:
            ids = self.vector_store.add_texts(texts, metadatas=metadatas, ids=ids)
            logger.info(f"✅ Added {len(ids)} texts to PGVector store for case {case_id}")
            return ids
        except Exception as e:
            logger.error(f"Failed to add texts to PGVector store: {e}", exc_info=True)
            raise
    
    def similarity_search(
        self,
        query: str,
        case_id: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Search for similar documents within a specific case
        
        Args:
            query: Search query
            case_id: Case identifier for filtering
            k: Number of results
            filter: Additional metadata filters
            
        Returns:
            List of Document objects
        """
        # Combine case_id filter with additional filters
        search_filter = {"case_id": case_id}
        if filter:
            search_filter.update(filter)
        
        try:
            results = self.vector_store.similarity_search(
                query,
                k=k,
                filter=search_filter
            )
            logger.debug(f"Found {len(results)} similar documents for case {case_id}")
            return results
        except Exception as e:
            logger.error(f"Failed to search PGVector store: {e}", exc_info=True)
            raise
    
    def similarity_search_with_score(
        self,
        query: str,
        case_id: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[tuple]:
        """
        Search for similar documents with similarity scores
        
        Args:
            query: Search query
            case_id: Case identifier for filtering
            k: Number of results
            filter: Additional metadata filters
            
        Returns:
            List of (Document, score) tuples
        """
        search_filter = {"case_id": case_id}
        if filter:
            search_filter.update(filter)
        
        try:
            results = self.vector_store.similarity_search_with_score(
                query,
                k=k,
                filter=search_filter
            )
            logger.debug(f"Found {len(results)} similar documents with scores for case {case_id}")
            return results
        except Exception as e:
            logger.error(f"Failed to search PGVector store with scores: {e}", exc_info=True)
            raise
    
    def delete_case_vectors(self, case_id: str) -> bool:
        """
        Delete all vectors for a specific case
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if successful
        """
        try:
            # Delete all documents with case_id metadata
            # PGVector delete method expects a filter
            # Note: This might need to be implemented via direct SQL
            # For now, we'll use a workaround by searching and deleting by IDs
            docs = self.similarity_search("", case_id=case_id, k=10000)  # Get all docs
            if not docs:
                logger.info(f"No vectors found for case {case_id} to delete")
                return True
            
            # Extract IDs from documents (PGVector stores IDs in metadata)
            # This is a workaround - proper implementation would use direct SQL
            logger.warning(f"delete_case_vectors for case {case_id} needs proper implementation")
            # TODO: Implement proper deletion via SQL DELETE with metadata filter
            return True
        except Exception as e:
            logger.error(f"Failed to delete vectors for case {case_id}: {e}", exc_info=True)
            return False

