"""Document Editor models for Legal AI Vault"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class Document(Base):
    """Document model - represents an editable document created in the editor"""
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column("userId", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)  # HTML content from TipTap editor
    content_plain = Column(Text, nullable=True)  # Plain text version for search
    document_metadata = Column(JSON, nullable=True)  # Additional metadata (version, author, tags, etc.) - renamed from 'metadata' to avoid SQLAlchemy reserved name
    version = Column(Integer, default=1)  # Version number for versioning
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    case = relationship("Case", backref="editor_documents")
    user = relationship("User", backref="documents")


class DocumentVersion(Base):
    """DocumentVersion model - stores version history of documents"""
    __tablename__ = "document_versions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)  # HTML content snapshot
    version = Column(Integer, nullable=False)  # Version number
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    document = relationship("Document", backref="versions")
    creator = relationship("User", foreign_keys=[created_by])

