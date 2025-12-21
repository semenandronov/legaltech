"""PGVector Vector Store service for multi-tenant document storage using direct SQLAlchemy approach"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text, Column, String, JSON, bindparam, Table, MetaData
from sqlalchemy.ext.declarative import declarative_base
from langchain_core.documents import Document
from app.config import config
from app.services.yandex_embeddings import YandexEmbeddings
import logging
import json
import uuid
from pgvector.sqlalchemy import Vector

logger = logging.getLogger(__name__)

# Base for vector store table
VectorBase = declarative_base()


class VectorEmbedding(VectorBase):
    """SQLAlchemy model for vector embeddings"""
    __tablename__ = "langchain_pg_embedding"
    
    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id = Column(String, nullable=True)
    embedding = Column(Vector(1536), nullable=True)  # Vector dimension (Yandex embeddings are 1536)
    document = Column(JSON, nullable=True)
    custom_id = Column(String, nullable=True)


class CaseVectorStore:
    """
    Multi-tenant PGVector store for case-specific document embeddings
    
    Uses direct SQLAlchemy approach instead of langchain-postgres to avoid dependency conflicts.
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
        
        # Create engine for direct SQL operations
        self.db_url = config.DATABASE_URL
        # Ensure postgresql:// format (not postgresql+psycopg://)
        if self.db_url.startswith("postgresql+psycopg://"):
            self.db_url = self.db_url.replace("postgresql+psycopg://", "postgresql://")
        
        self.engine = create_engine(self.db_url, echo=False)
        
        # Collection name for storing vectors
        self.collection_name = "legal_ai_vault_vectors"
        
        # Ensure table exists
        self._ensure_table_exists()
        
        logger.info("✅ PGVector store initialized successfully (direct SQLAlchemy approach)")
    
    def _ensure_table_exists(self):
        """Ensure the vector embedding table exists"""
        try:
            with self.engine.begin() as conn:
                # Check if pgvector extension exists
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                
                # Create table if it doesn't exist
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {VectorEmbedding.__tablename__} (
                        uuid TEXT PRIMARY KEY,
                        collection_id TEXT,
                        embedding vector(1536),
                        document JSONB,
                        custom_id TEXT
                    )
                """))
                
                # Create index on collection_id for faster filtering
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{VectorEmbedding.__tablename__}_collection_id 
                    ON {VectorEmbedding.__tablename__}(collection_id)
                """))
                
                # Create GIN index on document JSONB for metadata filtering
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{VectorEmbedding.__tablename__}_document_gin 
                    ON {VectorEmbedding.__tablename__} USING GIN (document)
                """))
                
        except Exception as e:
            logger.error(f"Failed to ensure table exists: {e}", exc_info=True)
            raise
    
    def get_retriever(self, case_id: str, k: int = 5, search_kwargs: Optional[Dict] = None):
        """
        Get retriever for a specific case with metadata filtering
        
        Note: This returns a simple retriever-like object for compatibility
        """
        from langchain_core.retrievers import BaseRetriever
        from langchain_core.callbacks import CallbackManagerForRetrieverRun
        
        class CaseRetriever(BaseRetriever):
            def __init__(self, vector_store, case_id, k):
                super().__init__()
                self.vector_store = vector_store
                self.case_id = case_id
                self.k = k
            
            def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun):
                return self.vector_store.similarity_search(query, self.case_id, k=self.k)
        
        return CaseRetriever(self, case_id, k)
    
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
        
        # Create embeddings
        texts = [doc.page_content for doc in documents]
        embeddings = self.embeddings.embed_documents(texts)
        
        ids = []
        try:
            with self.engine.begin() as conn:
                for doc, embedding in zip(documents, embeddings):
                    doc_id = str(uuid.uuid4())
                    ids.append(doc_id)
                    
                    # Prepare document JSONB
                    doc_json = {
                        "page_content": doc.page_content,
                        "metadata": doc.metadata
                    }
                    
                    # Convert embedding list to PostgreSQL array format string
                    embedding_array_str = '[' + ','.join(str(float(x)) for x in embedding) + ']'
                    document_json_str = json.dumps(doc_json)
                    
                    # Insert into database - use explicit parameter binding with unique parameter names
                    table_name = VectorEmbedding.__tablename__
                    sql_str = (
                        f"INSERT INTO {table_name} "
                        "(uuid, collection_id, embedding, document, custom_id) "
                        "VALUES (:uuid_param, :collection_id_param, :embedding_param::vector, :document_param::jsonb, :custom_id_param)"
                    )
                    stmt = text(sql_str)
                    conn.execute(
                        stmt,
                        {
                            "uuid_param": doc_id,
                            "collection_id_param": self.collection_name,
                            "embedding_param": embedding_array_str,
                            "document_param": document_json_str,
                            "custom_id_param": doc_id
                        }
                    )
            
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
        
        # Create embeddings
        embeddings = self.embeddings.embed_documents(texts)
        
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        
        try:
            with self.engine.begin() as conn:
                for text_content, embedding, metadata, doc_id in zip(texts, embeddings, metadatas, ids):
                    # Prepare document JSONB
                    doc_json = {
                        "page_content": text_content,
                        "metadata": metadata
                    }
                    
                    # Convert embedding list to PostgreSQL array format string
                    embedding_array_str = '[' + ','.join(str(float(x)) for x in embedding) + ']'
                    document_json_str = json.dumps(doc_json)
                    
                    # Insert into database - use explicit parameter binding with unique parameter names
                    table_name = VectorEmbedding.__tablename__
                    sql_str = (
                        f"INSERT INTO {table_name} "
                        "(uuid, collection_id, embedding, document, custom_id) "
                        "VALUES (:uuid_param, :collection_id_param, :embedding_param::vector, :document_param::jsonb, :custom_id_param)"
                    )
                    stmt = text(sql_str)
                    conn.execute(
                        stmt,
                        {
                            "uuid_param": doc_id,
                            "collection_id_param": self.collection_name,
                            "embedding_param": embedding_array_str,
                            "document_param": document_json_str,
                            "custom_id_param": doc_id
                        }
                    )
            
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
        # Create query embedding
        query_embedding = self.embeddings.embed_query(query)
        # Convert to PostgreSQL array format string
        query_embedding_str = '[' + ','.join(str(float(x)) for x in query_embedding) + ']'
        
        # Combine case_id filter with additional filters
        search_filter = {"case_id": case_id}
        if filter:
            search_filter.update(filter)
        
        try:
            with self.engine.connect() as conn:
                # Build filter condition for JSONB
                filter_conditions = []
                for key, value in search_filter.items():
                    filter_conditions.append(f"document->'metadata'->>'{key}' = '{value}'")
                filter_sql = " AND ".join(filter_conditions) if filter_conditions else "1=1"
                
                # Perform similarity search using cosine distance
                # Note: pgvector uses <-> operator for cosine distance (lower is better)
                results = conn.execute(
                    text(f"""
                        SELECT uuid, document, 
                               1 - (embedding <=> :query_embedding::vector) as similarity
                        FROM {VectorEmbedding.__tablename__}
                        WHERE collection_id = :collection_id
                          AND {filter_sql}
                        ORDER BY embedding <=> :query_embedding::vector
                        LIMIT :k
                    """),
                    {
                        "query_embedding": query_embedding_str,
                        "collection_id": self.collection_name,
                        "k": k
                    }
                )
                
                documents = []
                for row in results:
                    doc_data = row.document
                    if isinstance(doc_data, str):
                        doc_data = json.loads(doc_data)
                    
                    doc = Document(
                        page_content=doc_data.get("page_content", ""),
                        metadata=doc_data.get("metadata", {})
                    )
                    documents.append(doc)
                
                logger.debug(f"Found {len(documents)} similar documents for case {case_id}")
                return documents
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
        # Create query embedding
        query_embedding = self.embeddings.embed_query(query)
        
        # Combine case_id filter with additional filters
        search_filter = {"case_id": case_id}
        if filter:
            search_filter.update(filter)
        
        try:
            with self.engine.connect() as conn:
                # Build filter condition for JSONB
                filter_conditions = []
                for key, value in search_filter.items():
                    filter_conditions.append(f"document->'metadata'->>'{key}' = '{value}'")
                filter_sql = " AND ".join(filter_conditions) if filter_conditions else "1=1"
                
                # Perform similarity search with scores
                results = conn.execute(
                    text(f"""
                        SELECT uuid, document, 
                               1 - (embedding <=> :query_embedding::vector) as similarity
                        FROM {VectorEmbedding.__tablename__}
                        WHERE collection_id = :collection_id
                          AND {filter_sql}
                        ORDER BY embedding <=> :query_embedding::vector
                        LIMIT :k
                    """),
                    {
                        "query_embedding": query_embedding_str,
                        "collection_id": self.collection_name,
                        "k": k
                    }
                )
                
                documents_with_scores = []
                for row in results:
                    doc_data = row.document
                    if isinstance(doc_data, str):
                        doc_data = json.loads(doc_data)
                    
                    doc = Document(
                        page_content=doc_data.get("page_content", ""),
                        metadata=doc_data.get("metadata", {})
                    )
                    score = float(row.similarity) if row.similarity is not None else 0.0
                    documents_with_scores.append((doc, score))
                
                logger.debug(f"Found {len(documents_with_scores)} similar documents with scores for case {case_id}")
                return documents_with_scores
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
            with self.engine.begin() as conn:
                # Delete all documents with case_id in metadata
                conn.execute(
                    text(f"""
                        DELETE FROM {VectorEmbedding.__tablename__}
                        WHERE collection_id = :collection_id
                          AND document->'metadata'->>'case_id' = :case_id
                    """),
                    {
                        "collection_id": self.collection_name,
                        "case_id": case_id
                    }
                )
            
            logger.info(f"✅ Deleted all vectors for case {case_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete vectors for case {case_id}: {e}", exc_info=True)
            return False
