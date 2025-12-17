"""Тесты для planning tools"""
import pytest
import json
from app.services.langchain_agents.planning_tools import (
    get_available_analyses_tool,
    check_analysis_dependencies_tool,
    validate_analysis_plan_tool,
    get_planning_tools,
    AVAILABLE_ANALYSES
)


class TestPlanningTools:
    """Тесты для planning tools"""
    
    def test_get_available_analyses_tool(self):
        """Тест получения списка доступных анализов"""
        result = get_available_analyses_tool.invoke({})
        
        # Результат должен быть JSON строкой
        assert isinstance(result, str)
        
        # Парсим JSON
        analyses_info = json.loads(result)
        
        # Проверяем наличие всех анализов
        assert "timeline" in analyses_info
        assert "key_facts" in analyses_info
        assert "discrepancy" in analyses_info
        assert "risk" in analyses_info
        assert "summary" in analyses_info
        
        # Проверяем структуру информации
        for analysis_type, info in analyses_info.items():
            assert "description" in info
            assert "keywords" in info
            assert "dependencies" in info
    
    def test_check_analysis_dependencies_tool_independent(self):
        """Тест проверки зависимостей для независимых анализов"""
        # Timeline не имеет зависимостей
        result = check_analysis_dependencies_tool.invoke({"analysis_type": "timeline"})
        deps_info = json.loads(result)
        
        assert deps_info["analysis_type"] == "timeline"
        assert deps_info["dependencies"] == []
        assert deps_info["requires_dependencies"] is False
    
    def test_check_analysis_dependencies_tool_dependent(self):
        """Тест проверки зависимостей для зависимых анализов"""
        # Risk требует discrepancy
        result = check_analysis_dependencies_tool.invoke({"analysis_type": "risk"})
        deps_info = json.loads(result)
        
        assert deps_info["analysis_type"] == "risk"
        assert "discrepancy" in deps_info["dependencies"]
        assert deps_info["requires_dependencies"] is True
        
        # Summary требует key_facts
        result = check_analysis_dependencies_tool.invoke({"analysis_type": "summary"})
        deps_info = json.loads(result)
        
        assert deps_info["analysis_type"] == "summary"
        assert "key_facts" in deps_info["dependencies"]
        assert deps_info["requires_dependencies"] is True
    
    def test_check_analysis_dependencies_tool_unknown(self):
        """Тест проверки зависимостей для неизвестного типа анализа"""
        result = check_analysis_dependencies_tool.invoke({"analysis_type": "unknown_type"})
        deps_info = json.loads(result)
        
        assert "error" in deps_info
        assert "available_types" in deps_info
    
    def test_validate_analysis_plan_tool_simple(self):
        """Тест валидации простого плана"""
        # Простой план без зависимостей
        plan_json = json.dumps(["timeline", "key_facts"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        assert "original_types" in validated_info
        assert "validated_types" in validated_info
        assert len(validated_info["validated_types"]) >= 2
        assert "timeline" in validated_info["validated_types"]
        assert "key_facts" in validated_info["validated_types"]
    
    def test_validate_analysis_plan_tool_with_dependencies(self):
        """Тест валидации плана с зависимостями"""
        # План с risk - должна добавиться dependency discrepancy
        plan_json = json.dumps(["risk"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        assert "discrepancy" in validated_info["validated_types"]
        assert "risk" in validated_info["validated_types"]
        assert validated_info["validated_types"].index("discrepancy") < validated_info["validated_types"].index("risk")
        
        # План с summary - должна добавиться dependency key_facts
        plan_json = json.dumps(["summary"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        assert "key_facts" in validated_info["validated_types"]
        assert "summary" in validated_info["validated_types"]
        assert validated_info["validated_types"].index("key_facts") < validated_info["validated_types"].index("summary")
    
    def test_validate_analysis_plan_tool_complex(self):
        """Тест валидации сложного плана"""
        # План с несколькими анализами, включая зависимые
        plan_json = json.dumps(["timeline", "risk", "summary"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        validated_types = validated_info["validated_types"]
        
        # Должны быть все запрошенные анализы
        assert "timeline" in validated_types
        assert "risk" in validated_types
        assert "summary" in validated_types
        
        # Должны быть добавлены зависимости
        assert "discrepancy" in validated_types  # для risk
        assert "key_facts" in validated_types  # для summary
    
    def test_validate_analysis_plan_tool_string_input(self):
        """Тест валидации с строковым входом (не JSON)"""
        # Попытка передать строку с запятыми
        result = validate_analysis_plan_tool.invoke({"analysis_types": "timeline,key_facts"})
        validated_info = json.loads(result)
        
        assert "validated_types" in validated_info
        assert len(validated_info["validated_types"]) >= 2
    
    def test_get_planning_tools(self):
        """Тест получения всех planning tools"""
        tools = get_planning_tools()
        
        assert isinstance(tools, list)
        assert len(tools) >= 3
        
        tool_names = [tool.name for tool in tools]
        assert "get_available_analyses_tool" in tool_names
        assert "check_analysis_dependencies_tool" in tool_names
        assert "validate_analysis_plan_tool" in tool_names
    
    def test_get_available_analyses_tool_structure(self):
        """Тест детальной структуры ответа get_available_analyses_tool"""
        result = get_available_analyses_tool.invoke({})
        analyses_info = json.loads(result)
        
        # Проверяем что все поля присутствуют
        for analysis_type, info in analyses_info.items():
            assert isinstance(info["description"], str)
            assert isinstance(info["keywords"], list)
            assert len(info["keywords"]) > 0
            assert isinstance(info["dependencies"], list)
    
    def test_check_analysis_dependencies_all_types(self):
        """Тест проверки зависимостей для всех типов анализов"""
        all_types = list(AVAILABLE_ANALYSES.keys())
        
        for analysis_type in all_types:
            result = check_analysis_dependencies_tool.invoke({"analysis_type": analysis_type})
            deps_info = json.loads(result)
            
            assert deps_info["analysis_type"] == analysis_type
            assert "dependencies" in deps_info
            assert "requires_dependencies" in deps_info
            assert isinstance(deps_info["dependencies"], list)
            
            # Проверяем соответствие реальным зависимостям
            expected_deps = AVAILABLE_ANALYSES[analysis_type]["dependencies"]
            assert set(deps_info["dependencies"]) == set(expected_deps)
    
    def test_validate_analysis_plan_tool_empty_list(self):
        """Тест валидации пустого списка"""
        plan_json = json.dumps([])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        assert "validated_types" in validated_info
        assert isinstance(validated_info["validated_types"], list)
        # Пустой список должен вернуть пустой список
        assert len(validated_info["validated_types"]) == 0
    
    def test_validate_analysis_plan_tool_invalid_json(self):
        """Тест валидации с невалидным JSON"""
        # Невалидный JSON должен обрабатываться как строка
        result = validate_analysis_plan_tool.invoke({"analysis_types": "not a json"})
        validated_info = json.loads(result)
        
        # Должен обработать как строку через запятую
        assert "validated_types" in validated_info or "error" in validated_info
    
    def test_validate_analysis_plan_tool_unknown_type(self):
        """Тест валидации с неизвестным типом анализа"""
        plan_json = json.dumps(["unknown_analysis_type"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        # Неизвестный тип должен быть пропущен
        assert "validated_types" in validated_info
        # unknown_analysis_type не должен быть в validated_types
        assert "unknown_analysis_type" not in validated_info["validated_types"]
    
    def test_validate_analysis_plan_tool_duplicates(self):
        """Тест валидации с дубликатами"""
        plan_json = json.dumps(["timeline", "timeline", "key_facts"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        validated_types = validated_info["validated_types"]
        # Дубликаты должны быть удалены
        assert validated_types.count("timeline") == 1
        assert "key_facts" in validated_types
    
    def test_validate_analysis_plan_tool_preserves_order(self):
        """Тест что порядок анализов сохраняется после валидации"""
        plan_json = json.dumps(["timeline", "key_facts", "discrepancy"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        validated_types = validated_info["validated_types"]
        # Независимые анализы должны сохранить порядок
        assert validated_types.index("timeline") < validated_types.index("key_facts")
        assert validated_types.index("key_facts") < validated_types.index("discrepancy")
    
    def test_validate_analysis_plan_tool_dependency_order(self):
        """Тест правильного порядка зависимостей"""
        # Risk должен идти после discrepancy
        plan_json = json.dumps(["risk"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        validated_types = validated_info["validated_types"]
        dep_idx = validated_types.index("discrepancy")
        risk_idx = validated_types.index("risk")
        assert dep_idx < risk_idx
        
        # Summary должен идти после key_facts
        plan_json = json.dumps(["summary"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        validated_info = json.loads(result)
        
        validated_types = validated_info["validated_types"]
        key_facts_idx = validated_types.index("key_facts")
        summary_idx = validated_types.index("summary")
        assert key_facts_idx < summary_idx
    
    def test_validate_analysis_plan_tool_list_input(self):
        """Тест валидации с прямым списком (не JSON строка)"""
        # Если передать список напрямую
        result = validate_analysis_plan_tool.invoke({"analysis_types": ["timeline", "key_facts"]})
        validated_info = json.loads(result)
        
        assert "validated_types" in validated_info
        assert "timeline" in validated_info["validated_types"]
        assert "key_facts" in validated_info["validated_types"]
    
    def test_check_analysis_dependencies_tool_error_handling(self):
        """Тест обработки ошибок в check_analysis_dependencies_tool"""
        # Пустая строка
        result = check_analysis_dependencies_tool.invoke({"analysis_type": ""})
        deps_info = json.loads(result)
        assert "error" in deps_info or "available_types" in deps_info
        
        # None не должен обрабатываться напрямую, но проверим что функция не падает
        # (в реальности FastAPI/Pydantic валидирует вход)
    
    def test_get_available_analyses_tool_error_handling(self):
        """Тест что get_available_analyses_tool обрабатывает ошибки"""
        # Tool должен всегда возвращать валидный JSON
        result = get_available_analyses_tool.invoke({})
        assert isinstance(result, str)
        
        # Должен быть валидный JSON
        try:
            analyses_info = json.loads(result)
            assert isinstance(analyses_info, dict)
        except json.JSONDecodeError:
            pytest.fail("get_available_analyses_tool вернул невалидный JSON")
