"""
Chat History Service - Управление историей чата

Отвечает за:
- Создание и управление сессиями
- Сохранение сообщений пользователя и ассистента
- Загрузка истории для контекста
- Получение списка сессий
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
import uuid
import logging

from app.models.case import ChatMessage

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """
    Сервис управления историей чата.
    
    Обеспечивает:
    - Группировку сообщений по сессиям
    - Автоматическое создание новых сессий
    - Сохранение и загрузку истории
    """
    
    # Таймаут сессии в минутах (новая сессия если прошло больше)
    SESSION_TIMEOUT_MINUTES = 30
    
    def __init__(self, db: Session):
        """
        Инициализация сервиса
        
        Args:
            db: SQLAlchemy сессия
        """
        self.db = db
    
    def get_or_create_session(self, case_id: str) -> str:
        """
        Получить текущую сессию или создать новую
        
        Логика:
        - Если есть сообщение в последние 30 минут → продолжаем сессию
        - Иначе → создаём новую
        
        Args:
            case_id: ID дела
            
        Returns:
            session_id
        """
        try:
            last_message = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            if last_message and last_message.created_at:
                time_diff = datetime.utcnow() - last_message.created_at
                if time_diff < timedelta(minutes=self.SESSION_TIMEOUT_MINUTES):
                    if last_message.session_id:
                        logger.debug(f"Continuing session {last_message.session_id} for case {case_id}")
                        return last_message.session_id
            
            # Создаём новую сессию
            new_session_id = str(uuid.uuid4())
            logger.info(f"Creating new session {new_session_id} for case {case_id}")
            return new_session_id
            
        except Exception as e:
            logger.warning(f"Error getting session: {e}, creating new one")
            return str(uuid.uuid4())
    
    def save_user_message(
        self,
        case_id: str,
        content: str,
        session_id: Optional[str] = None
    ) -> ChatMessage:
        """
        Сохранить сообщение пользователя
        
        Args:
            case_id: ID дела
            content: Текст сообщения
            session_id: ID сессии (если None, будет определён автоматически)
            
        Returns:
            Созданное сообщение
        """
        if not session_id:
            session_id = self.get_or_create_session(case_id)
        
        message_id = str(uuid.uuid4())
        message = ChatMessage(
            id=message_id,
            case_id=case_id,
            role="user",
            content=content,
            session_id=session_id
        )
        
        self.db.add(message)
        self.db.commit()
        
        logger.info(f"Saved user message {message_id} in session {session_id}")
        return message
    
    def create_assistant_placeholder(
        self,
        case_id: str,
        session_id: str
    ) -> ChatMessage:
        """
        Создать placeholder для сообщения ассистента
        
        Используется для streaming - создаём пустое сообщение,
        которое потом обновляем полным ответом.
        
        Args:
            case_id: ID дела
            session_id: ID сессии
            
        Returns:
            Созданное сообщение (с пустым content)
        """
        message_id = str(uuid.uuid4())
        message = ChatMessage(
            id=message_id,
            case_id=case_id,
            role="assistant",
            content="",
            source_references=None,
            session_id=session_id
        )
        
        self.db.add(message)
        self.db.commit()
        
        logger.debug(f"Created assistant placeholder {message_id}")
        return message
    
    def update_assistant_message(
        self,
        message_id: str,
        content: str,
        source_references: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Обновить сообщение ассистента (после streaming)
        
        Args:
            message_id: ID сообщения
            content: Полный текст ответа
            source_references: Источники (опционально)
            
        Returns:
            True если успешно, False если сообщение не найдено
        """
        try:
            message = self.db.query(ChatMessage).filter(
                ChatMessage.id == message_id
            ).first()
            
            if not message:
                logger.warning(f"Assistant message {message_id} not found")
                return False
            
            message.content = content
            if source_references:
                message.source_references = source_references
            
            self.db.commit()
            logger.debug(f"Updated assistant message {message_id}")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating assistant message: {e}")
            return False
    
    def save_assistant_message(
        self,
        case_id: str,
        content: str,
        session_id: str,
        source_references: Optional[List[Dict[str, Any]]] = None
    ) -> ChatMessage:
        """
        Сохранить полное сообщение ассистента (без placeholder)
        
        Args:
            case_id: ID дела
            content: Текст ответа
            session_id: ID сессии
            source_references: Источники
            
        Returns:
            Созданное сообщение
        """
        message_id = str(uuid.uuid4())
        message = ChatMessage(
            id=message_id,
            case_id=case_id,
            role="assistant",
            content=content,
            source_references=source_references,
            session_id=session_id
        )
        
        self.db.add(message)
        self.db.commit()
        
        logger.info(f"Saved assistant message {message_id}")
        return message
    
    def get_session_history(
        self,
        case_id: str,
        session_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """
        Получить историю сообщений
        
        Args:
            case_id: ID дела
            session_id: ID сессии (если None, возвращает все сообщения дела)
            limit: Максимальное количество сообщений
            
        Returns:
            Список сообщений (от старых к новым)
        """
        query = self.db.query(ChatMessage).filter(
            ChatMessage.case_id == case_id,
            ChatMessage.content.isnot(None),
            ChatMessage.content != ""
        )
        
        if session_id:
            query = query.filter(ChatMessage.session_id == session_id)
        
        query = query.order_by(ChatMessage.created_at.asc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def get_history_for_context(
        self,
        case_id: str,
        session_id: str
    ) -> List[Dict[str, str]]:
        """
        Получить историю в формате для LLM контекста
        
        Args:
            case_id: ID дела
            session_id: ID сессии
            
        Returns:
            Список словарей {"role": "user/assistant", "content": "..."}
        """
        messages = self.get_session_history(case_id, session_id)
        
        history = []
        for msg in messages:
            if msg.role == "user" and msg.content:
                history.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant" and msg.content:
                history.append({"role": "assistant", "content": msg.content})
        
        return history
    
    def get_history_as_text(
        self,
        case_id: str,
        session_id: str
    ) -> str:
        """
        Получить историю как текст для промпта
        
        Args:
            case_id: ID дела
            session_id: ID сессии
            
        Returns:
            Текстовое представление истории
        """
        messages = self.get_session_history(case_id, session_id)
        
        parts = []
        for msg in messages:
            if msg.role == "user" and msg.content:
                parts.append(f"Пользователь: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                parts.append(f"Ассистент: {msg.content}")
        
        return "\n\n".join(parts)
    
    def get_sessions_for_case(self, case_id: str) -> List[Dict[str, Any]]:
        """
        Получить список сессий для дела
        
        Args:
            case_id: ID дела
            
        Returns:
            Список сессий с метаданными
        """
        sessions_query = self.db.query(
            ChatMessage.session_id,
            func.min(ChatMessage.created_at).label('first_message_at'),
            func.max(ChatMessage.created_at).label('last_message_at'),
            func.count(ChatMessage.id).label('message_count')
        ).filter(
            ChatMessage.case_id == case_id,
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
            ChatMessage.session_id.isnot(None)
        ).group_by(ChatMessage.session_id).order_by(desc('last_message_at')).all()
        
        sessions = []
        for session_row in sessions_query:
            session_id = session_row.session_id
            
            # Получаем первое и последнее сообщение для превью
            first_message = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.session_id == session_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.asc()).first()
            
            last_message = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.session_id == session_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            first_preview = ""
            if first_message and first_message.content:
                first_preview = first_message.content[:100]
                if len(first_message.content) > 100:
                    first_preview += "…"
            
            last_preview = ""
            if last_message and last_message.content:
                last_preview = last_message.content[:100]
                if len(last_message.content) > 100:
                    last_preview += "…"
            
            sessions.append({
                "session_id": session_id,
                "first_message": first_preview,
                "last_message": last_preview,
                "first_message_at": first_message.created_at.isoformat() if first_message and first_message.created_at else None,
                "last_message_at": last_message.created_at.isoformat() if last_message and last_message.created_at else None,
                "message_count": session_row.message_count
            })
        
        return sessions
    
    def delete_session(self, case_id: str, session_id: str) -> int:
        """
        Удалить сессию (все сообщения)
        
        Args:
            case_id: ID дела
            session_id: ID сессии
            
        Returns:
            Количество удалённых сообщений
        """
        try:
            deleted = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.session_id == session_id
            ).delete()
            
            self.db.commit()
            logger.info(f"Deleted {deleted} messages from session {session_id}")
            return deleted
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting session: {e}")
            return 0


