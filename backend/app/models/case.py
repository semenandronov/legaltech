"""SQLAlchemy models for Legal AI Vault"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON, LargeBinary
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
    analysis_plans = relationship("AnalysisPlan", back_populates="case", cascade="all, delete-orphan")


class ChatMessage(Base):
    """ChatMessage model - represents a message in chat history"""
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    source_references = Column(JSON, nullable=True)  # List of source file names
    evidence = Column(JSON, nullable=True)  # Canonical evidence bundle (citations[], retrieval_metadata, etc.)
    reasoning_steps = Column(JSON, nullable=True)  # [{phase, step, totalSteps, content}, ...]
    session_id = Column(String, name="sessionId", nullable=True)  # Session ID for chat (optional, defaults to case_id). DB column is "sessionId"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="chat_messages")


class GlobalAssistantSession(Base):
    """Session for the global (case-free) assistant chat"""
    __tablename__ = "global_assistant_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=True)   # first user message preview
    draft_title = Column(String(500), nullable=True)   # saved draft document title
    draft_content = Column(Text, nullable=True)        # saved draft document HTML content
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("GlobalAssistantMessage", back_populates="session",
                            cascade="all, delete-orphan", order_by="GlobalAssistantMessage.created_at")


class GlobalAssistantMessage(Base):
    """Message in a global assistant session"""
    __tablename__ = "global_assistant_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("global_assistant_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    role = Column(String(20), nullable=False)   # "user" or "assistant"
    content = Column(Text, nullable=False)
    reasoning_steps = Column(JSON, nullable=True)  # [{phase, step, totalSteps, content}, ...]
    evidence = Column(JSON, nullable=True)  # Canonical evidence bundle (citations[], retrieval_metadata, etc.)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("GlobalAssistantSession", back_populates="messages")


class GlobalAssistantFile(Base):
    """File uploaded directly in the global assistant (not tied to a case)."""
    __tablename__ = "global_assistant_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_content = Column(LargeBinary, nullable=True)   # raw bytes of original file
    html_content = Column(Text, nullable=True)          # cached HTML for DOCX
    original_text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class LegalCorpusFile(Base):
    """Original file storage for global legal corpus (shared across users)."""
    __tablename__ = "legal_corpus_files"

    # Keep id equal to corpus_file_id for direct citation/source mapping
    id = Column(String, primary_key=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_content = Column(LargeBinary, nullable=True)  # raw original bytes
    html_content = Column(Text, nullable=True)  # cached HTML for DOCX preview
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class File(Base):
    """File model - stores per-document data for a case"""
    __tablename__ = "files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    original_text = Column(Text, nullable=False)
    file_path = Column(String(512), nullable=True)  # Путь к оригинальному файлу на диске (deprecated, kept for backward compatibility)
    file_content = Column(LargeBinary, nullable=True)  # Binary content of the original file stored in DB
    html_content = Column(Text, nullable=True)  # Cached HTML representation of the file for faster viewing
    folder_id = Column(String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    processing_status = Column(String(50), default="ready")  # pending, processing, ready, error, cancelled
    processing_error = Column(Text, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    structured_text = Column(Text, nullable=True)
    structured_text_format = Column(String(32), nullable=True)
    doc_summary_short = Column(Text, nullable=True)
    doc_key_points = Column(JSON, nullable=True)
    summary_version = Column(String(32), nullable=True)
    summary_content_hash = Column(String(64), nullable=True)
    # metadata удалено - не существует в БД, используем другие поля для хранения метаданных
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    case = relationship("Case", back_populates="files")
    chunks = relationship("DocumentChunk", back_populates="file", cascade="all, delete-orphan")
    document_classifications = relationship("DocumentClassification", back_populates="file", cascade="all, delete-orphan")
    extracted_entities = relationship("ExtractedEntity", back_populates="file", cascade="all, delete-orphan")
    privilege_checks = relationship("PrivilegeCheck", back_populates="file", cascade="all, delete-orphan")

