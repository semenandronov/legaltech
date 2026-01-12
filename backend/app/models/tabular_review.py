"""Tabular Review models for Legal AI Vault"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer, Boolean, DECIMAL, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class TabularReview(Base):
    """TabularReview model - stores tabular review projects"""
    __tablename__ = "tabular_reviews"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="draft")  # draft, processing, completed
    selected_file_ids = Column(JSON, nullable=True)  # Список выбранных file_id для этой таблицы
    table_mode = Column(String(50), default="document")  # document, entity, fact
    entity_config = Column(JSON, nullable=True)  # Конфигурация для entity режима: {entity_type, extraction_prompt, grouping_key}
    review_rules = Column(JSON, nullable=True)  # Правила для review queue: {low_confidence_threshold, critical_columns, always_review_types, conflict_priority, ocr_quality_threshold}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    case = relationship("Case", backref="tabular_reviews")
    columns = relationship("TabularColumn", back_populates="review", cascade="all, delete-orphan", order_by="TabularColumn.order_index")
    cells = relationship("TabularCell", back_populates="review", cascade="all, delete-orphan")
    document_statuses = relationship("TabularDocumentStatus", back_populates="review", cascade="all, delete-orphan")


class TabularColumn(Base):
    """TabularColumn model - stores column definitions (questions) for tabular review"""
    __tablename__ = "tabular_columns"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    column_label = Column(String(255), nullable=False)  # "Loan Type", "Key Terms", etc.
    column_type = Column(String(50), nullable=False)  # text, number, currency, yes_no, date, tag, verbatim, manual_input
    prompt = Column(Text, nullable=False)  # вопрос/prompt для AI
    column_config = Column(JSON, nullable=True)  # Конфигурация для типа tag: {options: [{label, color}], allow_custom: bool}
    order_index = Column(Integer, nullable=False)
    is_pinned = Column(Boolean, default=False)  # Закреплена ли колонка
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    review = relationship("TabularReview", back_populates="columns")
    cells = relationship("TabularCell", back_populates="column", cascade="all, delete-orphan")


class TabularCell(Base):
    """TabularCell model - stores cell values (AI responses) for tabular review"""
    __tablename__ = "tabular_cells"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    column_id = Column(String, ForeignKey("tabular_columns.id", ondelete="CASCADE"), nullable=False, index=True)
    cell_value = Column(Text, nullable=True)  # извлеченное значение
    normalized_value = Column(Text, nullable=True)  # нормализованное значение (отдельно от cell_value)
    verbatim_extract = Column(Text, nullable=True)  # точная цитата из документа
    reasoning = Column(Text, nullable=True)  # объяснение AI (обоснование ответа)
    source_references = Column(JSON, nullable=True)  # Ссылки на источники: [{page: int, section: str, text: str}]
    confidence_score = Column(DECIMAL(3, 2), nullable=True)  # 0.00 - 1.00
    source_page = Column(Integer, nullable=True)
    source_section = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")  # pending, processing, completed, reviewed, conflict, empty, n_a
    candidates = Column(JSON, nullable=True)  # Массив кандидатов: [{value, confidence, source_page, verbatim, reasoning, normalized_value}]
    conflict_resolution = Column(JSON, nullable=True)  # Метаданные разрешения конфликта: {resolved_by, resolution_method, selected_candidate_id, resolved_at}
    locked_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    locked_at = Column(DateTime, nullable=True)
    lock_expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Phase 4: Citation system fields for deep links
    primary_source_doc_id = Column(String, nullable=True, index=True)  # doc_id основного источника
    primary_source_char_start = Column(Integer, nullable=True)  # Начальная позиция символа в источнике
    primary_source_char_end = Column(Integer, nullable=True)  # Конечная позиция символа в источнике
    verified_flag = Column(Boolean, nullable=True)  # Флаг верификации цитаты
    
    # Unique constraint: одна ячейка на документ+колонку
    __table_args__ = (
        UniqueConstraint('file_id', 'column_id', name='uq_tabular_cell_file_column'),
    )
    
    # Relationships
    review = relationship("TabularReview", back_populates="cells")
    column = relationship("TabularColumn", back_populates="cells")
    file = relationship("File", backref="tabular_cells")


class TabularColumnTemplate(Base):
    """TabularColumnTemplate model - stores reusable column templates"""
    __tablename__ = "tabular_column_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)  # "M&A Due Diligence", "Loan Analysis", etc.
    description = Column(Text, nullable=True)
    columns = Column(JSON, nullable=False)  # массив определений колонок
    is_public = Column(Boolean, default=False)
    category = Column(String(100), nullable=True, index=True)  # "contract", "litigation", "due_diligence", etc.
    tags = Column(JSON, nullable=True)  # массив тегов: ["Law firm", "In-house", "Dispute"]
    is_system = Column(Boolean, default=False)  # системные шаблоны от Legora
    is_featured = Column(Boolean, default=False)  # избранные шаблоны для carousel
    usage_count = Column(Integer, default=0)  # счетчик использования
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="tabular_templates")


class TabularDocumentStatus(Base):
    """TabularDocumentStatus model - stores document review statuses"""
    __tablename__ = "tabular_document_status"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), default="not_reviewed")  # not_reviewed, reviewed, flagged, pending_clarification
    locked = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint: один статус на документ+пользователя в review
    __table_args__ = (
        UniqueConstraint('tabular_review_id', 'file_id', 'user_id', name='uq_tabular_doc_status'),
    )
    
    # Relationships
    review = relationship("TabularReview", back_populates="document_statuses")
    file = relationship("File", backref="tabular_document_statuses")
    user = relationship("User", backref="tabular_document_statuses")


class CellHistory(Base):
    """CellHistory model - stores version history for cell values"""
    __tablename__ = "cell_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    column_id = Column(String, ForeignKey("tabular_columns.id", ondelete="CASCADE"), nullable=False, index=True)
    cell_value = Column(Text, nullable=True)
    verbatim_extract = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    source_references = Column(JSON, nullable=True)
    confidence_score = Column(DECIMAL(3, 2), nullable=True)
    source_page = Column(Integer, nullable=True)
    source_section = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")
    changed_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    change_type = Column(String(50), nullable=False)  # 'created', 'updated', 'deleted', 'reverted'
    previous_cell_value = Column(Text, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    review = relationship("TabularReview", backref="cell_history_records")
    file = relationship("File", backref="cell_history_records")
    column = relationship("TabularColumn", backref="cell_history_records")
    user = relationship("User", backref="cell_history_records")


class CellComment(Base):
    """CellComment model - stores comments on tabular cells"""
    __tablename__ = "cell_comments"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    column_id = Column(String, ForeignKey("tabular_columns.id", ondelete="CASCADE"), nullable=False, index=True)
    comment_text = Column(Text, nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    review = relationship("TabularReview", backref="cell_comments")
    file = relationship("File", backref="cell_comments")
    column = relationship("TabularColumn", backref="cell_comments")
    author = relationship("User", foreign_keys=[created_by], backref="cell_comments_authored")
    resolver = relationship("User", foreign_keys=[resolved_by], backref="cell_comments_resolved")


class ReviewQueueItem(Base):
    """ReviewQueueItem model - stores items in review queue"""
    __tablename__ = "review_queue_items"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tabular_review_id = Column(String, ForeignKey("tabular_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    column_id = Column(String, ForeignKey("tabular_columns.id", ondelete="CASCADE"), nullable=False, index=True)
    cell_id = Column(String, ForeignKey("tabular_cells.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(Integer, nullable=False, default=5)  # 1-5, where 1 is highest
    reason = Column(String(255), nullable=False)  # Comma-separated reasons: "conflict,low_confidence"
    is_reviewed = Column(Boolean, default=False, index=True)
    reviewed_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    review = relationship("TabularReview", backref="review_queue_items")
    file = relationship("File", backref="review_queue_items")
    column = relationship("TabularColumn", backref="review_queue_items")
    cell = relationship("TabularCell", backref="review_queue_items")
    reviewer = relationship("User", backref="review_queue_items")

