"""Database utilities for Legal AI Vault"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from app.config import config
from app.models.case import Base, Case, ChatMessage, File  # Import models to register them
from app.models.user import User, UserSession  # Import user models to register them
from app.models.analysis import AnalysisResult, Discrepancy, TimelineEvent, DocumentChunk  # Import analysis models to register them
import logging

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(config.DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema():
    """Ensure required columns and indexes exist"""
    inspector = inspect(engine)
    
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
            # Check if sessionId column exists and if it's NOT NULL, make it nullable or set default
            if "sessionId" in columns:
                session_id_col = columns["sessionId"]
                # If sessionId is NOT NULL, we need to update existing NULL values or change constraint
                # For now, we'll just ensure existing NULL values get case_id as default
                # This is a workaround - ideally the column should be nullable
                try:
                    # Update any NULL sessionId values to use case_id from the same row
                    conn.execute(
                        text(
                            "UPDATE chat_messages "
                            "SET \"sessionId\" = case_id "
                            "WHERE \"sessionId\" IS NULL"
                        )
                    )
                except Exception as e:
                    # If update fails, try to alter column to allow NULL (if possible)
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


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    ensure_schema()


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
    
