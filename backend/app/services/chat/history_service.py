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
from datetime import datetime, timezone
import uuid
import logging

from app.models.case import ChatMessage
from app.services.chat.editor_session import is_editor_session_id

logger = logging.getLogger(__name__)

# Namespaces stored in chat_messages but not shown as case-assistant threads.
_NON_CASE_ASSISTANT_SESSION_PREFIXES = (
    "editor:%",
    "tabular:%",
    "operations:%",
)


def _exclude_scoped_chat_sessions(query):
    """Case assistant list/history must not include editor/tabular/operations threads."""
    filtered = query
    for prefix in _NON_CASE_ASSISTANT_SESSION_PREFIXES:
        filtered = filtered.filter(
            (ChatMessage.session_id.is_(None))
            | (~ChatMessage.session_id.like(prefix))
        )
    return filtered


# Backward-compatible alias used by older call sites / tests.
_exclude_editor_sessions = _exclude_scoped_chat_sessions


class ChatHistoryService:
    """
    Сервис управления историей чата.
    
    Обеспечивает:
    - Группировку сообщений по сессиям
    - Автоматическое создание новых сессий
    - Сохранение и загрузку истории
    """
    
    def __init__(self, db: Session):
        """
        Инициализация сервиса
        
        Args:
            db: SQLAlchemy сессия
        """
        self.db = db
    
    def get_or_create_session(self, case_id: str) -> str:
        """
        Mint a new chat session when the caller did not pass session_id.

        Thread identity is client-authoritative (see case_chat_session.resolve_case_chat_session_id).
        """
        _ = case_id
        new_session_id = str(uuid.uuid4())
        logger.info("Creating new session %s for case %s", new_session_id, case_id)
        return new_session_id
    
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
            reasoning_steps=None,
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
        source_references: Optional[Any] = None,
        evidence: Optional[Any] = None,
        reasoning_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Обновить сообщение ассистента (после streaming)
        
        Args:
            message_id: ID сообщения
            content: Полный текст ответа
            source_references: Источники (опционально)
            reasoning_steps: Сохранённые шаги reasoning (SSE), опционально
            
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
            if evidence is not None:
                message.evidence = evidence if evidence else None
            if reasoning_steps is not None:
                message.reasoning_steps = reasoning_steps if reasoning_steps else None
            
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
        source_references: Optional[List[Dict[str, Any]]] = None,
        evidence: Optional[Any] = None,
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
            evidence=evidence if evidence else None,
            reasoning_steps=None,
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
        else:
            query = _exclude_editor_sessions(query)
        
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
        sessions_query = _exclude_editor_sessions(
            self.db.query(
                ChatMessage.session_id,
                func.min(ChatMessage.created_at).label('first_message_at'),
                func.max(ChatMessage.created_at).label('last_message_at'),
                func.count(ChatMessage.id).label('message_count'),
            ).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != "",
                ChatMessage.session_id.isnot(None),
            )
        ).group_by(ChatMessage.session_id).order_by(desc('last_message_at')).all()
        
        if not sessions_query:
            return []

        session_ids = [row.session_id for row in sessions_query if row.session_id]
        message_rows = self.db.query(
            ChatMessage.session_id,
            ChatMessage.content,
            ChatMessage.created_at,
        ).filter(
            ChatMessage.case_id == case_id,
            ChatMessage.session_id.in_(session_ids),
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
        ).order_by(
            ChatMessage.session_id.asc(),
            ChatMessage.created_at.asc(),
        ).all()

        previews: Dict[str, Dict[str, Any]] = {}
        for row in message_rows:
            sid = row.session_id
            if not sid:
                continue
            content = row.content or ""
            if sid not in previews:
                previews[sid] = {
                    "first_content": content,
                    "first_created_at": row.created_at,
                    "last_content": content,
                    "last_created_at": row.created_at,
                }
            else:
                previews[sid]["last_content"] = content
                previews[sid]["last_created_at"] = row.created_at

        sessions = []
        for session_row in sessions_query:
            session_id = session_row.session_id
            preview = previews.get(session_id or "", {})
            first_content = str(preview.get("first_content") or "")
            last_content = str(preview.get("last_content") or "")
            first_preview = f"{first_content[:100]}…" if len(first_content) > 100 else first_content
            last_preview = f"{last_content[:100]}…" if len(last_content) > 100 else last_content
            first_created_at = preview.get("first_created_at")
            last_created_at = preview.get("last_created_at")
            sessions.append({
                "session_id": session_id,
                "first_message": first_preview,
                "last_message": last_preview,
                "first_message_at": first_created_at.isoformat() if first_created_at else None,
                "last_message_at": last_created_at.isoformat() if last_created_at else None,
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


