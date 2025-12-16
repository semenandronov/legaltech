"""Database utilities for Legal AI Vault"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from app.config import config
from app.models.case import Base, Case, ChatMessage, File  # Import models to register them
from app.models.user import User, UserSession  # Import user models to register them
from app.models.analysis import AnalysisResult, Discrepancy, TimelineEvent, DocumentChunk  # Import analysis models to register them

# Create engine
engine = create_engine(config.DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema():
    """Ensure required columns and indexes exist"""
    inspector = inspect(engine)
    if "chat_messages" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("chat_messages")]
        with engine.begin() as conn:
            if "case_id" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE chat_messages "
                        "ADD COLUMN IF NOT EXISTS case_id TEXT REFERENCES cases(id) ON DELETE CASCADE"
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chat_messages_case_id "
                    "ON chat_messages(case_id)"
                )
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
    
