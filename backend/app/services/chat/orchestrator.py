"""
Chat Orchestrator - Главный оркестратор чат-запросов

Единая точка входа для обработки всех типов запросов:
- RAG (простые вопросы)
- Agent (сложные задачи)
- Draft (создание документов)
- Editor (редактирование документов)
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from dataclasses import dataclass
from sqlalchemy.orm import Session
import logging

from app.services.chat.events import SSESerializer, SSEEvent
from app.services.chat.classifier import RequestClassifier, ClassificationResult
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.rag_handler import RAGHandler
from app.services.chat.draft_handler import DraftHandler
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.agent_handler import AgentHandler
from app.services.chat.metrics import get_metrics, MetricTimer
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.models.case import Case
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class ChatRequest:
    """Запрос к чату"""
    case_id: str
    question: str
    current_user: User
    
    # Режимы
    web_search: bool = False
    legal_research: bool = False
    deep_think: bool = False
    draft_mode: bool = False
    
    # Контекст редактора
    document_context: Optional[str] = None
    document_id: Optional[str] = None
    selected_text: Optional[str] = None
    
    # Шаблон для draft mode
    template_file_id: Optional[str] = None
    template_file_content: Optional[str] = None
    
    # Прикреплённые файлы
    attached_file_ids: Optional[List[str]] = None


class ChatOrchestrator:
    """
    Главный оркестратор чат-запросов.
    
    Определяет тип запроса и делегирует обработку соответствующему handler'у:
    - DraftHandler: создание документов
    - EditorHandler: редактирование документов
    - RAGHandler: ответы на вопросы
    - AgentHandler: выполнение сложных задач
    
    Интегрирует:
    - Метрики производительности
    - Structured logging
    - Error handling
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None,
        classifier: Optional[RequestClassifier] = None
    ):
        """
        Инициализация оркестратора
        
        Args:
            db: SQLAlchemy сессия
            rag_service: RAG сервис (создаётся если не передан)
            document_processor: Document processor (создаётся если не передан)
            classifier: Классификатор запросов (создаётся если не передан)
        """
        self.db = db
        self.rag_service = rag_service or RAGService()
        self.document_processor = document_processor or DocumentProcessor()
        
        # Инициализируем классификатор
        if classifier:
            self.classifier = classifier
        else:
            from app.services.llm_factory import create_llm
            from app.services.external_sources.cache_manager import get_cache_manager
            
            llm = create_llm(temperature=0.0, max_tokens=500)
            cache = get_cache_manager()
            self.classifier = RequestClassifier(llm=llm, cache=cache)
        
        # Инициализируем сервисы
        self.history_service = ChatHistoryService(db)
        
        # Инициализируем handlers
        self.rag_handler = RAGHandler(self.rag_service, db)
        self.draft_handler = DraftHandler(db)
        self.editor_handler = EditorHandler(self.rag_service, db)
        self.agent_handler = AgentHandler(self.rag_service, db)
        
        # Метрики
        self.metrics = get_metrics()
        
        logger.info("ChatOrchestrator initialized")
    
    async def process_request(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """
        Обработать запрос к чату
        
        Args:
            request: ChatRequest с параметрами запроса
            
        Yields:
            SSE события (строки в формате "data: {...}\n\n")
        """
        import time
        import json
        
        start_time = time.time()
        mode = self._determine_mode(request)
        
        try:
            # Записываем метрику запроса
            self.metrics.record_request(mode)
            
            # Проверяем доступ к делу
            case = self._verify_case_access(request.case_id, request.current_user)
            if not case:
                self.metrics.record_error(f"{mode}:case_not_found")
                yield SSESerializer.error("Дело не найдено")
                return
            
            # Создаём сессию и сохраняем сообщение пользователя
            session_id = self.history_service.get_or_create_session(request.case_id)
            user_message = self.history_service.save_user_message(
                case_id=request.case_id,
                content=request.question,
                session_id=session_id
            )
            
            # Создаём placeholder для ответа ассистента
            assistant_placeholder = self.history_service.create_assistant_placeholder(
                case_id=request.case_id,
                session_id=session_id
            )
            
            # Определяем handler и обрабатываем запрос
            full_response = ""
            
            try:
                async for event in self._route_to_handler(request, session_id):
                    yield event
                    # Извлекаем текст для сохранения
                    full_response += self._extract_text_from_event(event)
                
            finally:
                # Сохраняем ответ в БД
                if full_response:
                    self.history_service.update_assistant_message(
                        message_id=assistant_placeholder.id,
                        content=full_response
                    )
                
                # Записываем метрику латентности
                latency = time.time() - start_time
                self.metrics.record_latency(mode, latency)
                logger.info(f"[ChatOrchestrator] {mode} completed in {latency:.2f}s, response length: {len(full_response)}")
                
        except Exception as e:
            self.metrics.record_error(f"{mode}:exception")
            logger.error(f"[ChatOrchestrator] Error in {mode}: {e}", exc_info=True)
            yield SSESerializer.error(str(e))
    
    def _determine_mode(self, request: ChatRequest) -> str:
        """Определить режим обработки запроса"""
        if request.draft_mode:
            return "draft"
        elif request.document_context:
            return "editor"
        else:
            return "rag"
    
    async def _route_to_handler(
        self,
        request: ChatRequest,
        session_id: str
    ) -> AsyncGenerator[str, None]:
        """Маршрутизация к соответствующему handler'у"""
        
        if request.draft_mode:
            # Draft mode: создание документов
            chat_history = self.history_service.get_history_as_text(
                request.case_id, session_id
            )
            
            async for event in self.draft_handler.handle(
                case_id=request.case_id,
                question=request.question,
                current_user=request.current_user,
                chat_history=chat_history,
                template_file_id=request.template_file_id,
                template_file_content=request.template_file_content
            ):
                yield event
        
        elif request.document_context:
            # Editor mode: редактирование документов
            async for event in self.editor_handler.handle(
                case_id=request.case_id,
                question=request.question,
                current_user=request.current_user,
                document_id=request.document_id or "",
                document_context=request.document_context,
                selected_text=request.selected_text
            ):
                yield event
        
        else:
            # Проверяем наличие документов
            from app.models.case import File as FileModel
            file_count = self.db.query(FileModel).filter(
                FileModel.case_id == request.case_id
            ).count()
            
            if file_count == 0:
                yield SSESerializer.error(
                    "В деле нет загруженных документов. Пожалуйста, сначала загрузите документы."
                )
                return
            
            # Классифицируем запрос
            classification = await self.classifier.classify(request.question)
            self.metrics.record_classification(classification.label)
            
            if classification.is_task and classification.confidence >= 0.8:
                # Agent mode: выполнение сложных задач
                logger.info(f"[ChatOrchestrator] Routing to AgentHandler (confidence: {classification.confidence:.2f})")
                
                async for event in self.agent_handler.handle(
                    case_id=request.case_id,
                    question=request.question,
                    current_user=request.current_user,
                    auto_approve=False  # Требуем подтверждения плана
                ):
                    yield event
            else:
                # RAG mode: ответы на вопросы
                chat_history = self.history_service.get_history_for_context(
                    request.case_id, session_id
                )
                
                async for event in self.rag_handler.handle(
                    case_id=request.case_id,
                    question=request.question,
                    current_user=request.current_user,
                    chat_history=chat_history,
                    legal_research=request.legal_research,
                    deep_think=request.deep_think,
                    web_search=request.web_search
                ):
                    yield event
    
    def _extract_text_from_event(self, event: str) -> str:
        """Извлечь текст из SSE события"""
        import json
        
        if "textDelta" not in event:
            return ""
        
        try:
            data = json.loads(event.replace("data: ", "").strip())
            return data.get("textDelta", "")
        except:
            return ""
    
    def _verify_case_access(self, case_id: str, user: User) -> Optional[Case]:
        """
        Проверить доступ пользователя к делу
        
        Returns:
            Case если доступ есть, None иначе
        """
        case = self.db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == user.id
        ).first()
        
        if not case:
            logger.warning(f"[ChatOrchestrator] Case not found: {case_id} for user {user.id}")
        
        return case
    
    async def classify_request(self, question: str) -> ClassificationResult:
        """
        Классифицировать запрос (task/question)
        
        Args:
            question: Текст запроса
            
        Returns:
            ClassificationResult
        """
        return await self.classifier.classify(question)


# =============================================================================
# Factory function для создания оркестратора
# =============================================================================

def get_chat_orchestrator(db: Session) -> ChatOrchestrator:
    """
    Создать ChatOrchestrator с зависимостями
    
    Args:
        db: SQLAlchemy сессия
        
    Returns:
        ChatOrchestrator instance
    """
    return ChatOrchestrator(db=db)


