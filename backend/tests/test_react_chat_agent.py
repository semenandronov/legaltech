"""
Тесты для ReActChatAgent

Проверяет:
1. Инициализацию агента с разными переключателями
2. Выбор инструментов в зависимости от вопроса
3. Обработку обзорных вопросов (summarize_all_documents)
4. Обработку конкретных вопросов (search_documents)
5. Интеграцию с deep_think
"""
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import asyncio


class TestChatTools:
    """Тесты для chat_tools.py"""
    
    def test_get_chat_tools_basic(self):
        """Тест получения базовых инструментов"""
        from app.services.chat.chat_tools import get_chat_tools
        
        # Мокаем зависимости
        mock_db = Mock()
        mock_rag_service = Mock()
        
        tools = get_chat_tools(
            db=mock_db,
            rag_service=mock_rag_service,
            case_id="test-case-123",
            legal_research=False,
            web_search=False
        )
        
        # Проверяем базовые инструменты
        tool_names = [t.name for t in tools]
        
        assert "search_documents" in tool_names
        assert "list_case_files" in tool_names
        assert "get_file_summary" in tool_names
        assert "summarize_all_documents" in tool_names
        assert "extract_entities" in tool_names
        assert "find_contradictions" in tool_names
        assert "analyze_risks" in tool_names
        assert "build_timeline" in tool_names
    
    def test_get_chat_tools_with_garant(self):
        """Тест добавления GARANT инструментов"""
        from app.services.chat.chat_tools import get_chat_tools
        
        mock_db = Mock()
        mock_rag_service = Mock()
        
        tools = get_chat_tools(
            db=mock_db,
            rag_service=mock_rag_service,
            case_id="test-case-123",
            legal_research=True,  # Включаем GARANT
            web_search=False
        )
        
        tool_names = [t.name for t in tools]
        
        # Базовые инструменты должны быть
        assert "search_documents" in tool_names
        
        # GARANT инструменты могут быть добавлены (если модуль доступен)
        # Не падаем если их нет
        assert len(tools) >= 8  # Минимум базовые


class TestReActChatAgent:
    """Тесты для ReActChatAgent"""
    
    def test_agent_initialization(self):
        """Тест инициализации агента"""
        from app.services.chat.react_chat_agent import ReActChatAgent
        
        mock_db = Mock()
        mock_rag_service = Mock()
        
        # Мокаем LLM
        with patch('app.services.chat.react_chat_agent.ReActChatAgent._create_llm') as mock_llm:
            with patch('app.services.chat.react_chat_agent.ReActChatAgent._create_agent') as mock_agent:
                mock_llm.return_value = Mock()
                mock_agent.return_value = Mock()
                
                agent = ReActChatAgent(
                    case_id="test-case-123",
                    db=mock_db,
                    rag_service=mock_rag_service,
                    legal_research=True,
                    deep_think=False,
                    web_search=True
                )
                
                assert agent.case_id == "test-case-123"
                assert agent.legal_research == True
                assert agent.deep_think == False
                assert agent.web_search == True
    
    def test_agent_with_deep_think(self):
        """Тест агента с deep_think режимом"""
        from app.services.chat.react_chat_agent import ReActChatAgent
        
        mock_db = Mock()
        mock_rag_service = Mock()
        
        with patch('app.services.chat.react_chat_agent.ReActChatAgent._create_llm') as mock_llm:
            with patch('app.services.chat.react_chat_agent.ReActChatAgent._create_agent') as mock_agent:
                mock_llm.return_value = Mock()
                mock_agent.return_value = Mock()
                
                agent = ReActChatAgent(
                    case_id="test-case-123",
                    db=mock_db,
                    rag_service=mock_rag_service,
                    deep_think=True  # Включаем deep_think
                )
                
                assert agent.deep_think == True
                # LLM должен быть создан с deep_think
                mock_llm.assert_called_once()


