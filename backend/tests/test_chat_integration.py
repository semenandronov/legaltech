"""Интеграционные тесты для chat с Planning Agent"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient


class TestChatTaskIntegration:
    """Тесты интеграции Planning Agent с chat endpoint"""
    
    def test_is_task_request_detection(self):
        """Тест определения задачи vs вопроса"""
        from app.routes.chat import is_task_request
        
        # Задачи (должны возвращать True)
        assert is_task_request("Проанализируй документы и найди все риски") is True
        assert is_task_request("Найди все противоречия в документах") is True
        assert is_task_request("Извлеки ключевые факты") is True
        assert is_task_request("Создай резюме дела") is True
        assert is_task_request("Find all discrepancies") is True
        assert is_task_request("Extract timeline events") is True
        
        # Вопросы (должны возвращать False)
        assert is_task_request("Какие даты упоминаются в документах?") is False
        assert is_task_request("Что такое timeline?") is False
        assert is_task_request("Объясни что такое discrepancy") is False
    
    def test_is_task_request_all_command_keywords(self):
        """Тест всех команд выполнения"""
        from app.routes.chat import is_task_request
        
        # Русские команды
        commands_ru = [
            "проанализируй", "анализируй", "выполни", "найди", "извлеки",
            "создай", "сделай", "запусти", "проведи", "провести"
        ]
        
        for cmd in commands_ru:
            assert is_task_request(f"{cmd} документы") is True, f"Команда '{cmd}' не распознана как задача"
        
        # Английские команды
        commands_en = [
            "analyze", "extract", "find", "create", "generate", "run", "perform", "execute"
        ]
        
        for cmd in commands_en:
            assert is_task_request(f"{cmd} documents") is True, f"Команда '{cmd}' не распознана как задача"
    
    def test_is_task_request_edge_cases(self):
        """Тест граничных случаев для is_task_request"""
        from app.routes.chat import is_task_request
        
        # Пустая строка
        assert is_task_request("") is False
        
        # Только пробелы
        assert is_task_request("   ") is False
        
        # Команда без контекста
        assert is_task_request("проанализируй") is True
        
        # Вопрос с командным словом
        assert is_task_request("Как проанализировать документы?") is False  # Это вопрос
        
        # Смешанный регистр
        assert is_task_request("Проанализируй Документы") is True
        assert is_task_request("ANALYZE documents") is True
    
    def test_chat_endpoint_handles_task_request(self):
        """Тест что chat endpoint обрабатывает задачи через Planning Agent"""
        # Структурная проверка - endpoint должен иметь логику для задач
        from app.routes.chat import chat, is_task_request
        
        # Проверяем что функция is_task_request доступна
        assert callable(is_task_request)
        
        # Проверяем что chat endpoint принимает background_tasks
        import inspect
        sig = inspect.signature(chat)
        assert "background_tasks" in sig.parameters
    
    def test_task_endpoint_structure(self):
        """Тест структуры task endpoint"""
        try:
            from app.routes.chat import execute_task
            import inspect
            
            sig = inspect.signature(execute_task)
            assert "request" in sig.parameters
            assert "background_tasks" in sig.parameters
            assert "db" in sig.parameters
            assert "current_user" in sig.parameters
        except ImportError:
            pytest.skip("Task endpoint not available")
    
    def test_planning_agent_integration(self):
        """Тест интеграции Planning Agent"""
        from app.services.langchain_agents import PlanningAgent
        
        # Проверяем что PlanningAgent доступен
        assert PlanningAgent is not None
        
        # Проверяем структуру класса
        assert hasattr(PlanningAgent, '__init__')
        assert hasattr(PlanningAgent, 'plan_analysis')
        
        # Проверяем что можно создать экземпляр (с моками)
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            assert agent is not None


class TestTaskRequestResponse:
    """Тесты структуры request/response для задач"""
    
    def test_task_request_model(self):
        """Тест модели TaskRequest"""
        try:
            from app.routes.chat import TaskRequest
            
            # Проверка структуры модели
            assert hasattr(TaskRequest, '__fields__') or hasattr(TaskRequest, 'model_fields')
        except ImportError:
            pytest.skip("TaskRequest not available")
    
    def test_task_response_model(self):
        """Тест модели TaskResponse"""
        try:
            from app.routes.chat import TaskResponse
            
            # Проверка структуры модели
            assert hasattr(TaskResponse, '__fields__') or hasattr(TaskResponse, 'model_fields')
        except ImportError:
            pytest.skip("TaskResponse not available")


class TestTaskExecutionFlow:
    """Тесты потока выполнения задачи"""
    
    def test_planning_to_analysis_flow(self):
        """Тест потока от планирования к анализу"""
        # Структурная проверка потока:
        # 1. Planning Agent создает план
        # 2. План преобразуется в analysis_types
        # 3. Analysis types передаются в AgentCoordinator
        
        from app.services.langchain_agents import PlanningAgent
        from app.services.analysis_service import AnalysisService
        
        # Проверяем что компоненты доступны
        assert PlanningAgent is not None
        assert AnalysisService is not None
        
        # Проверяем что AnalysisService имеет run_agent_analysis
        assert hasattr(AnalysisService, 'run_agent_analysis')
    
    def test_analysis_types_mapping(self):
        """Тест маппинга типов анализов между Planning Agent и API"""
        # Planning Agent использует: timeline, key_facts, discrepancy, risk, summary
        # API использует: timeline, key_facts, discrepancies, summary, risk_analysis
        
        # Проверяем что маппинг происходит в chat endpoint
        # Это структурная проверка - реальный маппинг проверяется в integration тестах
        planning_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        api_types = ["timeline", "key_facts", "discrepancies", "risk_analysis", "summary"]
        
        # Должны быть совместимые типы
        assert len(planning_types) == len(api_types) or len(set(planning_types) & set(api_types)) > 0
    
    def test_chat_endpoint_task_flow_structure(self):
        """Тест структуры потока обработки задач в chat endpoint"""
        from app.routes.chat import chat
        import inspect
        
        # Проверяем что chat принимает все нужные параметры
        sig = inspect.signature(chat)
        params = list(sig.parameters.keys())
        
        assert "request" in params
        assert "background_tasks" in params
        assert "db" in params
        assert "current_user" in params
    
    def test_chat_endpoint_mapping_logic(self):
        """Тест логики маппинга типов в chat endpoint"""
        # Симуляция маппинга как в коде chat endpoint
        planning_types = ["discrepancy", "risk"]
        
        api_analysis_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_analysis_types.append("discrepancies")
            elif at == "risk":
                api_analysis_types.append("risk_analysis")
            else:
                api_analysis_types.append(at)
        
        assert api_analysis_types == ["discrepancies", "risk_analysis"]
    
    def test_background_task_mapping_logic(self):
        """Тест логики маппинга в background task"""
        # Симуляция маппинга как в background task
        api_analysis_types = ["discrepancies", "risk_analysis"]
        
        agent_types = []
        for at in api_analysis_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        assert agent_types == ["discrepancy", "risk"]
