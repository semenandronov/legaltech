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
    details = Column(JSON, nullable=True)  # Дополнительные детали (включает reasoning и confidence)
    # reasoning и confidence удалены - хранятся в details (JSON) для совместимости с БД
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="discrepancies")


class TimelineEvent(Base):
    """TimelineEvent model - stores timeline events extracted from documents"""
    __tablename__ = "timeline_events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timelineId = Column(String, nullable=True)  # Старое поле для совместимости со старой схемой БД
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)  # nullable=True для совместимости
    date = Column(DateTime, nullable=False, index=True)  # Изменено с Date на DateTime для совместимости с БД
    event_type = Column(String(100), nullable=True)  # Тип события
    description = Column(Text, nullable=False)
    source_document = Column(String(255), nullable=False)  # Имя документа-источника
    source_page = Column(Integer, nullable=True)  # Номер страницы
    source_line = Column(Integer, nullable=True)  # Номер строки или диапазон
    event_metadata = Column(JSON, nullable=True)  # Дополнительные метаданные (включает reasoning и confidence)
    order = Column(Integer, nullable=False, default=0)  # Порядок события для сортировки (обязательное поле в БД)
    # reasoning и confidence удалены - хранятся в event_metadata для совместимости с БД
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
    chunk_metadata = Column(JSON, nullable=True)  # Дополнительные метаданные (переименовано из metadata)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case", back_populates="document_chunks")
    file = relationship("File", back_populates="chunks")


class DocumentClassification(Base):
    """DocumentClassification model - stores document classification results"""
    __tablename__ = "document_classifications"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True)
    doc_type = Column(String(100), nullable=False)  # Тип документа
    relevance_score = Column(Integer, nullable=False)  # Релевантность 0-100
    is_privileged = Column(String(10), nullable=False, default="false")  # true/false как строка
    privilege_type = Column(String(50), nullable=False, default="none")  # attorney-client, work-product, none
    key_topics = Column(JSON, nullable=True)  # Массив основных тем
    confidence = Column(String(10), nullable=True)  # Уверенность 0-1
    reasoning = Column(Text, nullable=True)  # Подробное объяснение решения
    needs_human_review = Column(String(10), nullable=False, default="false")  # true/false как строка
    prompt_version = Column(String(20), nullable=True, default="v1")  # Версия промпта
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case")
    file = relationship("File")


class ExtractedEntity(Base):
    """ExtractedEntity model - stores extracted named entities"""
    __tablename__ = "extracted_entities"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True)
    entity_text = Column(Text, nullable=False)  # Текст сущности
    entity_type = Column(String(50), nullable=False)  # PERSON, ORG, DATE, AMOUNT, CONTRACT_TERM
    confidence = Column(String(10), nullable=True)  # Уверенность 0-1
    context = Column(Text, nullable=True)  # Контекст, в котором найдена сущность
    source_document = Column(String(255), nullable=True)  # Имя документа-источника
    source_page = Column(Integer, nullable=True)  # Номер страницы
    source_line = Column(Integer, nullable=True)  # Номер строки
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case")
    file = relationship("File")


class PrivilegeCheck(Base):
    """PrivilegeCheck model - stores privilege check results (КРИТИЧНО для e-discovery!)"""
    __tablename__ = "privilege_checks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    is_privileged = Column(String(10), nullable=False)  # true/false как строка
    privilege_type = Column(String(50), nullable=False)  # attorney-client, work-product, none
    confidence = Column(String(10), nullable=False)  # Уверенность 0-100 (критично >95%)
    reasoning = Column(JSON, nullable=True)  # Ключевые факторы (массив строк)
    withhold_recommendation = Column(String(10), nullable=False, default="false")  # true/false как строка
    requires_human_review = Column(String(10), nullable=False, default="true")  # Всегда требует human review
    prompt_version = Column(String(20), nullable=True, default="v1")  # Версия промпта
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case")
    file = relationship("File")


class RelationshipNode(Base):
    """RelationshipNode model - stores nodes in relationship graph"""
    __tablename__ = "relationship_nodes"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String, nullable=False, index=True)  # Unique identifier for node in graph (e.g., "CEO_Ivanov")
    node_type = Column(String(50), nullable=False)  # Person, Organization, Contract, Event, etc.
    node_label = Column(String(255), nullable=False)  # Display label (e.g., "Иванов Иван Иванович")
    properties = Column(JSON, nullable=True)  # Additional properties (title, role, etc.)
    source_document = Column(String(255), nullable=True)  # Source document
    source_page = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case")


class RelationshipEdge(Base):
    """RelationshipEdge model - stores edges (relationships) in relationship graph"""
    __tablename__ = "relationship_edges"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(String, nullable=False, index=True)  # Reference to RelationshipNode.node_id
    target_node_id = Column(String, nullable=False, index=True)  # Reference to RelationshipNode.node_id
    relationship_type = Column(String(100), nullable=False)  # signed, works_for, owns, contacted, etc.
    relationship_label = Column(String(255), nullable=True)  # Display label
    confidence = Column(String(10), nullable=True)  # Confidence 0-1
    context = Column(Text, nullable=True)  # Context where relationship was found
    source_document = Column(String(255), nullable=True)  # Source document
    source_page = Column(Integer, nullable=True)
    properties = Column(JSON, nullable=True)  # Additional properties (date, amount, etc.)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    case = relationship("Case")


class Risk(Base):
    """Risk model - stores identified risks for a case"""
    __tablename__ = "risks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_name = Column(String(255), nullable=False)  # Название риска
    risk_category = Column(String(50), nullable=False)  # legal, financial, reputational, procedural
    probability = Column(String(20), nullable=False)  # HIGH, MEDIUM, LOW
    impact = Column(String(20), nullable=False)  # HIGH, MEDIUM, LOW
    description = Column(Text, nullable=False)  # Описание риска
    evidence = Column(JSON, nullable=False)  # Список документов-доказательств
    recommendation = Column(Text, nullable=False)  # Рекомендации по митигации
    reasoning = Column(Text, nullable=False)  # Обоснование риска
    confidence = Column(String(10), nullable=True)  # Уверенность (0-1)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", back_populates="risks")


class AnalysisPlan(Base):
    """AnalysisPlan model - stores analysis plans for user approval"""
    __tablename__ = "analysis_plans"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_task = Column(Text, nullable=False)  # Исходная задача пользователя
    plan_data = Column(JSON, nullable=False)  # Полный план в JSON формате
    status = Column(String(50), default="pending_approval")  # pending_approval, approved, rejected, executing, completed
    confidence = Column(String(10), nullable=True)  # Уверенность плана (0-1)
    validation_result = Column(JSON, nullable=True)  # Результаты валидации плана
    tables_to_create = Column(JSON, nullable=True)  # Список таблиц для создания
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)  # Время одобрения
    executed_at = Column(DateTime, nullable=True)  # Время начала выполнения
    
    # Relationships
    case = relationship("Case")
    user = relationship("User")
