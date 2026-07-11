"""SQL rows for structured-table documents (bank statements, registers)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Integer, JSON, Numeric, String, Text

from app.models.case import Base


class CaseFileTransaction(Base):
    __tablename__ = "case_file_transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String(36), nullable=False, index=True)
    file_id = Column(String(36), nullable=False, index=True)
    global_row_index = Column(Integer, nullable=False)
    table_index = Column(Integer, nullable=False, default=0)
    row_index = Column(Integer, nullable=False, default=0)
    operation_date = Column(Date, nullable=True)
    operation_datetime_text = Column(Text, nullable=True)
    amount_rub = Column(Numeric(18, 2), nullable=True)
    amount_raw = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    row_columns = Column(JSON, nullable=False, default=dict)
    page_start = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    verbatim_row_text = Column(Text, nullable=True)
    source_references = Column(JSON, nullable=True)
    flow_direction = Column(String(16), nullable=True)
    source_filename = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
