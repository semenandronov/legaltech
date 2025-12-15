"""SQLAlchemy models for Legal AI Vault"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()


class Case(Base):
    """Case model - represents a legal case with uploaded documents"""
    __tablename__ = "cases"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=True)  # For future authentication
    title = Column(String(255), nullable=True)
    full_text = Column(Text, nullable=False)  # Combined text from all documents
    num_documents = Column(Integer, default=0)
    file_names = Column(JSON, nullable=False)  # List of file names
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    chat_messages = relationship("ChatMessage", back_populates="case", cascade="all, delete-orphan")


class ChatMessage(Base):
    """ChatMessage model - represents a message in chat history"""
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    source_references = Column(JSON, nullable=True)  # List of source file names
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="chat_messages")

