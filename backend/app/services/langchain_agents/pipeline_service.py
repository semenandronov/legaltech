"""Pipeline Service - унифицированный API для обработки запросов (RAG и Agent)"""
from typing import AsyncGenerator, Dict, Any, Optional, Union
from sqlalchemy.orm import Session
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.complexity_classifier import ComplexityClassifier, ClassificationResult as OldClassificationResult
from app.services.langchain_agents.advanced_complexity_classifier import (
    AdvancedComplexityClassifier,
    EnhancedClassificationResult
)
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
    - hybrid (RAG + Agent) → комбинированный путь
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService,
        document_processor: DocumentProcessor,
        classifier: Optional[Union[AdvancedComplexityClassifier, ComplexityClassifier]] = None,
        audit_logger: Optional[AuditLogger] = None,
        pii_redactor: Optional[PIIRedactionMiddleware] = None,
        use_advanced_classifier: bool = True
    ):
        """
        Инициализация PipelineService
        
        Args:
            db: Сессия базы данных
            rag_service: RAG service для поиска документов
            document_processor: Document processor
            classifier: Опциональный классификатор (AdvancedComplexityClassifier или ComplexityClassifier)
            audit_logger: Опциональный AuditLogger (создаётся автоматически если не передан)
            pii_redactor: Опциональный PIIRedactionMiddleware (создаётся автоматически если не передан)
            use_advanced_classifier: Использовать AdvancedComplexityClassifier по умолчанию (True) или старый ComplexityClassifier (False)
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Создаём classifier если не передан
        if classifier is None:
            llm = create_llm(temperature=0.0, top_p=1.0, max_tokens=500)  # Увеличили для enhanced классификации
            from app.routes.assistant_chat import get_classification_cache
            cache = get_classification_cache()
            
            if use_advanced_classifier:
                classifier = AdvancedComplexityClassifier(llm=llm, cache=cache, confidence_threshold=0.7)
            else:
                classifier = ComplexityClassifier(llm=llm, cache=cache)
        
        self.classifier = classifier
        self.use_advanced_classifier = isinstance(classifier, AdvancedComplexityClassifier)
        
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
    ) -> Union[EnhancedClassificationResult, OldClassificationResult]:
        """
        Обработать запрос и определить путь (RAG, Agent или Hybrid)
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Returns:
            EnhancedClassificationResult или ClassificationResult с определённым путём
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
        classification_dict = {
            "label": classification.label,
            "confidence": classification.confidence,
            "rationale": getattr(classification, 'rationale', None) or classification.rationale if hasattr(classification, 'rationale') else "N/A",
            "recommended_path": classification.recommended_path
        }
        
        # Добавляем дополнительные поля для EnhancedClassificationResult
        if isinstance(classification, EnhancedClassificationResult):
            classification_dict.update({
                "requires_clarification": classification.requires_clarification,
                "suggested_agents": classification.suggested_agents,
                "rag_queries": classification.rag_queries,
                "estimated_complexity": classification.estimated_complexity
            })
        
        self.audit_logger.log_classification(
            query=redacted_query,
            classification_result=classification_dict,
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
        classification: Optional[Union[EnhancedClassificationResult, OldClassificationResult]] = None,
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
        
        # Проверяем, требуется ли уточнение
        if isinstance(classification, EnhancedClassificationResult) and classification.requires_clarification:
            logger.info(f"[PipelineService] Classification requires clarification (confidence: {classification.confidence:.2f})")
            # Отправляем событие с просьбой об уточнении
            clarification_event = {
                "type": "clarification_needed",
                "message": f"Запрос неоднозначен (уверенность: {classification.confidence:.2f}). {classification.rationale}",
                "classification": classification.dict()
            }
            yield f"data: {json.dumps(clarification_event, ensure_ascii=False)}\n\n"
            return
        
        # Маршрутизируем на основе классификации
        if classification.recommended_path == "rag":
            # RAG путь - простой вопрос
            async for chunk in self._stream_rag_response(
                case_id=case_id,
                query=query,
                current_user=current_user,
                classification=classification,
                web_search=web_search,
                legal_research=legal_research,
                deep_think=deep_think
            ):
                yield chunk
        elif classification.recommended_path == "hybrid":
            # Hybrid путь - комбинированный (RAG + Agent)
            async for chunk in self._stream_hybrid_response(
                case_id=case_id,
                query=query,
                current_user=current_user,
                classification=classification,
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
        classification: Optional[Union[EnhancedClassificationResult, OldClassificationResult]] = None,
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
        classification: Union[EnhancedClassificationResult, OldClassificationResult],
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
            
            # Используем новый stream_analysis_events для нативного streaming через astream_events
            # #region debug log
            import json as json_module
            log_file = "/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log"
            try:
                with open(log_file, "a") as f:
                    f.write(json_module.dumps({"timestamp": time.time(), "sessionId": "debug-session", "runId": "pipeline-start", "hypothesisId": "E", "location": "pipeline_service.py:363", "message": "Starting stream_analysis_events", "data": {"case_id": case_id}}) + "\n")
            except: pass
            # #endregion
            async for event in self.coordinator.stream_analysis_events(
                case_id=case_id,
                user_task=query,
                config=None
            ):
                event_type = event.get("type")
                # #region debug log
                try:
                    with open(log_file, "a") as f:
                        f.write(json_module.dumps({"timestamp": time.time(), "sessionId": "debug-session", "runId": "pipeline-event", "hypothesisId": "E", "location": "pipeline_service.py:369", "message": "Received event", "data": {"case_id": case_id, "event_type": event_type}}) + "\n")
                except: pass
                # #endregion
                
                if event_type == "token":
                    # LLM токены - отправляем как textDelta
                    content = event.get("content", "")
                    if content:
                        rag_event = RAGResponseEvent(text_delta=content)
                        yield rag_event.to_sse_format()
                
                elif event_type == "reasoning":
                    # Reasoning события - отправляем как кастомное событие
                    reasoning_data = event.get("data", {})
                    reasoning_event = {
                        'type': 'reasoning',
                        'phase': reasoning_data.get('phase', ''),
                        'step': reasoning_data.get('step', 0),
                        'totalSteps': reasoning_data.get('total_steps', 0),
                        'content': reasoning_data.get('content', '')
                    }
                    yield f"data: {json.dumps(reasoning_event, ensure_ascii=False)}\n\n"
                
                elif event_type == "node_complete":
                    # Завершение node - отправляем progress event
                    node_name = event.get("node", "")
                    progress_event = AgentProgressEvent(
                        agent_name=node_name,
                        step=f"Завершён этап: {node_name}",
                        progress=1.0,
                        message=f"Этап {node_name} завершён"
                    )
                    yield progress_event.to_sse_format()
                
                elif event_type == "interrupt":
                    # Interrupt событие - отправляем human feedback request
                    interrupt_data = event.get("data", {})
                    thread_id = event.get("thread_id")
                    
                    # Используем JSON напрямую для interrupt событий
                    interrupt_event = {
                        "type": "interrupt",
                        "request_id": interrupt_data.get("request_id", ""),
                        "question": interrupt_data.get("question", "Требуется обратная связь"),
                        "interrupt_type": interrupt_data.get("type"),
                        "thread_id": thread_id,
                        "payload": interrupt_data
                    }
                    yield f"data: {json.dumps(interrupt_event, ensure_ascii=False)}\n\n"
                
                elif event_type == "completion":
                    # Финальное событие о завершении анализа
                    # #region debug log
                    try:
                        with open(log_file, "a") as f:
                            f.write(json_module.dumps({"timestamp": time.time(), "sessionId": "debug-session", "runId": "pipeline-completion", "hypothesisId": "A,E", "location": "pipeline_service.py:417", "message": "Processing completion event", "data": {"case_id": case_id}}) + "\n")
                    except: pass
                    # #endregion
                    completion_event = AgentProgressEvent(
                        agent_name="system",
                        step="Анализ завершён",
                        progress=1.0,
                        message="Все этапы анализа успешно выполнены"
                    )
                    yield completion_event.to_sse_format()
                    # #region debug log
                    try:
                        with open(log_file, "a") as f:
                            f.write(json_module.dumps({"timestamp": time.time(), "sessionId": "debug-session", "runId": "pipeline-completion-sent", "hypothesisId": "A,E", "location": "pipeline_service.py:425", "message": "Completion event sent to client", "data": {"case_id": case_id}}) + "\n")
                    except: pass
                    # #endregion
                
                elif event_type == "error":
                    # Ошибка
                    error_msg = event.get("error", "Неизвестная ошибка")
                    error_event = ErrorEvent(error=error_msg)
                    yield error_event.to_sse_format()
            
            # Отправляем финальное событие завершения
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
    
    async def _stream_hybrid_response(
        self,
        case_id: str,
        query: str,
        current_user: User,
        classification: EnhancedClassificationResult,
        web_search: bool = False,
        legal_research: bool = False,
        deep_think: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Потоковый ответ через Hybrid путь (RAG + Agent)
        
        Сначала выполняет RAG запросы, затем запускает агентов
        
        Args:
            case_id: Идентификатор дела
            query: Запрос пользователя
            current_user: Текущий пользователь
            classification: Результат классификации (EnhancedClassificationResult)
            web_search: Включить веб-поиск
            legal_research: Включить юридическое исследование
            deep_think: Включить глубокое размышление
            
        Yields:
            JSON строки в формате assistant-ui SSE
        """
        try:
            logger.info(f"[PipelineService:Hybrid] Processing hybrid request for case {case_id}")
            
            # Фаза 1: RAG запросы (если есть)
            rag_queries = classification.rag_queries if classification.rag_queries else [query]
            
            if rag_queries:
                progress_event = AgentProgressEvent(
                    agent_name="rag",
                    step="Фаза 1: Поиск информации",
                    progress=0.0,
                    message=f"Выполняю поиск по {len(rag_queries)} запросу(ам)..."
                )
                yield progress_event.to_sse_format()
                
                # Обрабатываем каждый RAG запрос
                for i, rag_query in enumerate(rag_queries):
                    logger.info(f"[PipelineService:Hybrid] Processing RAG query {i+1}/{len(rag_queries)}: {rag_query[:50]}...")
                    
                    async for chunk in self._stream_rag_response(
                        case_id=case_id,
                        query=rag_query,
                        current_user=current_user,
                        classification=None,  # Не классифицируем повторно
                        web_search=web_search,
                        legal_research=legal_research,
                        deep_think=deep_think
                    ):
                        yield chunk
                    
                    # Разделитель между RAG ответами (если несколько)
                    if i < len(rag_queries) - 1:
                        separator = {
                            "type": "textDelta",
                            "textDelta": "\n\n---\n\n"
                        }
                        yield f"data: {json.dumps(separator, ensure_ascii=False)}\n\n"
            
            # Фаза 2: Agent обработка
            progress_event = AgentProgressEvent(
                agent_name="agents",
                step="Фаза 2: Анализ через агентов",
                progress=0.5,
                message=f"Запускаю анализ через агентов: {', '.join(classification.suggested_agents) if classification.suggested_agents else 'автоматический выбор'}"
            )
            yield progress_event.to_sse_format()
            
            # Создаём модифицированный запрос для агентов
            # Если были RAG запросы, добавляем контекст
            agent_query = query
            if rag_queries and len(rag_queries) > 0:
                agent_query = f"{query} (на основе предыдущего поиска: {', '.join(rag_queries[:2])})"
            
            # Конвертируем EnhancedClassificationResult в формат для агентов
            # Используем suggested_agents для определения analysis_types
            analysis_types = classification.suggested_agents if classification.suggested_agents else []
            
            # Если analysis_types пустой, используем стандартный путь через coordinator
            if not analysis_types:
                # Используем стандартный agent путь
                async for chunk in self._stream_agent_response(
                    case_id=case_id,
                    query=agent_query,
                    current_user=current_user,
                    classification=classification,
                    web_search=web_search,
                    legal_research=legal_research,
                    deep_think=deep_think
                ):
                    yield chunk
            else:
                # TODO: Реализовать запуск конкретных агентов через coordinator
                # Пока используем стандартный путь
                logger.info(f"[PipelineService:Hybrid] Suggested agents: {analysis_types}, using standard agent path")
                async for chunk in self._stream_agent_response(
                    case_id=case_id,
                    query=agent_query,
                    current_user=current_user,
                    classification=classification,
                    web_search=web_search,
                    legal_research=legal_research,
                    deep_think=deep_think
                ):
                    yield chunk
            
            # Финальное событие завершения
            complete_event = AgentProgressEvent(
                agent_name="hybrid",
                step="Завершено",
                progress=1.0,
                message="Гибридная обработка завершена"
            )
            yield complete_event.to_sse_format()
            
        except Exception as e:
            logger.error(f"[PipelineService:Hybrid] Error in Hybrid response: {e}", exc_info=True)
            error_event = ErrorEvent(error=f"Ошибка выполнения гибридной обработки: {str(e)}")
            yield error_event.to_sse_format()
            
            # Логируем ошибку
            self.audit_logger.log_error(
                error=e,
                context={"case_id": case_id, "query": self.pii_redactor.redact_text(query), "type": "hybrid"},
                case_id=case_id,
                user_id=str(current_user.id)
            )

