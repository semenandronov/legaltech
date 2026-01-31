"""
LangGraph Store модель для долгосрочной памяти агентов.

Хранит key-value данные для memory profiles, case memory,
query history и insights.
"""
from sqlalchemy import Column, String, Text, DateTime, Index
from sqlalchemy.sql import func
from app.models.case import Base


class LangGraphStoreEntry(Base):
    """
    Запись в LangGraph Store.
    
    Используется для хранения:
    - user_profile/{user_id}: Профили пользователей
    - case_memory/{case_id}: Память по делам
    - query_history/{user_id}: История запросов
    - insights/{scope_id}: Инсайты
    """
    __tablename__ = "langgraph_store"
    
    # Ключ в формате namespace/id
    key = Column(String(500), primary_key=True, nullable=False)
    
    # JSON-значение
    value = Column(Text, nullable=False)
    
    # Метаданные
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Индексы для поиска
    __table_args__ = (
        Index('ix_langgraph_store_key', key),
        Index('ix_langgraph_store_updated_at', updated_at),
    )
    
    def __repr__(self):
        return f"<LangGraphStoreEntry(key={self.key})>"

