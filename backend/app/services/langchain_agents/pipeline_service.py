"""Pipeline Service - унифицированный API для обработки запросов (RAG и Agent)"""
from typing import AsyncGenerator, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.complexity_classifier import ComplexityClassifier, ClassificationResult
from app.services.langchain_agents.pipeline_router import PipelineRouterMiddleware
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.audit_logger import AuditLogger, get_audit_logger
from app.services.langchain_agents.pii_redaction import PIIRedactionMiddleware
from app.services.langchain_agents.streaming_events import (
    RAGResponseEvent,
    AgentProgressEvent,
    AgentCompleteEvent,
    ErrorEvent,
    SourcesEvent,
    PlanReadyEvent
)
from app.services.llm_factory import create_llm
import json
import logging
import asyncio
import time

logger = logging.getLogger(__name__)


class PipelineService:
    """
    Унифицированный сервис для обработки запросов:
    - simple (RAG) → быстрый ответ на основе документов
    - complex (Agent) → многошаговая агентная оркестрация
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService,
        document_processor: DocumentProcessor,
        classifier: Optional[ComplexityClassifier] = None,
        audit_logger: Optional[AuditLogger] = None,
        pii_redactor: Optional[PIIRedactionMiddleware] = None
    ):
        """
        Инициализация PipelineService
        
        Args:
            db: Сессия базы данных
            rag_service: RAG service для поиска документов
            document_processor: Document processor
            classifier: Опциональный ComplexityClassifier (создаётся автоматически если не передан)
            audit_logger: Опциональный AuditLogger (создаётся автоматически если не передан)
            pii_redactor: Опциональный PIIRedactionMiddleware (создаётся автоматически если не передан)
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Создаём classifier если не передан
        if classifier is None:
            llm = create_llm(temperature=0.0, top_p=1.0, max_tokens=100)
            from app.routes.assistant_chat import get_classification_cache
            cache = get_classification_cache()
            classifier = ComplexityClassifier(llm=llm, cache=cache)
        
        self.classifier = classifier
        
        # Создаём router middleware
        self.router = PipelineRouterMiddleware(classifier=classifier)
        
        # Создаём coordinator для agent пути
        self.coordinator = AgentCoordinator(
            db=db,
            rag_service=rag_service,
            document_processor=document_processor,
            use_legora_workflow=True
        )
        
        # Инициализируем audit logger и PII redactor
        self.audit_logger = audit_logger or get_audit_logger()
        self.pii_redactor = pii_redactor or PIIRedactionMiddleware(enable_redaction=True)
    
    async def process_request(
        self,
        case_id: str,
        query: str,
        current_user: User,
        web_search: bool = False,
        legal_research: bool = False,
        deep_think: bool = False
    ) -> ClassificationResult:
        """
        Обработать запрос и определить путь (RAG или Agent)
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Returns:
            ClassificationResult с определённым путём
        """
        start_time = time.time()
        
        # Маскируем PII в запросе для логирования
        redacted_query = self.pii_redactor.redact_text(query)
        
        # Классифицируем запрос
        classification = self.classifier.classify(
            query=query,
            context={
                "case_id": case_id,
                "user_id": current_user.id
            }
        )
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Логируем классификацию
        self.audit_logger.log_classification(
            query=redacted_query,
            classification_result={
                "label": classification.label,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
                "recommended_path": classification.recommended_path
            },
            case_id=case_id,
            user_id=str(current_user.id)
        )
        
        # Логируем маршрутизацию
        self.audit_logger.log_routing(
            query=redacted_query,
            classification={
                "label": classification.label,
                "confidence": classification.confidence
            },
            case_id=case_id,
            user_id=str(current_user.id),
            routing_path=classification.recommended_path
        )
        
        logger.info(
            f"[PipelineService] Query classified as {classification.label} "
            f"(confidence: {classification.confidence:.2f}, path: {classification.recommended_path}, latency: {latency_ms:.2f}ms)"
        )
        
        return classification
    
    async def stream_response(
        self,
        case_id: str,
        query: str,
        current_user: User,
        classification: Optional[ClassificationResult] = None,
        web_search: bool = False,
        legal_research: bool = False,
        deep_think: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Потоковая обработка ответа на основе классификации
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            classification: Опциональная классификация (будет выполнена если не передана)
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        # Классифицируем если не передана
        if classification is None:
            classification = await self.process_request(
                case_id=case_id,
                query=query,
                current_user=current_user,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think
            )
        
        # Маршрутизируем на основе классификации
        if classification.recommended_path == "rag":
            # RAG путь - простой вопрос
            async for chunk in self._stream_rag_response(
                case_id=case_id,
                query=query,
                current_user=current_user,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think
            ):
                yield chunk
        else:
            # Agent путь - сложная задача
            async for chunk in self._stream_agent_response(
                case_id=case_id,
                query=query,
                current_user=current_user,
                classification=classification,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think
            ):
                yield chunk
    
    async def _stream_rag_response(
        self,
        case_id: str,
        query: str,
        current_user: User,
        web_search: bool = False,
        legal_research: bool = False,
        deep_think: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Потоковый ответ через RAG (простой путь)
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        try:
            logger.info(f"[PipelineService:RAG] Processing simple query for case {case_id}")
            
            # Импортируем функцию из assistant_chat для RAG обработки
            # Это временное решение - в будущем можно вынести RAG логику в отдельный сервис
            from app.routes.assistant_chat import stream_chat_response
            
            # Используем существующую функцию для RAG ответа
            # Но сначала нужно проверить, что это действительно простой вопрос
            # (stream_chat_response делает свою классификацию, но мы уже знаем путь)
            
            # TODO: Вынести RAG логику в отдельный метод для чистоты архитектуры
            # Пока используем существующую функцию через обходной путь
            
            # Создаём минимальный BackgroundTasks для совместимости
            from fastapi import BackgroundTasks
            background_tasks = BackgroundTasks()
            
            # Вызываем stream_chat_response, но он снова классифицирует
            # В будущем нужно передать флаг, что путь уже определён
            async for chunk in stream_chat_response(
                case_id=case_id,
                question=query,
                db=self.db,
                current_user=current_user,
                background_tasks=background_tasks,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think
            ):
                yield chunk
                
        except Exception as e:
            logger.error(f"[PipelineService:RAG] Error in RAG response: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': f'Ошибка обработки запроса: {str(e)}'})}\n\n"
    
    async def _stream_agent_response(
        self,
        case_id: str,
        query: str,
        current_user: User,
        classification: ClassificationResult,
        web_search: bool = False,
        legal_research: bool = False,
        deep_think: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Потоковый ответ через Agent оркестрацию (сложный путь)
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            classification: Результат классификации
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        try:
            logger.info(f"[PipelineService:Agent] Processing complex task for case {case_id}")
            
            # Фаза 8.3: Используем унифицированные streaming events
            # Отправляем событие начала планирования
            progress_event = AgentProgressEvent(
                agent_name="planning",
                step="Планирование анализа",
                progress=0.0,
                message="Создание плана выполнения задачи..."
            )
            yield progress_event.to_sse_format()
            
            # Создаём callback для streaming событий из coordinator
            async def step_callback(event):
                """Callback для получения событий из coordinator"""
                if hasattr(event, 'to_sse_format'):
                    yield event.to_sse_format()
                else:
                    # Если это dict или другой формат, преобразуем
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            
            # Используем coordinator для выполнения анализа с streaming
            # TODO: Интегрировать полноценный streaming из coordinator.stream_analysis()
            # Пока используем run_analysis с step_callback
            
            # Выполняем анализ через coordinator
            result = self.coordinator.run_analysis(
                case_id=case_id,
                analysis_types=[],  # Пустой список - будет использовано планирование
                user_task=query,
                config=None,
                step_callback=step_callback  # Передаём callback для streaming
            )
            
            # Отправляем событие завершения
            complete_event = AgentCompleteEvent(
                agent_name="analysis",
                result=result,
                success=True,
                metadata={"case_id": case_id}
            )
            yield complete_event.to_sse_format()
            
            # Форматируем финальный результат для отображения
            response_text = f"Анализ выполнен успешно. Получено результатов: {len(result)}"
            rag_event = RAGResponseEvent(
                text_delta=response_text,
                metadata={"result_count": len(result)}
            )
            yield rag_event.to_sse_format()
            
            yield f"data: {json.dumps({'textDelta': ''})}\n\n"
            
        except Exception as e:
            logger.error(f"[PipelineService:Agent] Error in Agent response: {e}", exc_info=True)
            error_event = ErrorEvent(error=f"Ошибка выполнения задачи: {str(e)}")
            yield error_event.to_sse_format()
            
            # Логируем ошибку
            self.audit_logger.log_error(
                error=e,
                context={"case_id": case_id, "query": self.pii_redactor.redact_text(query)},
                case_id=case_id,
                user_id=str(current_user.id)
            )

