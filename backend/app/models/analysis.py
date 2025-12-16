"""Analysis models for Legal AI Vault"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer, Date
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class AnalysisResult(Base):
    """AnalysisResult model - stores analysis results for a case"""
    __tablename__ = "analysis_results"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False)  # timeline, discrepancies, key_facts, summary, risk_analysis
    result_data = Column(JSON, nullable=False)  # JSON с результатами анализа
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="analysis_results")


class Discrepancy(Base):
    """Discrepancy model - stores found discrepancies in documents"""
    __tablename__ = "discrepancies"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(100), nullable=False)  # Тип противоречия
    severity = Column(String(20), nullable=False)  # HIGH, MEDIUM, LOW
    description = Column(Text, nullable=False)
    source_documents = Column(JSON, nullable=False)  # Список документов с противоречиями
    details = Column(JSON, nullable=True)  # Дополнительные детали
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="discrepancies")


class TimelineEvent(Base):
    """TimelineEvent model - stores timeline events extracted from documents"""
    __tablename__ = "timeline_events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    event_type = Column(String(100), nullable=True)  # Тип события
    description = Column(Text, nullable=False)
    source_document = Column(String(255), nullable=False)  # Имя документа-источника
    source_page = Column(Integer, nullable=True)  # Номер страницы
    source_line = Column(Integer, nullable=True)  # Номер строки или диапазон
    metadata = Column(JSON, nullable=True)  # Дополнительные метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="timeline_events")


class DocumentChunk(Base):
    """DocumentChunk model - stores document chunks for LangChain RAG"""
    __tablename__ = "document_chunks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True)
    chunk_index = Column(Integer, nullable=False)  # Порядковый номер чанка в файле
    chunk_text = Column(Text, nullable=False)  # Текст чанка
    source_file = Column(String(255), nullable=False)  # Имя исходного файла
    source_page = Column(Integer, nullable=True)  # Номер страницы (для PDF)
    source_start_line = Column(Integer, nullable=True)  # Начальная строка
    source_end_line = Column(Integer, nullable=True)  # Конечная строка
    embedding = Column(JSON, nullable=True)  # Векторное представление (опционально, если храним в БД)
    metadata = Column(JSON, nullable=True)  # Дополнительные метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case", back_populates="document_chunks")
    file = relationship("File", back_populates="chunks")

