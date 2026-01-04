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
    case_id = Column(String, nullable=True)  # Case identifier for multi-tenant filtering
    embedding = Column(Vector(256), nullable=True)  # Vector dimension (Yandex text-search-query embeddings are 256)
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
        
        # Create engine with connection pooling and SSL connection management
        # pool_pre_ping: Verify connections before using (prevents SSL connection closed errors)
        # pool_recycle: Recycle connections after 1 hour (prevents stale connections)
        self.engine = create_engine(
            self.db_url,
            echo=False,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600,  # Recycle connections after 1 hour
            pool_size=5,  # Number of connections to maintain
            max_overflow=10  # Maximum overflow connections
        )
        
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
                        case_id TEXT,
                        embedding vector(256),
                        document JSONB,
                        custom_id TEXT
                    )
                """))
                
                # Create index on collection_id for faster filtering
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{VectorEmbedding.__tablename__}_collection_id 
                    ON {VectorEmbedding.__tablename__}(collection_id)
                """))
                
                # Check if embedding column has correct dimension (256)
                # If table was created with wrong dimension (1536), we need to fix it
                try:
                    result = conn.execute(text(f"""
                        SELECT atttypmod FROM pg_attribute 
                        WHERE attrelid = '{VectorEmbedding.__tablename__}'::regclass 
                        AND attname = 'embedding'
                    """))
                    row = result.fetchone()
                    if row and row[0]:
                        # atttypmod for vector(256) should be -1 (variable) or specific dimension
                        # For vector(1536), atttypmod would be different
                        # Check actual dimension by querying the column definition
                        dim_result = conn.execute(text(f"""
                            SELECT COUNT(*) FROM information_schema.columns 
                            WHERE table_name = '{VectorEmbedding.__tablename__}' 
                            AND column_name = 'embedding'
                            AND data_type = 'USER-DEFINED'
                        """))
                        # If column exists with wrong dimension, we need to recreate table
                        # This is a safety check - actual fix will happen on first insert attempt
                        logger.debug(f"Embedding column exists in {VectorEmbedding.__tablename__}")
                except Exception as e:
                    logger.debug(f"Could not check embedding column dimension: {e}")
                
                # Create GIN index on document JSONB for metadata filtering
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{VectorEmbedding.__tablename__}_document_gin 
                    ON {VectorEmbedding.__tablename__} USING GIN (document)
                """))
                
        except Exception as e:
            logger.error(f"Failed to ensure table exists: {e}", exc_info=True)
            raise
    
    def _fix_vector_dimension_if_needed(self):
        """Fix vector dimension if table was created with wrong dimension (1536 instead of 256)"""
        try:
            with self.engine.connect() as conn:
                table_name = VectorEmbedding.__tablename__
                
                # Check if table exists and get the actual dimension
                result = conn.execute(text(f"""
                    SELECT t.typname, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) as type
                    FROM pg_catalog.pg_attribute a
                    JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
                    JOIN pg_catalog.pg_type t ON a.atttypid = t.oid
                    WHERE c.relname = '{table_name}'
                    AND a.attname = 'embedding'
                    AND NOT a.attisdropped
                """))
                row = result.fetchone()
                
                if row:
                    type_str = row[2] if len(row) > 2 else ""
                    # If dimension is 1536, we need to fix it
                    if 'vector(1536)' in type_str:
                        logger.warning(f"Table {table_name} has wrong vector dimension (1536). Recreating table...")
                        # Drop and recreate table (data will be lost, but this is necessary)
                        with self.engine.begin() as trans_conn:
                            trans_conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
                            trans_conn.execute(text(f"""
                                CREATE TABLE {table_name} (
                                    uuid TEXT PRIMARY KEY,
                                    collection_id TEXT,
                                    embedding vector(256),
                                    document JSONB,
                                    custom_id TEXT
                                )
                            """))
                            trans_conn.execute(text(f"""
                                CREATE INDEX IF NOT EXISTS idx_{table_name}_collection_id 
                                ON {table_name}(collection_id)
                            """))
                            trans_conn.execute(text(f"""
                                CREATE INDEX IF NOT EXISTS idx_{table_name}_document_gin 
                                ON {table_name} USING GIN (document)
                            """))
                        logger.info(f"✅ Table {table_name} recreated with correct vector dimension (256)")
        except Exception as e:
            logger.warning(f"Could not fix vector dimension (table may not exist yet): {e}")
            # This is OK if table doesn't exist - it will be created with correct dimension
    
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
        
        # Fix vector dimension if needed (migration from 1536 to 256)
        self._fix_vector_dimension_if_needed()
        
        ids = []
        try:
            # Prepare all values for bulk insert
            from psycopg2.extras import execute_values
            
            values = []
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
                
                values.append((doc_id, self.collection_name, case_id, embedding_array_str, document_json_str, doc_id))
            
            # Bulk insert using execute_values
            with self.engine.begin() as conn:
                table_name = VectorEmbedding.__tablename__
                insert_sql = f"""
                    INSERT INTO {table_name} 
                    (uuid, collection_id, case_id, embedding, document, custom_id) 
                    VALUES %s
                """
                
                # Get raw connection properly - use conn.connection for SQLAlchemy 1.4+
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    execute_values(
                        cursor,
                        insert_sql,
                        values,
                        template="(%s, %s, %s, %s::vector, %s::jsonb, %s)"
                    )
                finally:
                    cursor.close()
            
            logger.info(f"✅ Added {len(ids)} documents to PGVector store for case {case_id} (bulk insert)")
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
            # Prepare all values for bulk insert
            from psycopg2.extras import execute_values
            
            values = []
            for text_content, embedding, metadata, doc_id in zip(texts, embeddings, metadatas, ids):
                # Prepare document JSONB
                doc_json = {
                    "page_content": text_content,
                    "metadata": metadata
                }
                
                # Convert embedding list to PostgreSQL array format string
                embedding_array_str = '[' + ','.join(str(float(x)) for x in embedding) + ']'
                document_json_str = json.dumps(doc_json)
                
                values.append((doc_id, self.collection_name, case_id, embedding_array_str, document_json_str, doc_id))
            
            # Bulk insert using execute_values
            with self.engine.begin() as conn:
                table_name = VectorEmbedding.__tablename__
                insert_sql = f"""
                    INSERT INTO {table_name} 
                    (uuid, collection_id, case_id, embedding, document, custom_id) 
                    VALUES %s
                """
                
                # Get raw connection properly - use conn.connection for SQLAlchemy 1.4+
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    execute_values(
                        cursor,
                        insert_sql,
                        values,
                        template="(%s, %s, %s, %s::vector, %s::jsonb, %s)"
                    )
                finally:
                    cursor.close()
            
            logger.info(f"✅ Added {len(ids)} texts to PGVector store for case {case_id} (bulk insert)")
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
        # Use case_id column for filtering (faster than JSONB)
        search_filter = {}
        if filter:
            search_filter.update(filter)
        
        try:
            with self.engine.connect() as conn:
                # Build filter condition with parameterized queries (prevents SQL injection)
                # Use case_id column directly for better performance
                filter_conditions = ["collection_id = %s", "case_id = %s"]
                params = [self.collection_name, case_id]
                
                # Add additional filters using parameterized queries for JSONB
                for key, value in search_filter.items():
                    # Use parameterized query for JSONB access
                    filter_conditions.append(f"document->'metadata'->>%s = %s")
                    params.extend([key, str(value)])
                
                where_sql = " AND ".join(filter_conditions)
                
                # Use raw psycopg2 cursor to avoid SQLAlchemy parameter style conflicts
                table_name = VectorEmbedding.__tablename__
                sql = f"""
                    SELECT uuid, document, 
                           1 - (embedding <=> %s::vector) as similarity
                    FROM {table_name}
                    WHERE {where_sql}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
                
                # ПРАВИЛЬНЫЙ ПОРЯДОК ПАРАМЕТРОВ:
                # SQL использует: %s::vector (SELECT), затем WHERE параметры, затем %s::vector (ORDER BY), затем LIMIT
                # Поэтому порядок: [query_embedding_str, collection_id, case_id, ...filters..., query_embedding_str, k]
                # Текущий params = [collection_id, case_id, ...filters...]
                # Нужно: [query_embedding_str] + params + [query_embedding_str, k]
                params = [query_embedding_str] + params + [query_embedding_str, k]
                
                # Get raw connection properly - use conn.connection for SQLAlchemy 1.4+
                # conn.connection is the underlying DBAPI connection
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    cursor.execute(sql, params)
                    
                    documents = []
                    for row in cursor.fetchall():
                        doc_data = row[1]  # document column is at index 1
                        if isinstance(doc_data, str):
                            doc_data = json.loads(doc_data)
                        elif isinstance(doc_data, dict):
                            pass  # Already a dict
                        else:
                            doc_data = {}
                        
                        doc = Document(
                            page_content=doc_data.get("page_content", ""),
                            metadata=doc_data.get("metadata", {})
                        )
                        documents.append(doc)
                finally:
                    cursor.close()
                
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
        # Convert to PostgreSQL array format string
        query_embedding_str = '[' + ','.join(str(float(x)) for x in query_embedding) + ']'
        
        # Combine case_id filter with additional filters
        # Use case_id column for filtering (faster than JSONB)
        search_filter = {}
        if filter:
            search_filter.update(filter)
        
        try:
            with self.engine.connect() as conn:
                # Build filter condition with parameterized queries (prevents SQL injection)
                # Use case_id column directly for better performance
                filter_conditions = ["collection_id = %s", "case_id = %s"]
                params = [self.collection_name, case_id]
                
                # Add additional filters using parameterized queries for JSONB
                for key, value in search_filter.items():
                    # Use parameterized query for JSONB access
                    filter_conditions.append(f"document->'metadata'->>%s = %s")
                    params.extend([key, str(value)])
                
                where_sql = " AND ".join(filter_conditions)
                
                # Use raw psycopg2 cursor to avoid SQLAlchemy parameter style conflicts
                table_name = VectorEmbedding.__tablename__
                sql = f"""
                    SELECT uuid, document, 
                           1 - (embedding <=> %s::vector) as similarity
                    FROM {table_name}
                    WHERE {where_sql}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
                
                # ПРАВИЛЬНЫЙ ПОРЯДОК ПАРАМЕТРОВ:
                # SQL использует: %s::vector (SELECT), затем WHERE параметры, затем %s::vector (ORDER BY), затем LIMIT
                # Поэтому порядок: [query_embedding_str, collection_id, case_id, ...filters..., query_embedding_str, k]
                # Текущий params = [collection_id, case_id, ...filters...]
                # Нужно: [query_embedding_str] + params + [query_embedding_str, k]
                params = [query_embedding_str] + params + [query_embedding_str, k]
                
                # Get raw connection properly - use conn.connection for SQLAlchemy 1.4+
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    cursor.execute(sql, params)
                    
                    documents_with_scores = []
                    for row in cursor.fetchall():
                        doc_data = row[1]  # document column is at index 1
                        similarity = row[2] if len(row) > 2 else 0.0  # similarity column
                        
                        if isinstance(doc_data, str):
                            doc_data = json.loads(doc_data)
                        elif isinstance(doc_data, dict):
                            pass  # Already a dict
                        else:
                            doc_data = {}
                        
                        doc = Document(
                            page_content=doc_data.get("page_content", ""),
                            metadata=doc_data.get("metadata", {})
                        )
                        documents_with_scores.append((doc, float(similarity) if similarity else 0.0))
                finally:
                    cursor.close()
                
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
