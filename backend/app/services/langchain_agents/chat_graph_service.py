"""
ChatGraphService - сервис для интеграции ChatGraph в API endpoints.

Предоставляет унифицированный интерфейс для:
- Streaming ответов через ChatGraph
- Обработку разных режимов (normal, deep_think, garant, draft)
- Форматирование событий для assistant-ui
"""
from typing import AsyncGenerator, Optional, List, Dict, Any, Literal
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.graphs.chat_graph import (
    create_chat_graph,
    create_initial_chat_state,
    ChatGraphState
)
from app.models.user import User
from app.models.case import Case, ChatMessage
import logging
import json
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ChatGraphService:
    """
    Сервис для работы с ChatGraph.
    
    Обеспечивает:
    - Создание и кэширование графа
    - Streaming ответов с форматированием для assistant-ui
    - Сохранение сообщений в БД
    """
    
    _graph_instance = None
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Инициализация сервиса.
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.db = db
        self.rag_service = rag_service or RAGService()
        self.document_processor = document_processor or DocumentProcessor()
    
    def _get_or_create_graph(self):
        """Получить или создать экземпляр графа."""
        if ChatGraphService._graph_instance is None:
            ChatGraphService._graph_instance = create_chat_graph(
                db=self.db,
                rag_service=self.rag_service,
                document_processor=self.document_processor,
                use_checkpointing=True
            )
            logger.info("[ChatGraphService] Created new ChatGraph instance")
        return ChatGraphService._graph_instance
    
    def _determine_mode(
        self,
        deep_think: bool = False,
        legal_research: bool = False,
        draft_mode: bool = False
    ) -> Literal["normal", "deep_think", "garant", "draft"]:
        """
        Определить режим на основе флагов.
        
        Args:
            deep_think: Режим глубокого мышления
            legal_research: Режим поиска в ГАРАНТ
            draft_mode: Режим создания документа
        
        Returns:
            Режим работы графа
        """
        if draft_mode:
            return "draft"
        elif deep_think:
            return "deep_think"
        elif legal_research:
            return "garant"
        else:
            return "normal"
    
    def _get_or_create_session(self, case_id: str) -> str:
        """Получить или создать session_id для чата."""
        try:
            last_message = self.db.query(ChatMessage).filter(
                ChatMessage.case_id == case_id,
                ChatMessage.content.isnot(None),
                ChatMessage.content != ""
            ).order_by(ChatMessage.created_at.desc()).first()
            
            if last_message and last_message.created_at:
                time_diff = datetime.utcnow() - last_message.created_at
                if time_diff < timedelta(minutes=30) and last_message.session_id:
                    return last_message.session_id
            
            return str(uuid.uuid4())
        except Exception as e:
            logger.warning(f"[ChatGraphService] Error getting session: {e}")
            return str(uuid.uuid4())
    
    def _save_user_message(
        self,
        case_id: str,
        question: str,
        session_id: str
    ) -> str:
        """Сохранить сообщение пользователя в БД."""
        message_id = str(uuid.uuid4())
        try:
            user_message = ChatMessage(
                id=message_id,
                case_id=case_id,
                role="user",
                content=question,
                session_id=session_id
            )
            self.db.add(user_message)
            self.db.commit()
            logger.info(f"[ChatGraphService] Saved user message: {message_id}")
        except Exception as e:
            self.db.rollback()
            logger.warning(f"[ChatGraphService] Failed to save user message: {e}")
        return message_id
    
    def _save_assistant_message(
        self,
        case_id: str,
        content: str,
        session_id: str,
        citations: List[Dict] = None
    ) -> str:
        """Сохранить ответ ассистента в БД."""
        message_id = str(uuid.uuid4())
        try:
            assistant_message = ChatMessage(
                id=message_id,
                case_id=case_id,
                role="assistant",
                content=content,
                source_references=json.dumps(citations) if citations else None,
                session_id=session_id
            )
            self.db.add(assistant_message)
            self.db.commit()
            logger.info(f"[ChatGraphService] Saved assistant message: {message_id}")
        except Exception as e:
            self.db.rollback()
            logger.warning(f"[ChatGraphService] Failed to save assistant message: {e}")
        return message_id
    
    async def stream_response(
        self,
        case_id: str,
        question: str,
        user: User,
        deep_think: bool = False,
        legal_research: bool = False,
        draft_mode: bool = False,
        document_context: str = None,
        document_id: str = None,
        selected_text: str = None
    ) -> AsyncGenerator[str, None]:
        """
        Streaming ответ через ChatGraph.
        
        Args:
            case_id: ID дела
            question: Вопрос пользователя
            user: Текущий пользователь
            deep_think: Режим глубокого мышления
            legal_research: Режим поиска в ГАРАНТ
            draft_mode: Режим создания документа
            document_context: Контекст документа (для редактора)
            document_id: ID документа (для редактора)
            selected_text: Выделенный текст (для редактора)
        
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        logger.info(f"[ChatGraphService] Starting stream for case {case_id}, mode={self._determine_mode(deep_think, legal_research, draft_mode)}")
        
        # Проверяем доступ к делу
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id
        ).first()
        
        if not case:
            yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
            return
        
        # Получаем session_id
        session_id = self._get_or_create_session(case_id)
        
        # Сохраняем сообщение пользователя
        self._save_user_message(case_id, question, session_id)
        
        # Определяем режим
        mode = self._determine_mode(deep_think, legal_research, draft_mode)
        
        # Создаём начальное состояние
        initial_state = create_initial_chat_state(
            case_id=case_id,
            user_id=str(user.id),
            question=question,
            mode=mode,
            enable_garant=legal_research or mode == "garant",
            enable_citations=True,
            document_context=document_context,
            document_id=document_id,
            selected_text=selected_text
        )
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        # Генерируем thread_id для checkpointing
        thread_id = f"{case_id}_{session_id}_{datetime.utcnow().timestamp()}"
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25
        }
        
        full_response = ""
        citations = []
        document_created = None
        
        try:
            # Streaming через граф
            async for chunk in graph.astream(initial_state, config=config):
                # Извлекаем данные из chunk
                if isinstance(chunk, dict):
                    for node_name, node_data in chunk.items():
                        if not isinstance(node_data, dict):
                            continue
                        
                        # Обрабатываем messages
                        messages = node_data.get("messages", [])
                        for msg in messages:
                            if isinstance(msg, AIMessage) and msg.content:
                                content = msg.content
                                
                                # Отправляем дельту
                                if content != full_response:
                                    if full_response and content.startswith(full_response):
                                        delta = content[len(full_response):]
                                    else:
                                        delta = content
                                    
                                    if delta:
                                        yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': delta})}\n\n"
                                    
                                    full_response = content
                        
                        # Обрабатываем response (финальный ответ)
                        response = node_data.get("response")
                        if response and response != full_response:
                            if full_response and response.startswith(full_response):
                                delta = response[len(full_response):]
                            else:
                                delta = response
                            
                            if delta:
                                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': delta})}\n\n"
                            
                            full_response = response
                        
                        # Обрабатываем citations
                        node_citations = node_data.get("citations")
                        if node_citations:
                            citations = node_citations
                        
                        # Обрабатываем document_created (draft mode)
                        doc_created = node_data.get("document_created")
                        if doc_created:
                            document_created = doc_created
                            
                            # Отправляем событие о создании документа
                            yield f"data: {json.dumps({'type': 'document-card', 'data': doc_created})}\n\n"
                        
                        # Обрабатываем thinking_steps (deep_think mode)
                        thinking_steps = node_data.get("thinking_steps")
                        if thinking_steps:
                            for step in thinking_steps:
                                yield f"data: {json.dumps({'type': 'thinking-step', 'data': step})}\n\n"
                        
                        # Обрабатываем current_phase для прогресса
                        phase = node_data.get("current_phase")
                        if phase:
                            yield f"data: {json.dumps({'type': 'status', 'phase': phase})}\n\n"
            
            # Если ответ пустой, отправляем fallback
            if not full_response:
                full_response = "Не удалось получить ответ. Попробуйте переформулировать вопрос."
                yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': full_response})}\n\n"
            
            # Отправляем citations если есть
            if citations:
                yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"
            
            # Сохраняем ответ ассистента
            self._save_assistant_message(case_id, full_response, session_id, citations)
            
            # Отправляем финальное событие
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'stop'})}\n\n"
            
            logger.info(f"[ChatGraphService] Stream completed: {len(full_response)} chars")
            
        except Exception as e:
            logger.error(f"[ChatGraphService] Stream error: {e}", exc_info=True)
            error_msg = f"Ошибка: {str(e)}"
            yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'error', 'error': str(e)})}\n\n"
            
            # Сохраняем ошибку как ответ
            self._save_assistant_message(case_id, error_msg, session_id)


# Глобальный экземпляр для переиспользования
_chat_graph_service: Optional[ChatGraphService] = None


def get_chat_graph_service(
    db: Session,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> ChatGraphService:
    """
    Получить экземпляр ChatGraphService.
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        ChatGraphService instance
    """
    global _chat_graph_service
    
    # Создаём новый экземпляр с текущим db session
    # (db session не должен переиспользоваться между запросами)
    return ChatGraphService(
        db=db,
        rag_service=rag_service or RAGService(),
        document_processor=document_processor or DocumentProcessor()
    )



