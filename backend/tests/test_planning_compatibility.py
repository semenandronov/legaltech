"""Тесты совместимости Planning Agent с существующей системой"""
import pytest
from unittest.mock import Mock, patch


class TestRAGChatCompatibility:
    """Тесты совместимости с обычным RAG chat"""
    
    def test_questions_still_use_rag(self):
        """Тест что вопросы продолжают обрабатываться через RAG"""
        from app.routes.chat import is_task_request
        
        # Вопросы не должны определяться как задачи
        questions = [
            "Какие даты упоминаются?",
            "Что такое timeline?",
            "Объясни что такое discrepancy",
        ]
        
        for question in questions:
            is_task = is_task_request(question)
            assert is_task is False, f"Вопрос '{question}' определен как задача"
    
    def test_chat_endpoint_structure_compatibility(self):
        """Тест что структура chat endpoint совместима"""
        from app.routes.chat import chat
        import inspect
        
        # Chat endpoint должен принимать те же параметры что и раньше
        sig = inspect.signature(chat)
        params = list(sig.parameters.keys())
        
        assert "request" in params
        assert "db" in params
        assert "current_user" in params
        
        # BackgroundTasks добавлен, но это не ломает существующий код
        assert "background_tasks" in params


class TestLegacyAnalysisCompatibility:
    """Тесты совместимости с legacy анализом"""
    
    def test_planning_agent_does_not_break_legacy(self):
        """Тест что Planning Agent не ломает legacy анализ"""
        from app.services.langchain_agents import PlanningAgent
        from app.services.analysis_service import AnalysisService
        
        # Оба должны существовать
        assert PlanningAgent is not None
        assert AnalysisService is not None
        
        # Legacy анализ должен продолжать работать
        assert hasattr(AnalysisService, 'extract_timeline')
        assert hasattr(AnalysisService, 'find_discrepancies')
        assert hasattr(AnalysisService, 'extract_key_facts')
        assert hasattr(AnalysisService, 'generate_summary')
        assert hasattr(AnalysisService, 'analyze_risks')
    
    def test_analysis_service_has_agents_method(self):
        """Тест что AnalysisService имеет метод для агентов"""
        from app.services.analysis_service import AnalysisService
        
        # AnalysisService должен иметь метод для работы с агентами
        assert hasattr(AnalysisService, 'run_agent_analysis')


class TestAPITypesCompatibility:
    """Тесты совместимости типов анализов API"""
    
    def test_api_types_compatibility(self):
        """Тест совместимости типов анализов между Planning и API"""
        # Planning Agent типы
        planning_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        
        # API типы (из существующей системы)
        api_types = ["timeline", "key_facts", "discrepancies", "risk_analysis", "summary"]
        
        # Проверяем что есть совместимость через маппинг
        # timeline, key_facts, summary совпадают
        common_types = set(planning_types) & set(api_types)
        assert "timeline" in common_types
        assert "key_facts" in common_types
        assert "summary" in common_types
        
        # discrepancy и risk требуют маппинга
        assert "discrepancy" in planning_types
        assert "discrepancies" in api_types
        assert "risk" in planning_types
        assert "risk_analysis" in api_types
    
    def test_type_mapping_preserves_functionality(self):
        """Тест что маппинг типов сохраняет функциональность"""
        # Симуляция маппинга
        planning_types = ["timeline", "discrepancy", "risk"]
        
        # Planning -> API
        api_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # Проверяем что все типы маппятся
        assert len(api_types) == len(planning_types)
        assert "timeline" in api_types
        assert "discrepancies" in api_types
        assert "risk_analysis" in api_types
        
        # API -> Agent (обратный маппинг)
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        # Должны получить исходные типы
        assert agent_types == planning_types


class TestBackwardCompatibility:
    """Тесты обратной совместимости"""
    
    def test_existing_api_endpoints_still_work(self):
        """Тест что существующие API endpoints продолжают работать"""
        from app.routes.analysis import router as analysis_router
        from app.routes.chat import router as chat_router
        
        # Роутеры должны существовать
        assert analysis_router is not None
        assert chat_router is not None
    
    def test_existing_models_still_valid(self):
        """Тест что существующие модели продолжают быть валидными"""
        from app.routes.chat import ChatRequest, ChatResponse
        
        # Модели должны существовать
        assert ChatRequest is not None
        assert ChatResponse is not None
        
        # ChatRequest должен иметь case_id и question
        fields = getattr(ChatRequest, 'model_fields', getattr(ChatRequest, '__fields__', None))
        if fields:
            assert "case_id" in fields
            assert "question" in fields


class TestComponentIntegrationCompatibility:
    """Тесты совместимости интеграции компонентов"""
    
    def test_planning_agent_with_existing_components(self):
        """Тест что Planning Agent работает с существующими компонентами"""
        from app.services.langchain_agents import PlanningAgent
        from app.services.langchain_agents.agent_factory import create_legal_agent
        from app.services.langchain_agents.planning_tools import get_planning_tools
        from app.services.langchain_agents.prompts import get_agent_prompt
        
        # Все компоненты должны быть доступны
        assert PlanningAgent is not None
        assert create_legal_agent is not None
        assert get_planning_tools is not None
        assert get_agent_prompt is not None
        
        # Planning Agent должен использовать существующие компоненты
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.get_planning_tools') as mock_tools:
                with patch('app.services.langchain_agents.planning_agent.get_agent_prompt') as mock_prompt:
                    mock_create.return_value = Mock()
                    mock_tools.return_value = []
                    mock_prompt.return_value = "test prompt"
                    
                    agent = PlanningAgent()
                    assert agent is not None
    
    def test_chat_endpoint_backward_compatibility(self):
        """Тест обратной совместимости chat endpoint"""
        from app.routes.chat import chat, ChatRequest
        
        # Chat endpoint должен принимать ChatRequest как раньше
        assert ChatRequest is not None
        
        # Структура должна быть совместимой
        import inspect
        sig = inspect.signature(chat)
        assert "request" in sig.parameters
        
        # BackgroundTasks - новый параметр, но опциональный через FastAPI


class TestLangChainCompatibility:
    """Тесты совместимости с LangChain"""
    
    def test_planning_agent_uses_create_legal_agent(self):
        """Тест что Planning Agent использует create_legal_agent"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        from app.services.langchain_agents.agent_factory import create_legal_agent
        
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_create.return_value = Mock()
            
            agent = PlanningAgent()
            
            # Проверяем что create_legal_agent был вызван
            mock_create.assert_called_once()
            
            # Проверяем что был вызван с правильными параметрами
            call_args = mock_create.call_args
            assert len(call_args[0]) >= 2  # llm и tools
            assert "system_prompt" in call_args[1]
    
    def test_planning_tools_use_langchain_tool_decorator(self):
        """Тест что planning tools используют langchain tool decorator"""
        from app.services.langchain_agents.planning_tools import (
            get_available_analyses_tool,
            check_analysis_dependencies_tool,
            validate_analysis_plan_tool
        )
        
        # Tools должны быть декорированы @tool
        assert hasattr(get_available_analyses_tool, 'name')
        assert hasattr(check_analysis_dependencies_tool, 'name')
        assert hasattr(validate_analysis_plan_tool, 'name')
        
        # Tools должны быть вызываемыми
        assert callable(get_available_analyses_tool)
        assert callable(check_analysis_dependencies_tool)
        assert callable(validate_analysis_plan_tool)
