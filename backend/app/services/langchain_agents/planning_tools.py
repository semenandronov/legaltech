"""Planning tools for Planning Agent"""
from typing import Dict, Any, List
from langchain.tools import tool
import json
import logging

logger = logging.getLogger(__name__)


# Определение доступных анализов и их зависимостей
AVAILABLE_ANALYSES = {
    "timeline": {
        "name": "timeline",
        "description": "Извлечение хронологии событий из документов (даты, события, временная линия)",
        "keywords": ["даты", "события", "хронология", "timeline", "timeline событий", "временная линия"],
        "dependencies": []
    },
    "key_facts": {
        "name": "key_facts",
        "description": "Извлечение ключевых фактов из документов (стороны, суммы, важные детали)",
        "keywords": ["факты", "ключевые факты", "key facts", "основные моменты", "важные детали"],
        "dependencies": []
    },
    "discrepancy": {
        "name": "discrepancy",
        "description": "Поиск противоречий и несоответствий между документами",
        "keywords": ["противоречия", "несоответствия", "discrepancy", "расхождения", "конфликты"],
        "dependencies": []
    },
    "risk": {
        "name": "risk",
        "description": "Анализ рисков на основе найденных противоречий",
        "keywords": ["риски", "risk", "анализ рисков", "оценка рисков", "риск-анализ"],
        "dependencies": ["discrepancy"]  # Требует discrepancy
    },
    "summary": {
        "name": "summary",
        "description": "Генерация резюме дела на основе ключевых фактов",
        "keywords": ["резюме", "summary", "краткое содержание", "сводка", "краткое резюме"],
        "dependencies": ["key_facts"]  # Требует key_facts
    }
}


@tool
def get_available_analyses_tool() -> str:
    """
    Возвращает список доступных типов анализов с описаниями и ключевыми словами.
    
    Используй этот инструмент для понимания, какие анализы доступны и что они делают.
    
    Returns:
        JSON строка с информацией о доступных анализах
    """
    try:
        analyses_info = {}
        for analysis_type, info in AVAILABLE_ANALYSES.items():
            analyses_info[analysis_type] = {
                "description": info["description"],
                "keywords": info["keywords"],
                "dependencies": info["dependencies"]
            }
        
        result = json.dumps(analyses_info, ensure_ascii=False, indent=2)
        logger.debug("get_available_analyses_tool: Returning available analyses")
        return result
    except Exception as e:
        logger.error(f"Error in get_available_analyses_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def check_analysis_dependencies_tool(analysis_type: str) -> str:
    """
    Проверяет зависимости для указанного типа анализа.
    
    Некоторые анализы требуют выполнения других анализов первыми.
    Например, risk требует discrepancy, summary требует key_facts.
    
    Args:
        analysis_type: Тип анализа для проверки (timeline, key_facts, discrepancy, risk, summary)
    
    Returns:
        JSON строка с информацией о зависимостях
    """
    try:
        analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
        if not analysis_info:
            return json.dumps({
                "analysis_type": analysis_type,
                "error": f"Unknown analysis type: {analysis_type}",
                "available_types": list(AVAILABLE_ANALYSES.keys())
            })
        
        dependencies = analysis_info["dependencies"]
        
        result = {
            "analysis_type": analysis_type,
            "dependencies": dependencies,
            "requires_dependencies": len(dependencies) > 0,
            "message": f"Analysis '{analysis_type}' requires: {', '.join(dependencies) if dependencies else 'none'}"
        }
        
        logger.debug(f"check_analysis_dependencies_tool: {analysis_type} -> {dependencies}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in check_analysis_dependencies_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def validate_analysis_plan_tool(analysis_types: str) -> str:
    """
    Валидирует план анализа и добавляет недостающие зависимости.
    
    Этот инструмент проверяет, что все необходимые зависимости включены в план.
    Если план включает анализ с зависимостями, они будут автоматически добавлены.
    
    Args:
        analysis_types: JSON строка или список типов анализов для валидации
    
    Returns:
        JSON строка с валидированным планом, включающим все зависимости
    """
    try:
        # Парсим входные данные
        if isinstance(analysis_types, str):
            try:
                types_list = json.loads(analysis_types)
            except json.JSONDecodeError:
                # Если не JSON, пытаемся разобрать как список строк через запятую
                types_list = [t.strip() for t in analysis_types.split(",")]
        else:
            types_list = analysis_types
        
        if not isinstance(types_list, list):
            return json.dumps({"error": "analysis_types must be a list"})
        
        # Валидируем и добавляем зависимости
        validated_types = []
        seen = set()
        
        def add_with_dependencies(analysis_type: str):
            """Рекурсивно добавляет анализ с его зависимостями"""
            if analysis_type in seen:
                return
            
            analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
            if not analysis_info:
                logger.warning(f"Unknown analysis type: {analysis_type}")
                return
            
            # Сначала добавляем зависимости
            for dep in analysis_info["dependencies"]:
                add_with_dependencies(dep)
            
            # Затем добавляем сам анализ
            validated_types.append(analysis_type)
            seen.add(analysis_type)
        
        # Добавляем все анализы с зависимостями
        for analysis_type in types_list:
            if isinstance(analysis_type, str):
                add_with_dependencies(analysis_type)
        
        result = {
            "original_types": types_list,
            "validated_types": validated_types,
            "added_dependencies": list(set(validated_types) - set(types_list)),
            "message": f"Validated plan: {validated_types}"
        }
        
        logger.debug(f"validate_analysis_plan_tool: {types_list} -> {validated_types}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in validate_analysis_plan_tool: {e}")
        return json.dumps({"error": str(e)})


def get_planning_tools() -> List:
    """Get all planning tools"""
    return [
        get_available_analyses_tool,
        check_analysis_dependencies_tool,
        validate_analysis_plan_tool,
    ]
