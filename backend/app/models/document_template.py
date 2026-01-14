"""Document Template models for caching Garant document templates"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class DocumentTemplate(Base):
    """
    DocumentTemplate model - кэширует шаблоны документов из Гаранта.
    
    Используется для быстрого доступа к часто используемым шаблонам
    без повторных запросов к API Гаранта.
    """
    __tablename__ = "document_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Источник шаблона
    source = Column(String(50), nullable=False, default="garant")  # "garant", "custom"
    source_doc_id = Column(String(255), nullable=True)  # ID документа в Гаранте
    
    # Основная информация
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Содержимое шаблона (HTML)
    content = Column(Text, nullable=False)  # HTML шаблон из Гаранта
    
    # Ключевые слова для поиска (извлекаются автоматически)
    keywords = Column(JSON, default=list)  # ["договор", "поставка", "поставки"]
    
    # Категория и теги
    category = Column(String(100), nullable=True, index=True)  # "contract", "agreement", etc.
    tags = Column(JSON, default=list)  # ["договор поставки", "коммерческий договор"]
    
    # Метаданные из Гаранта
    garant_metadata = Column(JSON, nullable=True)  # Сохраняем метаданные из Гаранта
    
    # Владелец (для пользовательских шаблонов)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Статистика использования
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    
    # Видимость
    is_public = Column(Boolean, default=False)  # Доступен всем пользователям
    is_system = Column(Boolean, default=False)  # Системный шаблон
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="document_templates")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "source": self.source,
            "source_doc_id": self.source_doc_id,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "keywords": self.keywords or [],
            "category": self.category,
            "tags": self.tags or [],
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

