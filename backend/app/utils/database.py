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
        
        # Add case_id column if missing (separate transaction)
        if "case_id" not in columns:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE chat_messages "
                            "ADD COLUMN IF NOT EXISTS case_id TEXT REFERENCES cases(id) ON DELETE CASCADE"
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not add case_id column to chat_messages: {e}")
        
        # Refresh columns after potential ALTER
        columns = {col["name"]: col for col in inspector.get_columns("chat_messages")}
        
        # Check if sessionId column exists and if it's NOT NULL, make it nullable (separate transaction)
        session_id_col_info = next((col for col in inspector.get_columns("chat_messages") if col["name"] == "sessionId"), None)
        if session_id_col_info and not session_id_col_info.get("nullable", True):
            logger.info("⚠️  Altering chat_messages.sessionId to be NULLABLE...")
            try:
                with engine.begin() as conn:
                    conn.execute(text('ALTER TABLE chat_messages ALTER COLUMN "sessionId" DROP NOT NULL'))
                    logger.info("✅ chat_messages.sessionId column altered to NULLABLE")
            except Exception as e:
                logger.warning(f"Could not alter sessionId column to NULLABLE: {e}")
                
        # Update any existing NULL sessionId values (separate transaction)
        # Only update if sessionId doesn't have foreign key constraint or if sessions exist
        if session_id_col_info:
            try:
                with engine.begin() as conn:
                    # Check if sessionId has foreign key constraint
                    fk_constraints = inspector.get_foreign_keys("chat_messages")
                    has_session_fk = any(fk.get("referred_table") == "chat_sessions" for fk in fk_constraints)
                    
                    if has_session_fk:
                        # If foreign key exists, only update if corresponding session exists
                        # For now, skip update to avoid ForeignKeyViolation
                        logger.info("⚠️  sessionId has foreign key to chat_sessions, skipping auto-update")
                    else:
                        # No foreign key, safe to update
                        conn.execute(
                            text(
                                'UPDATE chat_messages '
                                'SET "sessionId" = case_id '
                                'WHERE "sessionId" IS NULL AND case_id IS NOT NULL'
                            )
                        )
                        logger.info("✅ Updated NULL sessionId values to case_id")
            except Exception as e:
                logger.warning(f"Could not update NULL sessionId values: {e}")
        
        # Create index (separate transaction)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_chat_messages_case_id "
                        "ON chat_messages(case_id)"
                    )
                )
        except Exception as e:
            logger.warning(f"Could not create index ix_chat_messages_case_id: {e}")
    
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
                # Check if cmetadata column exists before creating index
                embedding_cols = inspector.get_columns("langchain_pg_embedding")
                has_cmetadata = any(col["name"] == "cmetadata" for col in embedding_cols)
                
                if has_cmetadata:
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
                else:
                    logger.info("⚠️  langchain_pg_embedding table exists but cmetadata column not found, skipping index creation")
                
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
                # Check and add selected_file_ids column if missing
                if "selected_file_ids" not in columns:
                    logger.info("Adding selected_file_ids column to tabular_reviews table...")
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text("ALTER TABLE tabular_reviews ADD COLUMN IF NOT EXISTS selected_file_ids JSON")
                            )
                        logger.info("✅ Added selected_file_ids column to tabular_reviews")
                    except Exception as e:
                        logger.warning(f"Could not add selected_file_ids column: {e}")
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
        
        # Ensure tabular_column_templates has all required columns
        if "tabular_column_templates" in table_names:
            try:
                columns = {col['name']: col for col in inspector.get_columns("tabular_column_templates")}
                with engine.begin() as conn:
                    # Add missing columns if they don't exist
                    if "category" not in columns:
                        logger.info("Adding category column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS category VARCHAR(100)"))
                        logger.info("✅ Added category column")
                    
                    if "tags" not in columns:
                        logger.info("Adding tags column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS tags JSON"))
                        logger.info("✅ Added tags column")
                    
                    if "is_system" not in columns:
                        logger.info("Adding is_system column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE"))
                        logger.info("✅ Added is_system column")
                    
                    if "is_featured" not in columns:
                        logger.info("Adding is_featured column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE"))
                        logger.info("✅ Added is_featured column")
                    
                    if "usage_count" not in columns:
                        logger.info("Adding usage_count column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0"))
                        logger.info("✅ Added usage_count column")
                    
                    if "updated_at" not in columns:
                        logger.info("Adding updated_at column to tabular_column_templates...")
                        conn.execute(text("ALTER TABLE tabular_column_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
                        logger.info("✅ Added updated_at column")
                    
                    # Create indexes if they don't exist
                    try:
                        indexes = [idx['name'] for idx in inspector.get_indexes("tabular_column_templates")]
                        if "idx_tabular_column_templates_category" not in indexes:
                            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_category ON tabular_column_templates(category)"))
                        if "idx_tabular_column_templates_featured" not in indexes:
                            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_featured ON tabular_column_templates(is_featured)"))
                        if "idx_tabular_column_templates_system" not in indexes:
                            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_system ON tabular_column_templates(is_system)"))
                    except Exception as idx_err:
                        logger.warning(f"Could not create indexes: {idx_err}")
                
                logger.info("✅ Tabular column templates table schema verified")
            except Exception as e:
                logger.error(f"Error ensuring tabular_column_templates schema: {e}", exc_info=True)
    except Exception as e:
        logger.warning(f"Could not ensure tabular_review tables: {e}", exc_info=True)
    
    # Ensure files.file_path column exists
    try:
        if "files" in inspector.get_table_names():
            columns = {col["name"]: col for col in inspector.get_columns("files")}
            
            if "file_path" not in columns:
                logger.info("⚠️  file_path column not found in files table, adding it...")
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE files "
                                "ADD COLUMN IF NOT EXISTS file_path VARCHAR(512)"
                            )
                        )
                        logger.info("✅ Added file_path column to files table")
                        
                        # Create index for faster lookups
                        conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_files_file_path "
                                "ON files(file_path) WHERE file_path IS NOT NULL"
                            )
                        )
                        logger.info("✅ Created index on files.file_path")
                except Exception as e:
                    logger.error(f"❌ Could not add file_path column to files table: {e}", exc_info=True)
                    raise
            else:
                logger.debug("✅ file_path column already exists in files table")
    except Exception as e:
        logger.error(f"Error checking/adding file_path column: {e}", exc_info=True)


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
                with engine.begin() as conn:
                    conn.execute(text("DROP TABLE IF EXISTS tabular_cells CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_columns CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_document_statuses CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_column_templates CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS tabular_reviews CASCADE"))
                logger.info("Dropped old tabular_review tables. Creating new ones...")
    except Exception as e:
        logger.warning(f"Could not check/fix tabular_reviews table: {e}", exc_info=True)
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("✅ All database tables created")
    
    ensure_schema()
    
    # Apply tabular_columns migration if needed
    try:
        from sqlalchemy import text, inspect as sql_inspect
        inspector = sql_inspect(engine)
        if "tabular_columns" in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns("tabular_columns")]
            if "column_config" not in columns:
                logger.info("⚠️  Applying migration: adding column_config and is_pinned to tabular_columns")
                try:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE tabular_columns ADD COLUMN IF NOT EXISTS column_config JSONB"))
                        conn.execute(text("ALTER TABLE tabular_columns ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE"))
                        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tabular_columns_is_pinned ON tabular_columns(is_pinned) WHERE is_pinned = TRUE"))
                    logger.info("✅ Migration applied: column_config and is_pinned added to tabular_columns")
                except Exception as mig_error:
                    logger.error(f"❌ Failed to apply column_config migration: {mig_error}", exc_info=True)
                    raise
            else:
                logger.info("✅ column_config and is_pinned already exist in tabular_columns")
        
        if "tabular_cells" in inspector.get_table_names():
            cells_columns = [col['name'] for col in inspector.get_columns("tabular_cells")]
            if "source_references" not in cells_columns:
                logger.info("⚠️  Applying migration: adding source_references to tabular_cells")
                try:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE tabular_cells ADD COLUMN IF NOT EXISTS source_references JSONB"))
                    logger.info("✅ Migration applied: source_references added to tabular_cells")
                except Exception as mig_error:
                    logger.error(f"❌ Failed to apply source_references migration: {mig_error}", exc_info=True)
                    raise
            else:
                logger.info("✅ source_references already exists in tabular_cells")
    except Exception as e:
        logger.warning(f"Could not apply tabular_columns migration: {e}", exc_info=True)
    
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
    
