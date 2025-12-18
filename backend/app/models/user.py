"""User models for Legal AI Vault"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class User(Base):
    """User model - represents a user account"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # В БД поле называется password, не password_hash
    name = Column(String(255), nullable=True)  # В БД поле называется name, не full_name
    role = Column(String(50), default="USER")  # В БД используется enum UserRole с дефолтом 'USER'
    emailVerified = Column(DateTime, nullable=True)  # Соответствует БД
    image = Column(String(255), nullable=True)  # Соответствует БД
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Соответствует БД
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Соответствует БД
    
    # Дополнительные поля для совместимости (могут отсутствовать в БД)
    # НЕ определяем как Column, используем только properties ниже
    # company = Column(String(255), nullable=True)  # Может отсутствовать в БД
    
    # Relationships
    cases = relationship("Case", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    
    @property
    def password_hash(self):
        """Getter для password_hash - возвращает password"""
        return self.password
    
    @password_hash.setter
    def password_hash(self, value):
        """Setter для password_hash - устанавливает password"""
        self.password = value
    
    @property
    def full_name(self):
        """Getter для full_name - возвращает name"""
        return self.name
    
    @full_name.setter
    def full_name(self, value):
        """Setter для full_name - устанавливает name"""
        self.name = value
    
    @property
    def is_active(self):
        """Getter для is_active - всегда True (если не заблокирован)"""
        # Можно добавить логику блокировки в будущем
        return True
    
    @property
    def created_at(self):
        """Getter для created_at - возвращает createdAt"""
        return self.createdAt
    
    @property
    def updated_at(self):
        """Getter для updated_at - возвращает updatedAt"""
        return self.updatedAt


class UserSession(Base):
    """UserSession model - manages user sessions"""
    __tablename__ = "user_sessions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)  # Добавлен ForeignKey
    token = Column(String(500), nullable=False, unique=True, index=True)
    refresh_token = Column(String(500), nullable=True, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationship
    user = relationship("User", back_populates="sessions")
