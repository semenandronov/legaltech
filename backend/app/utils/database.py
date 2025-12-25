"""Database utilities for Legal AI Vault"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from app.config import config
from app.models.case import Base, Case, ChatMessage, File  # Import models to register them
from app.models.user import User, UserSession  # Import user models to register them
from app.models.analysis import AnalysisResult, Discrepancy, TimelineEvent, DocumentChunk  # Import analysis models to register them
from app.models.tabular_review import TabularReview, TabularColumn, TabularCell, TabularColumnTemplate, TabularDocumentStatus  # Import tabular review models to register them
import logging

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(config.DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema():
    """Ensure required columns and indexes exist"""
    inspector = inspect(engine)
    
    # Ensure pgvector extension is installed
    try:
        with engine.begin() as conn:
            # Check if pgvector extension exists
            result = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            if result.fetchone() is None:
                logger.info("Installing pgvector extension...")
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                logger.info("✅ pgvector extension installed")
            else:
                logger.debug("pgvector extension already installed")
    except Exception as e:
        logger.warning(f"Could not install pgvector extension: {e}. Make sure PostgreSQL has pgvector installed.")
    
    # Ensure chat_messages schema
    if "chat_messages" in inspector.get_table_names():
        columns = {col["name"]: col for col in inspector.get_columns("chat_messages")}
        with engine.begin() as conn:
            if "case_id" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE chat_messages "
                        "ADD COLUMN IF NOT EXISTS case_id TEXT REFERENCES cases(id) ON DELETE CASCADE"
                    )
                )
            # Check if sessionId column exists and if it's NOT NULL, make it nullable
            session_id_col_info = next((col for col in inspector.get_columns("chat_messages") if col["name"] == "sessionId"), None)
            if session_id_col_info:
                # Check if column is NOT NULL and needs to be altered
                if not session_id_col_info.get("nullable", True):
                    logger.info("⚠️  Altering chat_messages.sessionId to be NULLABLE...")
                    try:
                        # Remove NOT NULL constraint
                        conn.execute(text('ALTER TABLE chat_messages ALTER COLUMN "sessionId" DROP NOT NULL'))
                        logger.info("✅ chat_messages.sessionId column altered to NULLABLE")
                    except Exception as e:
                        logger.warning(f"Could not alter sessionId column to NULLABLE: {e}")
                
                # Update any existing NULL sessionId values to use case_id from the same row
                try:
                    conn.execute(
                        text(
                            'UPDATE chat_messages '
                            'SET "sessionId" = case_id '
                            'WHERE "sessionId" IS NULL AND case_id IS NOT NULL'
                        )
                    )
                except Exception as e:
                    logger.warning(f"Could not update NULL sessionId values: {e}")
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chat_messages_case_id "
                    "ON chat_messages(case_id)"
                )
            )
    
    # Ensure cases table has yandex fields
    if "cases" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("cases")]
        with engine.begin() as conn:
            if "yandex_index_id" not in columns:
                conn.execute(
                    text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS yandex_index_id VARCHAR(255)")
                )
            if "yandex_assistant_id" not in columns:
                conn.execute(
                    text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS yandex_assistant_id VARCHAR(255)")
                )
    
    # Create pgvector indexes for optimization
    try:
        with engine.begin() as conn:
            # Check if langchain_pg_embedding table exists (created by langchain-postgres)
            if "langchain_pg_embedding" in inspector.get_table_names():
                # Create GIN index on case_id in metadata for fast filtering
                try:
                    conn.execute(
                        text("""
                            CREATE INDEX IF NOT EXISTS idx_embeddings_case_id 
                            ON langchain_pg_embedding USING GIN ((cmetadata->>'case_id'))
                        """)
                    )
                    logger.info("✅ Created GIN index on case_id metadata")
                except Exception as e:
                    logger.warning(f"Could not create case_id index: {e}")
                
                # Create HNSW index on embedding vector for fast similarity search (if pgvector supports it)
                # Note: HNSW index requires pgvector >= 0.5.0 and may need specific configuration
                try:
                    # Check if embedding column exists and is vector type
                    embedding_cols = inspector.get_columns("langchain_pg_embedding")
                    has_embedding = any(col["name"] == "embedding" for col in embedding_cols)
                    
                    if has_embedding:
                        # Try to create HNSW index (may fail if not supported)
                        conn.execute(
                            text("""
                                CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw 
                                ON langchain_pg_embedding USING hnsw (embedding vector_cosine_ops)
                                WITH (m = 16, ef_construction = 64)
                            """)
                        )
                        logger.info("✅ Created HNSW index on embeddings")
                except Exception as e:
                    # HNSW may not be available or syntax may differ
                    logger.debug(f"HNSW index creation skipped (may not be supported): {e}")
                    
                    # Fallback: create standard vector index if HNSW fails
                    try:
                        conn.execute(
                            text("""
                                CREATE INDEX IF NOT EXISTS idx_embeddings_vector 
                                ON langchain_pg_embedding USING ivfflat (embedding vector_cosine_ops)
                                WITH (lists = 100)
                            """)
                        )
                        logger.info("✅ Created IVFFlat index on embeddings (fallback)")
                    except Exception as ivf_error:
                        logger.debug(f"IVFFlat index also not available: {ivf_error}")
                        
    except Exception as e:
        logger.warning(f"Could not create pgvector indexes: {e}. Search may be slower.")
    
    # Ensure tabular_review tables exist with correct schema
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        if "tabular_reviews" in table_names:
            # Check if table has correct columns
            columns = [col['name'] for col in inspector.get_columns("tabular_reviews")]
            if "case_id" not in columns:
                logger.warning("tabular_reviews table exists but has wrong schema. It should be recreated manually.")
                logger.warning("Please run: backend/migrations/fix_tabular_reviews_table.sql")
            else:
                logger.debug("Tabular review tables exist with correct schema")
        else:
            logger.info("Creating tabular_review tables...")
            # Import models to ensure they're registered
            from app.models.tabular_review import (
                TabularReview, TabularColumn, TabularCell,
                TabularColumnTemplate, TabularDocumentStatus
            )
            # Create only tabular_review tables
            TabularReview.__table__.create(bind=engine, checkfirst=True)
            TabularColumn.__table__.create(bind=engine, checkfirst=True)
            TabularCell.__table__.create(bind=engine, checkfirst=True)
            TabularColumnTemplate.__table__.create(bind=engine, checkfirst=True)
            TabularDocumentStatus.__table__.create(bind=engine, checkfirst=True)
            logger.info("✅ Tabular review tables created")
    except Exception as e:
        logger.warning(f"Could not ensure tabular_review tables: {e}", exc_info=True)


def init_db():
    """Initialize database tables"""
    # Import all models to ensure they are registered with Base
    from app.models.case import Case, ChatMessage, File
    from app.models.user import User, UserSession
    from app.models.analysis import (
        AnalysisResult, Discrepancy, TimelineEvent, DocumentChunk,
        DocumentClassification, ExtractedEntity, PrivilegeCheck,
        RelationshipNode, RelationshipEdge, Risk
    )
    from app.models.tabular_review import (
        TabularReview, TabularColumn, TabularCell,
        TabularColumnTemplate, TabularDocumentStatus
    )
    
    # Check if tabular_reviews table exists with wrong schema and fix it
    try:
        inspector = inspect(engine)
        if "tabular_reviews" in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns("tabular_reviews")]
            if "case_id" not in columns:
                logger.warning("⚠️  tabular_reviews table has wrong schema. Attempting to fix...")
                # Drop and recreate the tables
                with engine.connect() as conn:
                    conn.execute(text("DROP TABLE IF EXISTS tabular_cells CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_columns CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_document_statuses CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_column_templates CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_reviews CASCADE"))
                    conn.commit()
                logger.info("Dropped old tabular_review tables. Creating new ones...")
    except Exception as e:
        logger.warning(f"Could not check/fix tabular_reviews table: {e}")
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("✅ All database tables created")
    
    ensure_schema()
    
    # Setup LangGraph checkpointer tables
    try:
        from app.utils.checkpointer_setup import setup_checkpointer
        setup_checkpointer()
    except Exception as e:
        logger.warning(f"Failed to setup LangGraph checkpointer: {e}. Will use fallback.")


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
    
