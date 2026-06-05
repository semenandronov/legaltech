"""
Интеграционные тесты для полного workflow редактора.

Проверяет:
- Полный workflow редактора
- SSE события
- Формат structured_edits
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.chat.editor_handler import EditorHandler
from app.services.langchain_agents.chat_graph_service import ChatGraphService


class TestEditorWorkflow:
    """Тесты для полного workflow редактора"""
    
    @pytest.mark.asyncio
    async def test_editor_handler_uses_chat_graph_service(self):
        """Проверка что EditorHandler использует ChatGraphService"""
        handler = EditorHandler(rag_service=Mock(), db=Mock())
        
        # Проверяем что handle вызывает ChatGraphService
        async def empty_stream(*args, **kwargs):
            if False:
                yield ""

        mock_chat = MagicMock()
        mock_chat.stream_response = MagicMock(return_value=empty_stream())

        with patch('app.services.langchain_agents.chat_graph_service.get_chat_graph_service') as mock_service:
            mock_service.return_value = mock_chat

            async for _ in handler.handle(
                case_id="test",
                question="Тест",
                current_user=Mock(),
                document_id="doc1",
                document_context="Документ",
                selected_text=None
            ):
                pass

            mock_chat.stream_response.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_structured_edits_in_sse_events(self):
        """Проверка что structured_edits приходят в SSE событиях"""
        handler = EditorHandler(rag_service=Mock(), db=Mock())
        
        # Мокируем ChatGraphService для возврата structured_edits
        mock_events = [
            'data: {"type": "text-delta", "textDelta": "Ответ"}\n\n',
            'data: {"structured_edits": [{"id": "edit-1", "original_text": "текст", "new_text": "новый"}]}\n\n'
        ]
        
        async def events_stream(*args, **kwargs):
            for event in mock_events:
                yield event

        mock_chat = MagicMock()
        mock_chat.stream_response = MagicMock(return_value=events_stream())

        with patch('app.services.langchain_agents.chat_graph_service.get_chat_graph_service') as mock_service:
            mock_service.return_value = mock_chat
            
            events = []
            async for event in handler.handle(
                case_id="test",
                question="Замени текст",
                current_user=Mock(),
                document_id="doc1",
                document_context="текст",
                selected_text=None
            ):
                events.append(event)
            
            # Проверяем что structured_edits присутствуют в событиях
            assert any("structured_edits" in event for event in events)
    
    def test_editor_mode_detection(self):
        """Проверка определения editor mode"""
        from app.services.langchain_agents.graphs.chat_graph import route_by_mode
        
        state_with_doc = {
            "mode": "normal",
            "document_context": "Документ"
        }
        
        result = route_by_mode(state_with_doc)
        
        # Проверяем что editor_mode определяется правильно
        assert result == "editor_mode"
    
    def test_editor_routing(self):
        """Проверка маршрутизации редактора"""
        from app.services.langchain_agents.graphs.chat_graph import route_editor_mode
        
        state_risks = {
            "question": "Проверь риски"
        }
        
        result = route_editor_mode(state_risks)
        
        # Проверяем что запрос на проверку рисков маршрутизируется правильно
        assert result == "check_risks"

    def test_editor_mode_hint_edit(self):
        from app.services.langchain_agents.graphs.chat_graph import route_editor_mode

        assert route_editor_mode({
            "editor_mode_hint": "edit",
            "question": "улучши формулировку",
        }) == "generate_edits"

    def test_editor_mode_hint_draft(self):
        from app.services.langchain_agents.graphs.chat_graph import route_editor_mode

        assert route_editor_mode({
            "editor_mode_hint": "draft",
            "question": "добавь пункт о форс-мажоре",
        }) == "generate_editor_snippet"

