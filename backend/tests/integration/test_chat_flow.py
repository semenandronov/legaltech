"""
Integration Tests for Chat Flow

Тестирует полный flow чата:
- Классификация запросов
- RAG ответы
- Draft mode (создание документов)
- Editor mode (редактирование)
- SSE события
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from sqlalchemy.orm import Session
import json

# Fixtures
from tests.conftest import (
    db_session,
    test_user,
    test_case,
)


# =============================================================================
# Тесты классификатора
# =============================================================================

class TestRequestClassifier:
    """Тесты для RequestClassifier"""
    
    def test_classify_article_request_as_question(self):
        """Запрос статьи кодекса → question"""
        from app.services.chat.classifier import RequestClassifier
        
        classifier = RequestClassifier()
        
        # Rule-based должен сработать
        result = classifier._check_rule_based("Пришли статью 135 ГПК")
        
        assert result is not None
        assert result.label == "question"
        assert result.confidence >= 0.9
    
    def test_classify_greeting_as_question(self):
        """Приветствие → question"""
        from app.services.chat.classifier import RequestClassifier
        
        classifier = RequestClassifier()
        
        result = classifier._check_rule_based("Привет, как дела?")
        
        assert result is not None
        assert result.label == "question"
    
    def test_classify_extraction_as_task(self):
        """Запрос извлечения данных → task"""
        from app.services.chat.classifier import RequestClassifier
        
        classifier = RequestClassifier()
        
        result = classifier._check_rule_based("Извлеки все даты из документов")
        
        assert result is not None
        assert result.label == "task"
    
    def test_normalize_text(self):
        """Тест нормализации текста"""
        from app.services.chat.classifier import RequestClassifier
        
        text = "  Привет   мир  "
        normalized = RequestClassifier.normalize_text(text)
        
        assert normalized == "привет мир"
    
    def test_make_cache_key_consistent(self):
        """Cache key должен быть одинаковым для эквивалентных запросов"""
        from app.services.chat.classifier import RequestClassifier
        
        key1 = RequestClassifier.make_cache_key("Привет мир")
        key2 = RequestClassifier.make_cache_key("  привет   мир  ")
        
        assert key1 == key2


# =============================================================================
# Тесты SSE событий
# =============================================================================

class TestSSEEvents:
    """Тесты для SSE событий"""
    
    def test_text_delta_event_serialization(self):
        """TextDeltaEvent сериализуется корректно"""
        from app.services.chat.events import TextDeltaEvent
        
        event = TextDeltaEvent(text_delta="Привет")
        sse = event.to_sse()
        
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        
        # Парсим JSON
        json_str = sse.replace("data: ", "").strip()
        data = json.loads(json_str)
        
        assert data["textDelta"] == "Привет"
    
    def test_error_event_serialization(self):
        """ErrorEvent сериализуется корректно"""
        from app.services.chat.events import ErrorEvent
        
        event = ErrorEvent(error="Что-то пошло не так")
        sse = event.to_sse()
        
        json_str = sse.replace("data: ", "").strip()
        data = json.loads(json_str)
        
        assert data["error"] == "Что-то пошло не так"
    
    def test_citations_event_serialization(self):
        """CitationsEvent сериализуется корректно"""
        from app.services.chat.events import CitationsEvent, Citation
        
        citation = Citation(
            source_id="doc1",
            file_name="contract.pdf",
            quote="Пункт 1.1"
        )
        event = CitationsEvent(citations=[citation])
        sse = event.to_sse()
        
        json_str = sse.replace("data: ", "").strip()
        data = json.loads(json_str)
        
        assert data["type"] == "citations"
        assert len(data["citations"]) == 1
        assert data["citations"][0]["file_name"] == "contract.pdf"
    
    def test_reasoning_event_serialization(self):
        """ReasoningEvent сериализуется корректно"""
        from app.services.chat.events import ReasoningEvent
        
        event = ReasoningEvent(
            phase="understanding",
            step=1,
            total_steps=5,
            content="Анализирую запрос…"
        )
        sse = event.to_sse()
        
        json_str = sse.replace("data: ", "").strip()
        data = json.loads(json_str)
        
        assert data["type"] == "reasoning"
        assert data["phase"] == "understanding"
        assert data["step"] == 1
        assert data["totalSteps"] == 5
    
    def test_document_created_event_serialization(self):
        """DocumentCreatedEvent сериализуется корректно"""
        from app.services.chat.events import DocumentCreatedEvent, DocumentInfo
        
        doc = DocumentInfo(
            id="doc-123",
            title="Исковое заявление",
            case_id="case-456"
        )
        event = DocumentCreatedEvent(document=doc)
        sse = event.to_sse()
        
        json_str = sse.replace("data: ", "").strip()
        data = json.loads(json_str)
        
        assert data["type"] == "document_created"
        assert data["document"]["id"] == "doc-123"
        assert data["document"]["title"] == "Исковое заявление"
    
    def test_sse_serializer_shortcuts(self):
        """SSESerializer предоставляет удобные методы"""
        from app.services.chat.events import SSESerializer
        
        # text_delta
        sse = SSESerializer.text_delta("Привет")
        assert "textDelta" in sse
        
        # error
        sse = SSESerializer.error("Ошибка")
        assert "error" in sse
        
        # reasoning
        sse = SSESerializer.reasoning("phase", 1, 3, "content")
        assert "reasoning" in sse


# =============================================================================
# Тесты ChatHistoryService
# =============================================================================

class TestChatHistoryService:
    """Тесты для ChatHistoryService"""
    
    def test_get_or_create_session_creates_new(self, db_session, test_case):
        """Создаёт новую сессию если нет сообщений"""
        from app.services.chat.history_service import ChatHistoryService
        
        service = ChatHistoryService(db_session)
        session_id = service.get_or_create_session(test_case.id)
        
        assert session_id is not None
        assert len(session_id) == 36  # UUID format
    
    def test_save_user_message(self, db_session, test_case):
        """Сохраняет сообщение пользователя"""
        from app.services.chat.history_service import ChatHistoryService
        
        service = ChatHistoryService(db_session)
        message = service.save_user_message(
            case_id=test_case.id,
            content="Привет, какие документы в деле?"
        )
        
        assert message is not None
        assert message.role == "user"
        assert message.content == "Привет, какие документы в деле?"
        assert message.session_id is not None
    
    def test_get_history_for_context(self, db_session, test_case):
        """Получает историю в формате для LLM"""
        from app.services.chat.history_service import ChatHistoryService
        
        service = ChatHistoryService(db_session)
        
        # Сохраняем несколько сообщений
        msg1 = service.save_user_message(test_case.id, "Вопрос 1")
        service.save_assistant_message(
            test_case.id, "Ответ 1", msg1.session_id
        )
        
        # Получаем историю
        history = service.get_history_for_context(test_case.id, msg1.session_id)
        
        assert len(history) >= 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


# =============================================================================
# Тесты ChatOrchestrator (mock-based)
# =============================================================================

class TestChatOrchestrator:
    """Тесты для ChatOrchestrator"""
    
    @pytest.mark.asyncio
    async def test_process_request_verifies_case_access(self, db_session, test_user):
        """Проверяет доступ к делу"""
        from app.services.chat.orchestrator import ChatOrchestrator, ChatRequest
        
        orchestrator = ChatOrchestrator(db=db_session)
        
        request = ChatRequest(
            case_id="nonexistent-case",
            question="Привет",
            current_user=test_user
        )
        
        events = []
        async for event in orchestrator.process_request(request):
            events.append(event)
        
        # Должна быть ошибка "Дело не найдено"
        assert len(events) > 0
        assert "error" in events[0]
    
    @pytest.mark.asyncio
    async def test_classify_request_returns_result(self, db_session):
        """Классификация возвращает результат"""
        from app.services.chat.orchestrator import ChatOrchestrator
        from app.services.chat.classifier import ClassificationResult
        
        orchestrator = ChatOrchestrator(db=db_session)
        
        result = await orchestrator.classify_request("Пришли статью 135 ГПК")
        
        assert isinstance(result, ClassificationResult)
        assert result.label == "question"


# =============================================================================
# Тесты DI Container
# =============================================================================

class TestContainer:
    """Тесты для DI Container"""
    
    def test_get_instance_returns_singleton(self):
        """Container.get_instance() возвращает singleton"""
        from app.core.container import Container
        
        Container.reset()
        
        c1 = Container.get_instance()
        c2 = Container.get_instance()
        
        assert c1 is c2
    
    def test_override_dependency(self):
        """Можно переопределить зависимость"""
        from app.core.container import Container
        
        Container.reset()
        container = Container.get_instance()
        
        mock_rag = Mock()
        container.override("rag_service", mock_rag)
        
        assert container.rag_service is mock_rag
        
        container.clear_overrides()
    
    def test_create_classifier(self):
        """Создаёт RequestClassifier"""
        from app.core.container import Container
        from app.services.chat.classifier import RequestClassifier
        
        Container.reset()
        container = Container.get_instance()
        
        # Mock LLM чтобы не делать реальные вызовы
        container.override("llm", Mock())
        container.override("cache_manager", Mock())
        
        classifier = container.create_classifier()
        
        assert isinstance(classifier, RequestClassifier)
        
        container.clear_overrides()


# =============================================================================
# Тесты BaseAgent Protocol
# =============================================================================

class TestBaseAgent:
    """Тесты для BaseAgent"""
    
    @pytest.mark.asyncio
    async def test_execute_logs_timing(self):
        """execute() логирует время выполнения"""
        from app.services.langchain_agents.base_protocol import BaseAgent
        
        class TestAgent(BaseAgent):
            async def _execute(self, state):
                return {**state, "result": "done"}
        
        agent = TestAgent("test_agent", "Test description")
        
        result = await agent.execute({"input": "test"})
        
        assert result["result"] == "done"
        assert agent.status.value == "completed"
    
    @pytest.mark.asyncio
    async def test_execute_handles_errors(self):
        """execute() обрабатывает ошибки"""
        from app.services.langchain_agents.base_protocol import BaseAgent, AgentStatus
        
        class FailingAgent(BaseAgent):
            async def _execute(self, state):
                raise ValueError("Test error")
        
        agent = FailingAgent("failing_agent")
        
        result = await agent.execute({})
        
        assert agent.status == AgentStatus.FAILED
        assert "errors" in result
        assert any("Test error" in str(e) for e in result["errors"])
    
    @pytest.mark.asyncio
    async def test_stream_yields_events(self):
        """stream() генерирует события"""
        from app.services.langchain_agents.base_protocol import BaseAgent, AgentEvent
        
        class StreamAgent(BaseAgent):
            async def _execute(self, state):
                return {**state, "result": "done"}
        
        agent = StreamAgent("stream_agent")
        
        events = []
        async for event in agent.stream({}):
            events.append(event)
        
        assert len(events) >= 2  # start + complete (minimum)
        assert events[0].event_type == "start"
        assert events[-1].event_type == "complete"


# =============================================================================
# Тесты ParallelExecutor
# =============================================================================

class TestParallelExecutor:
    """Тесты для ParallelExecutor"""
    
    def test_create_parallel_sends(self):
        """Создаёт Send объекты для параллельного выполнения"""
        from app.services.langchain_agents.parallel_executor import create_parallel_sends
        
        state = {
            "case_id": "test-case",
            "analysis_types": ["timeline", "risk"]
        }
        
        sends = create_parallel_sends(
            state,
            ["timeline", "risk"],
            "execute_single_agent"
        )
        
        assert len(sends) == 2
    
    def test_create_parallel_sends_skips_completed(self):
        """Пропускает уже завершённые агенты"""
        from app.services.langchain_agents.parallel_executor import create_parallel_sends
        
        state = {
            "case_id": "test-case",
            "timeline_result": {"data": "already done"}
        }
        
        sends = create_parallel_sends(
            state,
            ["timeline", "risk"],
            "execute_single_agent"
        )
        
        assert len(sends) == 1  # Только risk
    
    def test_merge_parallel_results(self):
        """Сливает результаты параллельных выполнений"""
        from app.services.langchain_agents.parallel_executor import merge_parallel_results
        
        states = [
            {
                "current_agent": "timeline",
                "timeline_result": {"events": [1, 2, 3]},
                "errors": [],
                "completed_steps": ["timeline"]
            },
            {
                "current_agent": "risk",
                "risk_result": {"risks": ["A", "B"]},
                "errors": [],
                "completed_steps": ["risk"]
            }
        ]
        
        merged = merge_parallel_results(states)
        
        assert "timeline_result" in merged
        assert "risk_result" in merged
        assert "timeline" in merged["completed_steps"]
        assert "risk" in merged["completed_steps"]
    
    def test_parallel_agent_executor_prepare_sends(self):
        """ParallelAgentExecutor.prepare_sends() работает корректно"""
        from app.services.langchain_agents.parallel_executor import ParallelAgentExecutor
        
        registry = {
            "timeline": Mock(),
            "risk": Mock(),
            "summary": Mock()
        }
        
        executor = ParallelAgentExecutor(registry, max_parallel=2)
        
        state = {"case_id": "test"}
        sends = executor.prepare_sends(state, ["timeline", "risk", "summary"])
        
        # Должно быть ограничено до 2
        assert len(sends) <= 2


