"""PGVector Vector Store service for multi-tenant document storage using direct SQLAlchemy approach"""
from typing import Any, Dict, List, Optional, Sequence
import threading
import logging
import json
import uuid
import re

from sqlalchemy.orm import Session
from sqlalchemy import text, Column, String, JSON, bindparam, Table, MetaData
from sqlalchemy.ext.declarative import declarative_base
from langchain_core.documents import Document
from pgvector.sqlalchemy import Vector

from app.config import config
from app.services.yandex_embeddings import get_yandex_embeddings
from app.utils.database import engine as _shared_db_engine

logger = logging.getLogger(__name__)

# One engine for the whole app: each ``CaseVectorStore()`` used to call ``create_engine()`` and
# open a *new* pool (5 + 10 overflow per instance). Parallel HTTP handlers then multiplied
# connections to Neon/serverless Postgres, hit connection limits, and the server started closing
# sockets — including LangGraph's AsyncPostgresSaver pool (OperationalError).
_pgvector_schema_lock = threading.Lock()
_pgvector_schema_ready = False
_case_vector_store_lock = threading.Lock()
_case_vector_store_singleton: Optional["CaseVectorStore"] = None

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
            self.embeddings = get_yandex_embeddings()
        else:
            self.embeddings = embeddings

        self.engine = _shared_db_engine

        # Collection name for storing vectors
        self.collection_name = "legal_ai_vault_vectors"

        global _pgvector_schema_ready
        with _pgvector_schema_lock:
            if not _pgvector_schema_ready:
                self._ensure_table_exists()
                _pgvector_schema_ready = True

        if not getattr(CaseVectorStore, "_ready_logged", False):
            logger.info("✅ PGVector store ready (shared SQLAlchemy engine / single pool)")
            CaseVectorStore._ready_logged = True
    
    def _ensure_table_exists(self):
        """Ensure the vector embedding table exists"""
        try:
            table = VectorEmbedding.__tablename__

            # IMPORTANT:
            # - Any SQL error inside a transaction marks it as "aborted" in Postgres.
            # - Even if Python catches an exception, subsequent commands in the same transaction
            #   will fail with InFailedSqlTransaction.
            # Therefore we keep "must-succeed" DDL (table/columns/migration) in a transaction,
            # and run "best-effort" index creation in independent AUTOCOMMIT statements.
            with self.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

                conn.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            uuid TEXT PRIMARY KEY,
                            collection_id TEXT,
                            case_id TEXT,
                            embedding vector(256),
                            document JSONB,
                            custom_id TEXT
                        )
                        """
                    )
                )

                # Migration: earlier deployments created `document` as JSON (not JSONB).
                try:
                    dt_row = conn.execute(
                        text(
                            """
                            SELECT data_type
                            FROM information_schema.columns
                            WHERE table_name = :table_name
                              AND column_name = 'document'
                            """
                        ),
                        {"table_name": table},
                    ).fetchone()
                    data_type = (dt_row[0] if dt_row else None) if dt_row is not None else None
                    if str(data_type).lower() == "json":
                        conn.execute(
                            text(
                                f"""
                                ALTER TABLE {table}
                                ALTER COLUMN document TYPE JSONB
                                USING document::jsonb
                                """
                            )
                        )
                        logger.info("✅ Migrated %s.document from JSON to JSONB", table)
                except Exception as e:
                    logger.warning("Could not verify/migrate %s.document JSON→JSONB: %s", table, e)

                # Ensure case_id exists even on older schemas.
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS case_id TEXT"))
                    logger.info("✅ Ensured case_id column exists in %s", table)
                except Exception as e:
                    logger.debug("Could not add case_id column (may already exist): %s", e)

                # Non-risky B-tree indexes (keep in the transaction).
                conn.execute(
                    text(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_{table}_collection_id
                        ON {table}(collection_id)
                        """
                    )
                )
                try:
                    conn.execute(
                        text(
                            f"""
                            CREATE INDEX IF NOT EXISTS idx_{table}_case_id
                            ON {table}(case_id)
                            """
                        )
                    )
                except Exception as e:
                    logger.debug("Could not create case_id index: %s", e)

                # Optional: dimension sanity check (debug only).
                try:
                    conn.execute(
                        text(
                            f"""
                            SELECT atttypmod
                            FROM pg_attribute
                            WHERE attrelid = '{table}'::regclass
                              AND attname = 'embedding'
                            """
                        )
                    ).fetchone()
                except Exception as e:
                    logger.debug("Could not check embedding column dimension: %s", e)

            # Best-effort indexes: run outside the main transaction using AUTOCOMMIT.
            try:
                with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    try:
                        conn.execute(
                            text(
                                f"""
                                CREATE INDEX IF NOT EXISTS idx_{table}_document_gin
                                ON {table} USING GIN (document)
                                """
                            )
                        )
                    except Exception as e:
                        logger.warning("Could not create document GIN index: %s", e, exc_info=True)

                    try:
                        conn.execute(
                            text(
                                f"""
                                CREATE INDEX IF NOT EXISTS idx_{table}_fts
                                ON {table}
                                USING GIN (to_tsvector('russian', COALESCE(document->>'page_content', '')))
                                """
                            )
                        )
                    except Exception as e:
                        logger.warning("Could not create FTS index: %s", e, exc_info=True)
            except Exception as e:
                logger.warning("Could not create PGVector best-effort indexes (autocommit): %s", e, exc_info=True)
                
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
        from typing import ClassVar
        
        # Сохраняем ссылки в локальные переменные для closure
        _vector_store = self
        _case_id = case_id
        _k = k
        
        class CaseRetriever(BaseRetriever):
            """
            Простой retriever для case-specific поиска.
            Использует closure вместо instance переменных из-за ограничений Pydantic в BaseRetriever.
            """
            
            # Для Pydantic v2 - разрешаем произвольные типы
            model_config: ClassVar[dict] = {"arbitrary_types_allowed": True}
            
            def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun = None):
                return _vector_store.similarity_search(query, _case_id, k=_k)
        
        return CaseRetriever()
    
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
        
        # Create embeddings (optional Hidden Context: metadata["embedding_text"])
        texts: List[str] = []
        for doc in documents:
            md = doc.metadata or {}
            et = md.get("embedding_text")
            if isinstance(et, str) and et.strip():
                texts.append(et.strip())
            else:
                texts.append(doc.page_content or "")
        from app.services.file_processing_concurrency import embedding_index_slot

        with embedding_index_slot():
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
        from app.services.file_processing_concurrency import embedding_index_slot

        with embedding_index_slot():
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
    
    def _embedding_vector_literal(self, query_embedding: Sequence[float]) -> str:
        return "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

    def similarity_search_by_vector(
        self,
        query_embedding: Sequence[float],
        case_id: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Dense search with a precomputed query vector (tabular column runs, cached queries)."""
        query_embedding_str = self._embedding_vector_literal(query_embedding)
        search_filter = dict(filter or {})
        try:
            with self.engine.connect() as conn:
                filter_conditions = ["collection_id = %s", "case_id = %s"]
                params = [self.collection_name, case_id]

                for key, value in search_filter.items():
                    if isinstance(value, (list, tuple, set)):
                        values = [str(v) for v in value if str(v).strip()]
                        if not values:
                            continue
                        placeholders = ", ".join(["%s"] * len(values))
                        filter_conditions.append(
                            f"document->'metadata'->>%s IN ({placeholders})"
                        )
                        params.append(key)
                        params.extend(values)
                        continue
                    filter_conditions.append("document->'metadata'->>%s = %s")
                    params.extend([key, str(value)])

                where_sql = " AND ".join(filter_conditions)
                table_name = VectorEmbedding.__tablename__
                sql = f"""
                    SELECT uuid, document,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM {table_name}
                    WHERE {where_sql}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
                params = [query_embedding_str] + params + [query_embedding_str, k]
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    cursor.execute(sql, params)
                    documents = []
                    for row in cursor.fetchall():
                        doc_data = row[1]
                        if isinstance(doc_data, str):
                            doc_data = json.loads(doc_data)
                        elif not isinstance(doc_data, dict):
                            doc_data = {}
                        documents.append(
                            Document(
                                page_content=doc_data.get("page_content", ""),
                                metadata=doc_data.get("metadata", {}),
                            )
                        )
                finally:
                    cursor.close()
                logger.debug(
                    "Found %s similar documents for case %s (precomputed vector)",
                    len(documents),
                    case_id,
                )
                return documents
        except Exception as e:
            logger.error(f"Failed vector search in PGVector store: {e}", exc_info=True)
            raise

    def similarity_search(
        self,
        query: str,
        case_id: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[Sequence[float]] = None,
    ) -> List[Document]:
        """
        Search for similar documents within a specific case
        
        Args:
            query: Search query
            case_id: Case identifier for filtering
            k: Number of results
            filter: Additional metadata filters
            query_embedding: Optional precomputed query vector (skips embed_query)
            
        Returns:
            List of Document objects
        """
        if query_embedding is None:
            query_embedding = self.embeddings.embed_query(query)
        return self.similarity_search_by_vector(
            query_embedding,
            case_id=case_id,
            k=k,
            filter=filter,
        )
    
    def similarity_search_with_score(
        self,
        query: str,
        case_id: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[Sequence[float]] = None,
    ) -> List[tuple]:
        """
        Search for similar documents with similarity scores
        
        Args:
            query: Search query
            case_id: Case identifier for filtering
            k: Number of results
            filter: Additional metadata filters
            query_embedding: Optional precomputed query vector
            
        Returns:
            List of (Document, score) tuples
        """
        if query_embedding is None:
            query_embedding = self.embeddings.embed_query(query)
        query_embedding_str = self._embedding_vector_literal(query_embedding)
        
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
                    if isinstance(value, (list, tuple, set)):
                        values = [str(v) for v in value if str(v).strip()]
                        if not values:
                            continue
                        placeholders = ", ".join(["%s"] * len(values))
                        filter_conditions.append(
                            f"document->'metadata'->>%s IN ({placeholders})"
                        )
                        params.append(key)
                        params.extend(values)
                        continue
                    # Use parameterized query for JSONB access
                    filter_conditions.append("document->'metadata'->>%s = %s")
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

    def keyword_search(
        self,
        query: str,
        case_id: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        PostgreSQL Full-Text Search (FTS) over stored page_content.

        Uses websearch_to_tsquery for robust parsing of user queries and ranks
        matches with ts_rank_cd.
        """
        search_filter = {}
        if filter:
            search_filter.update(filter)
        try:
            with self.engine.connect() as conn:
                filter_conditions = ["collection_id = %s", "case_id = %s"]
                params = [self.collection_name, case_id]
                for key, value in search_filter.items():
                    if isinstance(value, (list, tuple, set)):
                        values = [str(v) for v in value if str(v).strip()]
                        if not values:
                            continue
                        placeholders = ", ".join(["%s"] * len(values))
                        filter_conditions.append(
                            f"document->'metadata'->>%s IN ({placeholders})"
                        )
                        params.append(key)
                        params.extend(values)
                        continue
                    filter_conditions.append("document->'metadata'->>%s = %s")
                    params.extend([key, str(value)])

                where_sql = " AND ".join(filter_conditions)
                table_name = VectorEmbedding.__tablename__
                sql = f"""
                    SELECT
                        document,
                        ts_rank_cd(
                            to_tsvector('russian', COALESCE(document->>'page_content', '')),
                            websearch_to_tsquery('russian', %s)
                        ) AS fts_rank
                    FROM {table_name}
                    WHERE {where_sql}
                      AND to_tsvector('russian', COALESCE(document->>'page_content', ''))
                          @@ websearch_to_tsquery('russian', %s)
                    ORDER BY fts_rank DESC
                    LIMIT %s
                """
                # query in SELECT rank + query in WHERE + k limit
                sql_params = [query] + params + [query, k]
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    cursor.execute(sql, sql_params)
                    docs: List[Document] = []
                    for row in cursor.fetchall():
                        doc_data = row[0]
                        fts_rank = row[1] if len(row) > 1 else 0.0
                        if isinstance(doc_data, str):
                            doc_data = json.loads(doc_data)
                        elif not isinstance(doc_data, dict):
                            doc_data = {}
                        doc = Document(
                            page_content=doc_data.get("page_content", ""),
                            metadata=doc_data.get("metadata", {}),
                        )
                        doc.metadata["fts_rank"] = float(fts_rank or 0.0)
                        docs.append(doc)
                finally:
                    cursor.close()
                return docs
        except Exception as e:
            logger.error("Failed to run PostgreSQL FTS search: %s", e, exc_info=True)
            return []

    def anchor_substring_search(
        self,
        *,
        query: str,
        case_id: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Deterministic substring retrieval for "address/anchor" queries like "пункт 6.8", "6.8.1", etc.

        Motivation:
        - Vector similarity is not reliable for purely-address queries.
        - FTS (websearch_to_tsquery) can miss numeric dotted anchors depending on parsing.
        - Substring match guarantees recall when the anchor exists in chunk text.
        """
        q = (query or "").strip()
        if not q:
            return []

        anchors = re.findall(r"\b\d+(?:[.,]\d+)+\b", q)
        if not anchors:
            return []

        # Small set of tolerant variants (dot/comma differences).
        patterns: List[str] = []
        seen = set()
        for a in anchors[:5]:
            for v in (a, a.replace(",", "."), a.replace(".", ",")):
                v = v.strip()
                if not v or v in seen:
                    continue
                seen.add(v)
                patterns.append(v)

        if not patterns:
            return []

        search_filter: Dict[str, Any] = {}
        if filter:
            search_filter.update(filter)

        try:
            with self.engine.connect() as conn:
                filter_conditions = ["collection_id = %s", "case_id = %s"]
                params: List[Any] = [self.collection_name, case_id]

                for key, value in search_filter.items():
                    if isinstance(value, (list, tuple, set)):
                        values = [str(v) for v in value if str(v).strip()]
                        if not values:
                            continue
                        placeholders = ", ".join(["%s"] * len(values))
                        filter_conditions.append(
                            f"document->'metadata'->>%s IN ({placeholders})"
                        )
                        params.append(key)
                        params.extend(values)
                        continue
                    filter_conditions.append("document->'metadata'->>%s = %s")
                    params.extend([key, str(value)])

                where_sql = " AND ".join(filter_conditions)
                table_name = VectorEmbedding.__tablename__

                or_clauses: List[str] = []
                pos_exprs: List[str] = []
                like_params: List[Any] = []
                pos_params: List[Any] = []

                for p in patterns:
                    or_clauses.append("COALESCE(document->>'page_content','') ILIKE %s")
                    like_params.append(f"%{p}%")
                    pos_exprs.append(
                        "NULLIF(POSITION(lower(%s) IN lower(COALESCE(document->>'page_content',''))), 0)"
                    )
                    pos_params.append(p)

                # Order by earliest anchor position in text (smaller is better).
                min_pos_sql = "LEAST(" + ", ".join([f"COALESCE({e}, 2147483647)" for e in pos_exprs]) + ")"

                sql = f"""
                    SELECT
                        document,
                        {min_pos_sql} AS anchor_pos
                    FROM {table_name}
                    WHERE {where_sql}
                      AND ({' OR '.join(or_clauses)})
                    ORDER BY anchor_pos ASC
                    LIMIT %s
                """

                # Parameter order must match placeholder order in SQL *appearance*.
                # Placeholders in the SELECT list appear before placeholders in WHERE.
                # Order:
                # - POSITION needles used in SELECT (min_pos_sql),
                # - THEN WHERE params (collection_id, case_id, metadata_filter),
                # - THEN ILIKE patterns used in WHERE,
                # - THEN LIMIT.
                sql_params = pos_params + params + like_params + [k]
                raw_conn = conn.connection
                cursor = raw_conn.cursor()
                try:
                    cursor.execute(sql, sql_params)
                    docs: List[Document] = []
                    for row in cursor.fetchall():
                        doc_data = row[0]
                        anchor_pos = row[1] if len(row) > 1 else None

                        if isinstance(doc_data, str):
                            doc_data = json.loads(doc_data)
                        elif not isinstance(doc_data, dict):
                            doc_data = {}

                        doc = Document(
                            page_content=doc_data.get("page_content", "") or "",
                            metadata=doc_data.get("metadata", {}) or {},
                        )
                        try:
                            doc.metadata["anchor_pos"] = int(anchor_pos) if anchor_pos is not None else None
                        except Exception:
                            doc.metadata["anchor_pos"] = None
                        docs.append(doc)
                finally:
                    cursor.close()

                return docs
        except Exception as e:
            logger.error("anchor_substring_search failed: %s", e, exc_info=True)
            return []
    
    def list_case_chunks(
        self,
        case_id: str,
        *,
        limit: int = 2500,
        chunk_levels: Optional[List[str]] = None,
    ) -> List[Document]:
        """
        Все чанки дела из PGVector для построения in-memory BM25.

        Порядок стабильный: file_id → chunk_index → uuid.
        """
        cid = str(case_id or "").strip()
        if not cid:
            return []
        lim = max(1, min(int(limit or 2500), 10_000))
        try:
            table_name = VectorEmbedding.__tablename__
            filter_conditions = ["collection_id = :collection_id", "case_id = :case_id"]
            params: Dict[str, Any] = {
                "collection_id": self.collection_name,
                "case_id": cid,
                "lim": lim,
            }
            if chunk_levels:
                levels = [str(v).strip() for v in chunk_levels if str(v).strip()]
                if levels:
                    filter_conditions.append(
                        "document->'metadata'->>'chunk_level' = ANY(:chunk_levels)"
                    )
                    params["chunk_levels"] = levels

            where_sql = " AND ".join(filter_conditions)
            sql = text(f"""
                SELECT document
                FROM {table_name}
                WHERE {where_sql}
                ORDER BY
                    COALESCE(document->'metadata'->>'file_id', ''),
                    COALESCE((document->'metadata'->>'chunk_index')::int, 2147483647),
                    uuid
                LIMIT :lim
            """)
            with self.engine.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            docs: List[Document] = []
            for row in rows:
                doc_data = row[0]
                if isinstance(doc_data, str):
                    doc_data = json.loads(doc_data)
                elif not isinstance(doc_data, dict):
                    continue
                docs.append(
                    Document(
                        page_content=doc_data.get("page_content", "") or "",
                        metadata=dict(doc_data.get("metadata") or {}),
                    )
                )
            logger.debug("list_case_chunks case=%s count=%s", cid, len(docs))
            return docs
        except Exception as e:
            logger.error("list_case_chunks failed case=%s: %s", cid, e, exc_info=True)
            return []

    def list_chunks_by_file(self, case_id: str, file_id: str) -> List[Document]:
        """
        Все проиндексированные чанки файла в PGVector (порядок как при индексации: chunk_index, uuid).

        Используется лабораторией чанков / отладкой цитат; не для retrieval по смыслу.
        """
        fid = str(file_id).strip()
        if not fid:
            return []
        try:
            table_name = VectorEmbedding.__tablename__
            sql = text(f"""
                SELECT document
                FROM {table_name}
                WHERE collection_id = :collection_id
                  AND case_id = :case_id
                  AND document->'metadata'->>'file_id' = :file_id
                ORDER BY COALESCE((document->'metadata'->>'chunk_index')::int, 2147483647), uuid
            """)
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {
                        "collection_id": self.collection_name,
                        "case_id": str(case_id),
                        "file_id": fid,
                    },
                ).fetchall()
            docs: List[Document] = []
            for row in rows:
                doc_data = row[0]
                if isinstance(doc_data, str):
                    doc_data = json.loads(doc_data)
                elif not isinstance(doc_data, dict):
                    continue
                docs.append(
                    Document(
                        page_content=doc_data.get("page_content", "") or "",
                        metadata=dict(doc_data.get("metadata") or {}),
                    )
                )
            return docs
        except Exception as e:
            logger.error("list_chunks_by_file failed case=%s file=%s: %s", case_id, fid, e, exc_info=True)
            return []

    def fetch_macro_chunks_by_macro_ids(
        self,
        case_id: str,
        macro_ids: Sequence[str],
    ) -> Dict[str, Document]:
        """
        Load macro (parent) chunks by stable macro_id for context resolution after micro rerank.

        Returns mapping macro_id -> Document (chunk_level=macro).
        """
        cid = str(case_id or "").strip()
        ids = list(dict.fromkeys(str(x).strip() for x in macro_ids if str(x).strip()))
        if not cid or not ids:
            return {}
        try:
            table_name = VectorEmbedding.__tablename__
            sql = text(f"""
                SELECT document
                FROM {table_name}
                WHERE collection_id = :collection_id
                  AND case_id = :case_id
                  AND document->'metadata'->>'chunk_level' = 'macro'
                  AND document->'metadata'->>'macro_id' = ANY(:macro_ids)
            """)
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {
                        "collection_id": self.collection_name,
                        "case_id": cid,
                        "macro_ids": ids,
                    },
                ).fetchall()
            out: Dict[str, Document] = {}
            for row in rows:
                doc_data = row[0]
                if isinstance(doc_data, str):
                    doc_data = json.loads(doc_data)
                elif not isinstance(doc_data, dict):
                    continue
                doc = Document(
                    page_content=doc_data.get("page_content", "") or "",
                    metadata=dict(doc_data.get("metadata") or {}),
                )
                mid = str((doc.metadata or {}).get("macro_id") or "").strip()
                if mid and mid not in out:
                    out[mid] = doc
            logger.debug(
                "fetch_macro_chunks_by_macro_ids case=%s requested=%s found=%s",
                cid,
                len(ids),
                len(out),
            )
            return out
        except Exception as e:
            logger.error(
                "fetch_macro_chunks_by_macro_ids failed case=%s: %s", cid, e, exc_info=True
            )
            return {}

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

    def delete_file_vectors(self, file_id: str) -> bool:
        """Delete all vector chunks for a specific file (before reindexing)."""
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"""
                        DELETE FROM {VectorEmbedding.__tablename__}
                        WHERE collection_id = :collection_id
                          AND document->'metadata'->>'file_id' = :file_id
                    """),
                    {"collection_id": self.collection_name, "file_id": file_id}
                )
            logger.info(f"✅ Deleted vectors for file {file_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete vectors for file {file_id}: {e}", exc_info=True)
            return False


def get_case_vector_store(*, embeddings=None) -> CaseVectorStore:
    """
    Shared CaseVectorStore on the app-wide SQLAlchemy engine (single connection pool).

    Legal corpus retrieval may issue many FTS lookups per request; reusing one store
    avoids redundant schema checks and repeated pool setup.
    """
    global _case_vector_store_singleton
    if embeddings is not None:
        return CaseVectorStore(embeddings=embeddings)
    with _case_vector_store_lock:
        if _case_vector_store_singleton is None:
            _case_vector_store_singleton = CaseVectorStore()
        return _case_vector_store_singleton
