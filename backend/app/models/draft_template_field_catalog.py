"""Каталог полей шаблона Draft (индексация при загрузке)."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.case import Base


class DraftTemplateFieldCatalog(Base):
    """
    Предвычисленные плейсхолдеры шаблона: семантика, retrieval_query, indexed_html с якорями.

    template_key: bankruptcy:{manifest_id} | db:{document_templates.id}
    """

    __tablename__ = "draft_template_field_catalog"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    template_key = Column(String(255), nullable=False, unique=True, index=True)
    content_sha256 = Column(String(64), nullable=False, default="")
    field_specs = Column(JSONB, nullable=False, default=list)
    indexed_html = Column(Text, nullable=False, default="")
    indexer_version = Column(String(32), nullable=False, default="1")
    indexed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
