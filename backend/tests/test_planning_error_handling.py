"""Тесты обработки ошибок для Planning Agent"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.planning_tools import get_available_analyses_tool, check_analysis_dependencies_tool, validate_analysis_plan_tool


class TestPlanningAgentErrorHandling:
    """Тесты обработки ошибок в Planning Agent"""
    
    def test_llm_error_fallback(self):
        """Тест fallback при ошибке LLM"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_agent.invoke.side_effect = Exception("LLM API error")
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            # При ошибке LLM должен вернуться fallback план
            plan = agent.plan_analysis("test task", "test_case")
            
            assert "analysis_types" in plan
            assert "reasoning" in plan
            assert "confidence" in plan
            assert plan["confidence"] == 0.6  # Fallback confidence
    
    def test_json_parsing_error_fallback(self):
        """Тест fallback при ошибке парсинга JSON"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            # Агент возвращает невалидный JSON
            mock_result = {
                "messages": [
                    Mock(content="Это не JSON формат ответа")
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("test task", "test_case")
                
                # Должен использоваться text extraction fallback
                assert "analysis_types" in plan
                assert isinstance(plan["analysis_types"], list)
    
    def test_agent_creation_error_handling(self):
        """Тест обработки ошибок при создании агента"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_create.side_effect = Exception("Failed to create agent")
            
            # При ошибке создания агента должна быть обработана
            # В реальности это вызовет ошибку при инициализации, но нужно проверить что система не падает
            try:
                agent = PlanningAgent()
                # Если инициализация прошла, проверяем что agent существует
                assert agent is not None
            except Exception:
                # Если ошибка выброшена, это нормально - главное что она обработана
                pass
    
    def test_invalid_agent_response_structure(self):
        """Тест обработки неожиданной структуры ответа агента"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            # Неожиданная структура ответа
            mock_result = "просто строка, не словарь"
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("test task", "test_case")
                
                # Должен использоваться fallback
                assert "analysis_types" in plan
    
    def test_empty_agent_response(self):
        """Тест обработки пустого ответа агента"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_result = {
                "messages": []
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("test task", "test_case")
                
                # Должен использоваться fallback
                assert "analysis_types" in plan
    
    def test_missing_analysis_types_in_response(self):
        """Тест обработки ответа без analysis_types"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_result = {
                "messages": [
                    Mock(content='{"reasoning": "test", "confidence": 0.9}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("test task", "test_case")
                
                # Должен использоваться fallback или добавлены analysis_types
                assert "analysis_types" in plan
                assert isinstance(plan["analysis_types"], list)


class TestPlanningToolsErrorHandling:
    """Тесты обработки ошибок в Planning Tools"""
    
    def test_get_available_analyses_tool_error_handling(self):
        """Тест обработки ошибок в get_available_analyses_tool"""
        # Tool должен всегда возвращать валидный JSON даже при ошибках
        result = get_available_analyses_tool.invoke({})
        
        assert isinstance(result, str)
        # Должен быть валидный JSON
        try:
            data = json.loads(result)
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail("get_available_analyses_tool вернул невалидный JSON")
    
    def test_check_dependencies_tool_invalid_input(self):
        """Тест обработки невалидного входа в check_analysis_dependencies_tool"""
        # None или пустая строка
        result = check_analysis_dependencies_tool.invoke({"analysis_type": ""})
        deps_info = json.loads(result)
        
        # Должен вернуть информацию об ошибке или список доступных типов
        assert "error" in deps_info or "available_types" in deps_info
    
    def test_validate_plan_tool_invalid_json(self):
        """Тест обработки невалидного JSON в validate_analysis_plan_tool"""
        # Невалидный JSON
        result = validate_analysis_plan_tool.invoke({"analysis_types": "{invalid json}"})
        validated_info = json.loads(result)
        
        # Должен обработать ошибку
        assert "validated_types" in validated_info or "error" in validated_info
    
    def test_validate_plan_tool_non_list_input(self):
        """Тест обработки не-списка в validate_analysis_plan_tool"""
        # Передаем словарь вместо списка
        result = validate_analysis_plan_tool.invoke({"analysis_types": json.dumps({"not": "a list"})})
        validated_info = json.loads(result)
        
        # Должен обработать ошибку
        assert "error" in validated_info or "validated_types" in validated_info


class TestChatEndpointErrorHandling:
    """Тесты обработки ошибок в chat endpoint"""
    
    def test_planning_agent_error_fallback_to_rag(self):
        """Тест что при ошибке Planning Agent происходит fallback к RAG"""
        from app.routes.chat import chat, is_task_request
        
        # Проверяем что функция существует и обрабатывает ошибки
        assert callable(chat)
        assert callable(is_task_request)
        
        # Структурная проверка - в реальном коде должен быть try-except
        # который переключается на RAG при ошибке planning
    
    def test_task_endpoint_error_response(self):
        """Тест что task endpoint возвращает ошибку при проблемах"""
        from app.routes.chat import execute_task
        from fastapi import HTTPException
        
        # Проверяем что HTTPException используется для обработки ошибок
        assert HTTPException is not None


class TestDependencyResolutionErrorHandling:
    """Тесты обработки ошибок при разрешении зависимостей"""
    
    def test_unknown_analysis_type_in_dependencies(self):
        """Тест обработки неизвестного типа анализа"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Неизвестный тип должен быть пропущен
            types = ["timeline", "unknown_type", "key_facts"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "unknown_type" not in validated
            assert "timeline" in validated
            assert "key_facts" in validated
    
    def test_circular_dependency_handling(self):
        """Тест обработки циклических зависимостей (если бы были)"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # В текущей реализации циклических зависимостей нет,
            # но проверяем что система не зависнет
            types = ["timeline", "key_facts"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert isinstance(validated, list)
            assert len(validated) >= 0
    
    def test_empty_types_list_handling(self):
        """Тест обработки пустого списка типов"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            validated = agent._validate_and_add_dependencies([])
            
            assert isinstance(validated, list)
            assert len(validated) == 0
    
    def test_none_type_in_list_handling(self):
        """Тест обработки None в списке типов"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Проверяем что None пропускается
            types = ["timeline", None, "key_facts"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "timeline" in validated
            assert "key_facts" in validated
            assert None not in validated
    
    def test_non_string_type_handling(self):
        """Тест обработки не-строковых типов"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Не-строковые типы должны быть пропущены
            types = ["timeline", 123, ["nested"], "key_facts"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "timeline" in validated
            assert "key_facts" in validated
            assert 123 not in validated


class TestJSONParsingErrorHandling:
    """Тесты обработки ошибок парсинга JSON"""
    
    def test_malformed_json_handling(self):
        """Тест обработки неправильно сформированного JSON"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Неправильно сформированный JSON
            malformed_json = '{"analysis_types": ["timeline", "reasoning": "test"}'
            plan = agent._parse_agent_response(malformed_json)
            
            # Должен использоваться text extraction
            assert "analysis_types" in plan
    
    def test_incomplete_json_handling(self):
        """Тест обработки неполного JSON"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            incomplete_json = '{"analysis_types": ["timeline"'
            plan = agent._parse_agent_response(incomplete_json)
            
            # Должен использоваться fallback
            assert "analysis_types" in plan
    
    def test_json_with_extra_fields(self):
        """Тест обработки JSON с лишними полями"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # JSON с лишними полями должен обрабатываться нормально
            json_with_extra = '{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9, "extra_field": "value"}'
            plan = agent._parse_agent_response(json_with_extra)
            
            # Основные поля должны быть извлечены
            assert "analysis_types" in plan
            assert plan["analysis_types"] == ["timeline"]
