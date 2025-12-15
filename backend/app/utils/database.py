"""Database utilities for Legal AI Vault"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import config
from app.models.case import Base

# Create engine
engine = create_engine(config.DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

