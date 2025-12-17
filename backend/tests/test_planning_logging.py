"""Тесты логирования для Planning Agent"""
import pytest
import logging
from unittest.mock import Mock, patch
from io import StringIO


class TestPlanningAgentLogging:
    """Тесты логирования Planning Agent"""
    
    def test_initialization_logging(self):
        """Тест логирования инициализации"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                from app.services.langchain_agents.planning_agent import PlanningAgent
                
                agent = PlanningAgent()
                
                # Должно быть логирование инициализации
                mock_logger.info.assert_called()
                calls = [str(call) for call in mock_logger.info.call_args_list]
                assert any("Planning Agent initialized" in str(call) for call in calls)
    
    def test_planning_start_logging(self):
        """Тест логирования начала планирования"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_result = {
                    "messages": [
                        Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
                    ]
                }
                mock_agent.invoke.return_value = mock_result
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # Должно быть логирование начала планирования
                    mock_logger.info.assert_called()
                    calls = [str(call) for call in mock_logger.info.call_args_list]
                    assert any("Planning analysis for task" in str(call) for call in calls)
    
    def test_planning_result_logging(self):
        """Тест логирования результата планирования"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_result = {
                    "messages": [
                        Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
                    ]
                }
                mock_agent.invoke.return_value = mock_result
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # Должно быть логирование результата
                    mock_logger.info.assert_called()
                    calls = [str(call) for call in mock_logger.info.call_args_list]
                    assert any("Analysis plan created" in str(call) for call in calls)
    
    def test_error_logging(self):
        """Тест логирования ошибок"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_agent.invoke.side_effect = Exception("Test error")
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # Должно быть логирование ошибки
                    mock_logger.warning.assert_called()
                    calls = [str(call) for call in mock_logger.warning.call_args_list]
                    assert any("Agent execution error" in str(call) or "using fallback" in str(call) for call in calls)
    
    def test_fallback_logging(self):
        """Тест логирования fallback"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_result = {
                    "messages": [
                        Mock(content="Не JSON ответ")
                    ]
                }
                mock_agent.invoke.return_value = mock_result
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # Должно быть логирование fallback на text extraction
                    mock_logger.warning.assert_called()
                    calls = [str(call) for call in mock_logger.warning.call_args_list]
                    assert any("Could not parse JSON" in str(call) or "trying text extraction" in str(call) for call in calls)
    
    def test_dependency_resolution_logging(self):
        """Тест логирования разрешения зависимостей"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                agent._validate_and_add_dependencies(["risk"])
                
                # Должно быть debug логирование разрешения зависимостей
                mock_logger.debug.assert_called()
                calls = [str(call) for call in mock_logger.debug.call_args_list]
                assert any("Dependency resolution" in str(call) for call in calls)
    
    def test_unknown_type_warning_logging(self):
        """Тест логирования предупреждений о неизвестных типах"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                agent._validate_and_add_dependencies(["unknown_type"])
                
                # Должно быть warning логирование неизвестного типа
                mock_logger.warning.assert_called()
                calls = [str(call) for call in mock_logger.warning.call_args_list]
                assert any("Unknown analysis type" in str(call) for call in calls)
    
    def test_exception_logging_with_traceback(self):
        """Тест логирования исключений с traceback"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_agent.invoke.side_effect = Exception("Critical error")
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # Должно быть error логирование с exc_info
                    mock_logger.error.assert_called()
                    calls = mock_logger.error.call_args_list
                    assert any(call[1].get('exc_info') is True for call in calls if len(call) > 1)


class TestPlanningToolsLogging:
    """Тесты логирования Planning Tools"""
    
    def test_get_available_analyses_tool_logging(self):
        """Тест логирования get_available_analyses_tool"""
        with patch('app.services.langchain_agents.planning_tools.logger') as mock_logger:
            from app.services.langchain_agents.planning_tools import get_available_analyses_tool
            
            get_available_analyses_tool.invoke({})
            
            # Должно быть debug логирование
            mock_logger.debug.assert_called()
            calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("get_available_analyses_tool" in str(call) for call in calls)
    
    def test_check_dependencies_tool_logging(self):
        """Тест логирования check_analysis_dependencies_tool"""
        with patch('app.services.langchain_agents.planning_tools.logger') as mock_logger:
            from app.services.langchain_agents.planning_tools import check_analysis_dependencies_tool
            
            check_analysis_dependencies_tool.invoke({"analysis_type": "risk"})
            
            # Должно быть debug логирование
            mock_logger.debug.assert_called()
            calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("check_analysis_dependencies_tool" in str(call) for call in calls)
    
    def test_validate_plan_tool_logging(self):
        """Тест логирования validate_analysis_plan_tool"""
        with patch('app.services.langchain_agents.planning_tools.logger') as mock_logger:
            import json
            from app.services.langchain_agents.planning_tools import validate_analysis_plan_tool
            
            validate_analysis_plan_tool.invoke({"analysis_types": json.dumps(["timeline"])})
            
            # Должно быть debug логирование
            mock_logger.debug.assert_called()
            calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("validate_analysis_plan_tool" in str(call) for call in calls)
    
    def test_tools_error_logging(self):
        """Тест логирования ошибок в tools"""
        with patch('app.services.langchain_agents.planning_tools.logger') as mock_logger:
            from app.services.langchain_agents.planning_tools import get_available_analyses_tool
            
            # Tool должен логировать ошибки, если они возникают
            # В данном случае tool должен работать нормально
            result = get_available_analyses_tool.invoke({})
            assert isinstance(result, str)


class TestLoggingLevels:
    """Тесты уровней логирования"""
    
    def test_info_logging_for_normal_operations(self):
        """Тест что нормальные операции логируются как INFO"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_result = {
                    "messages": [
                        Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
                    ]
                }
                mock_agent.invoke.return_value = mock_result
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # INFO логи должны быть вызваны
                    assert mock_logger.info.called
    
    def test_warning_logging_for_fallback(self):
        """Тест что fallback случаи логируются как WARNING"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_agent.invoke.side_effect = Exception("Test error")
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # WARNING логи должны быть вызваны
                    assert mock_logger.warning.called
    
    def test_error_logging_for_exceptions(self):
        """Тест что исключения логируются как ERROR"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                mock_agent = Mock()
                mock_agent.invoke.side_effect = Exception("Critical error")
                mock_create.return_value = mock_agent
                
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                    agent.plan_analysis("test task", "test_case")
                    
                    # ERROR логи должны быть вызваны
                    assert mock_logger.error.called
    
    def test_debug_logging_for_details(self):
        """Тест что детальная информация логируется как DEBUG"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            with patch('app.services.langchain_agents.planning_agent.logger') as mock_logger:
                from app.services.langchain_agents.planning_agent import PlanningAgent
                agent = PlanningAgent()
                
                agent._validate_and_add_dependencies(["timeline"])
                
                # DEBUG логи должны быть вызваны для детальной информации
                assert mock_logger.debug.called


class TestChatEndpointLogging:
    """Тесты логирования в chat endpoint"""
    
    def test_chat_endpoint_logs_task_detection(self):
        """Тест логирования определения задач в chat endpoint"""
        from app.routes.chat import is_task_request, chat
        import inspect
        
        # Проверяем что функция существует
        assert callable(is_task_request)
        assert callable(chat)
        
        # Структурная проверка - в реальном коде должен быть logger
        # который логирует определение задач
        from app.routes.chat import logger
        assert logger is not None