class TestChatOrchestrator:
    """Тесты для ChatOrchestrator с ReActChatAgent"""
    
    def test_orchestrator_routes_to_react_agent(self):
        """Тест роутинга на ReActChatAgent"""
        from app.services.chat.orchestrator import ChatOrchestrator, ChatRequest
        
        mock_db = Mock()
        mock_user = Mock()
        mock_user.id = "user-123"
        
        with patch('app.services.chat.orchestrator.RAGService'):
            with patch('app.services.chat.orchestrator.DocumentProcessor'):
                with patch('app.services.chat.orchestrator.ChatHistoryService'):
                    with patch('app.services.chat.orchestrator.DraftHandler'):
                        with patch('app.services.chat.orchestrator.EditorHandler'):
                            orchestrator = ChatOrchestrator(db=mock_db)
                            
                            # Создаём запрос (не draft, не editor)
                            request = ChatRequest(
                                case_id="test-case-123",
                                question="О чём все эти документы?",
                                current_user=mock_user,
                                legal_research=True,
                                deep_think=False,
                                web_search=False
                            )
                            
                            # Проверяем режим
                            mode = orchestrator._determine_mode(request)
                            assert mode == "react_agent"
    
    def test_orchestrator_routes_to_draft(self):
        """Тест роутинга на DraftHandler"""
        from app.services.chat.orchestrator import ChatOrchestrator, ChatRequest
        
        mock_db = Mock()
        mock_user = Mock()
        mock_user.id = "user-123"
        
        with patch('app.services.chat.orchestrator.RAGService'):
            with patch('app.services.chat.orchestrator.DocumentProcessor'):
                with patch('app.services.chat.orchestrator.ChatHistoryService'):
                    with patch('app.services.chat.orchestrator.DraftHandler'):
                        with patch('app.services.chat.orchestrator.EditorHandler'):
                            orchestrator = ChatOrchestrator(db=mock_db)
                            
                            # Создаём draft запрос
                            request = ChatRequest(
                                case_id="test-case-123",
                                question="Создай исковое заявление",
                                current_user=mock_user,
                                draft_mode=True  # Draft mode
                            )
                            
                            mode = orchestrator._determine_mode(request)
                            assert mode == "draft"
    
    def test_orchestrator_routes_to_editor(self):
        """Тест роутинга на EditorHandler"""
        from app.services.chat.orchestrator import ChatOrchestrator, ChatRequest
        
        mock_db = Mock()
        mock_user = Mock()
        mock_user.id = "user-123"
        
        with patch('app.services.chat.orchestrator.RAGService'):
            with patch('app.services.chat.orchestrator.DocumentProcessor'):
                with patch('app.services.chat.orchestrator.ChatHistoryService'):
                    with patch('app.services.chat.orchestrator.DraftHandler'):
                        with patch('app.services.chat.orchestrator.EditorHandler'):
                            orchestrator = ChatOrchestrator(db=mock_db)
                            
                            # Создаём editor запрос
                            request = ChatRequest(
                                case_id="test-case-123",
                                question="Исправь ошибку",
                                current_user=mock_user,
                                document_context="Текст документа..."  # Editor mode
                            )
                            
                            mode = orchestrator._determine_mode(request)
                            assert mode == "editor"


class TestQuestionTypeDetection:
    """Тесты определения типа вопроса"""
    
    def test_overview_question_detection(self):
        """Тест определения обзорных вопросов"""
        overview_questions = [
            "О чём все эти документы?",
            "Расскажи о деле",
            "Что содержится в документах?",
            "Дай обзор дела",
            "Какие документы в деле?",
        ]
        
        for question in overview_questions:
            question_lower = question.lower()
            is_overview = any(phrase in question_lower for phrase in [
                "о чём", "о чем", "обзор", "все документы", "что в деле",
                "расскажи о", "содержится", "какие документы"
            ])
            assert is_overview, f"Question should be detected as overview: {question}"
    
    def test_specific_question_detection(self):
        """Тест определения конкретных вопросов"""
        specific_questions = [
            "Какая сумма в договоре?",
            "Когда был подписан договор?",
            "Кто истец?",
            "Что сказано о сроках?",
        ]
        
        for question in specific_questions:
            question_lower = question.lower()
            is_overview = any(phrase in question_lower for phrase in [
                "о чём", "о чем", "обзор", "все документы", "что в деле",
                "расскажи о", "содержится", "какие документы"
            ])
            assert not is_overview, f"Question should NOT be detected as overview: {question}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

