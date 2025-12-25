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
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)  # nullable=True для совместимости с существующими данными
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)  # Описание дела
    case_type = Column(String(50), nullable=True)  # litigation, contracts, dd, compliance, other
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    full_text = Column(Text, nullable=False)  # Combined text from all documents
    num_documents = Column(Integer, default=0)
    file_names = Column(JSON, nullable=False)  # List of file names
    analysis_config = Column(JSON, nullable=True)  # Настройки анализа
    case_metadata = Column(JSON, nullable=True)  # Дополнительные метаданные (переименовано из metadata, т.к. metadata зарезервировано SQLAlchemy)
    yandex_index_id = Column(String(255), nullable=True)  # ID индекса в Yandex AI Studio
    yandex_assistant_id = Column(String(255), nullable=True)  # ID ассистента в Yandex AI Studio
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="cases")
    chat_messages = relationship("ChatMessage", back_populates="case", cascade="all, delete-orphan")
    files = relationship("File", back_populates="case", cascade="all, delete-orphan")
    analysis_results = relationship("AnalysisResult", back_populates="case", cascade="all, delete-orphan")
    discrepancies = relationship("Discrepancy", back_populates="case", cascade="all, delete-orphan")
    timeline_events = relationship("TimelineEvent", back_populates="case", cascade="all, delete-orphan")
    document_chunks = relationship("DocumentChunk", back_populates="case", cascade="all, delete-orphan")
    document_classifications = relationship("DocumentClassification", back_populates="case", cascade="all, delete-orphan")
    extracted_entities = relationship("ExtractedEntity", back_populates="case", cascade="all, delete-orphan")
    privilege_checks = relationship("PrivilegeCheck", back_populates="case", cascade="all, delete-orphan")
    risks = relationship("Risk", back_populates="case", cascade="all, delete-orphan")


class ChatMessage(Base):
    """ChatMessage model - represents a message in chat history"""
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    source_references = Column(JSON, nullable=True)  # List of source file names
    session_id = Column(String, name="sessionId", nullable=True)  # Session ID for chat (optional, defaults to case_id). DB column is "sessionId"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="chat_messages")


class File(Base):
    """File model - stores per-document data for a case"""
    __tablename__ = "files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    original_text = Column(Text, nullable=False)
    # metadata удалено - не существует в БД, используем другие поля для хранения метаданных
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    case = relationship("Case", back_populates="files")
    chunks = relationship("DocumentChunk", back_populates="file", cascade="all, delete-orphan")
    document_classifications = relationship("DocumentClassification", back_populates="file", cascade="all, delete-orphan")
    extracted_entities = relationship("ExtractedEntity", back_populates="file", cascade="all, delete-orphan")
    privilege_checks = relationship("PrivilegeCheck", back_populates="file", cascade="all, delete-orphan")

