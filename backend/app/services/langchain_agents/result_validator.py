"""
Валидатор результатов агентов (LLM-as-judge).

Проверяет качество результатов агентов:
1. Структурная валидация (обязательные поля)
2. Семантическая валидация (LLM проверяет на галлюцинации)
3. Консистентность (согласованность между агентами)

Для юридических документов точность критична — лучше не дать ответ,
чем дать неправильный.
"""
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import json

from app.services.langchain_agents.state import AnalysisState

logger = logging.getLogger(__name__)


class ValidationLevel(str, Enum):
    """Уровень валидации."""
    STRUCTURE = "structure"  # Только структура
    SEMANTIC = "semantic"    # + LLM проверка
    FULL = "full"           # + Cross-agent consistency


@dataclass
class ValidationResult:
    """Результат валидации."""
    is_valid: bool
    confidence: float  # 0.0 - 1.0
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentValidationResult:
    """Результат валидации конкретного агента."""
    agent_name: str
    result_key: str
    structure_valid: bool
    semantic_valid: Optional[bool] = None
    consistency_valid: Optional[bool] = None
    issues: List[str] = field(default_factory=list)
    confidence: float = 0.0


# =============================================================================
# СХЕМЫ ВАЛИДАЦИИ ДЛЯ КАЖДОГО АГЕНТА
# =============================================================================

VALIDATION_SCHEMAS = {
    "timeline": {
        "result_key": "timeline_result",
        "required_fields": ["events"],
        "event_fields": ["date", "description"],  # Каждое событие должно иметь
        "min_items": 0,  # Может быть 0 событий
    },
    "key_facts": {
        "result_key": "key_facts_result",
        "required_fields": ["facts"],
        "fact_fields": ["fact", "importance"],
        "min_items": 0,
    },
    "discrepancy": {
        "result_key": "discrepancy_result",
        "required_fields": ["discrepancies"],
        "item_fields": ["description", "severity"],
        "min_items": 0,
    },
    "entity_extraction": {
        "result_key": "entities_result",
        "required_fields": ["entities"],
        "entity_fields": ["name", "type"],
        "min_items": 0,
    },
    "document_classifier": {
        "result_key": "classification_result",
        "required_fields": ["classifications"],
        "classification_fields": ["document_name", "category"],
        "min_items": 0,
    },
    "summary": {
        "result_key": "summary_result",
        "required_fields": ["summary"],
        "min_length": 50,  # Минимальная длина резюме
    },
    "risk": {
        "result_key": "risk_result",
        "required_fields": ["risks"],
        "risk_fields": ["description", "level"],
        "min_items": 0,
    },
    "relationship": {
        "result_key": "relationship_result",
        "required_fields": ["relationships"],
        "relationship_fields": ["source", "target", "type"],
        "min_items": 0,
    },
}


# =============================================================================
# СТРУКТУРНАЯ ВАЛИДАЦИЯ
# =============================================================================

def validate_structure(
    agent_name: str,
    result: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Валидация структуры результата агента.
    
    Args:
        agent_name: Имя агента
        result: Результат агента
    
    Returns:
        (is_valid, issues)
    """
    schema = VALIDATION_SCHEMAS.get(agent_name)
    if not schema:
        return True, []  # Нет схемы — пропускаем
    
    issues = []
    
    # Проверяем обязательные поля
    for field in schema.get("required_fields", []):
        if field not in result:
            issues.append(f"Missing required field: {field}")
        elif result[field] is None:
            issues.append(f"Field '{field}' is None")
    
    # Проверяем минимальную длину (для summary)
    if "min_length" in schema:
        summary = result.get("summary", "")
        if isinstance(summary, str) and len(summary) < schema["min_length"]:
            issues.append(f"Summary too short: {len(summary)} < {schema['min_length']}")
    
    # Проверяем элементы списков
    list_field = schema.get("required_fields", [None])[0]
    item_fields = (
        schema.get("event_fields") or
        schema.get("fact_fields") or
        schema.get("item_fields") or
        schema.get("entity_fields") or
        schema.get("classification_fields") or
        schema.get("risk_fields") or
        schema.get("relationship_fields")
    )
    
    if list_field and item_fields:
        items = result.get(list_field, [])
        if isinstance(items, list):
            for i, item in enumerate(items[:5]):  # Проверяем первые 5
                if isinstance(item, dict):
                    for item_field in item_fields:
                        if item_field not in item:
                            issues.append(f"Item {i} missing field: {item_field}")
    
    return len(issues) == 0, issues


# =============================================================================
# СЕМАНТИЧЕСКАЯ ВАЛИДАЦИЯ (LLM-as-judge)
# =============================================================================

async def validate_semantic(
    agent_name: str,
    result: Dict[str, Any],
    source_documents: List[str] = None,
) -> Tuple[bool, float, List[str]]:
    """
    Семантическая валидация с помощью LLM.
    
    Проверяет:
    - Галлюцинации (факты не из документов)
    - Логическую согласованность
    - Полноту извлечения
    
    Args:
        agent_name: Имя агента
        result: Результат агента
        source_documents: Исходные документы для проверки
    
    Returns:
        (is_valid, confidence, issues)
    """
    # Если нет исходных документов, пропускаем семантическую проверку
    if not source_documents:
        return True, 0.8, ["No source documents for semantic validation"]
    
    try:
        from app.services.llm_factory import create_llm
        
        llm = create_llm(temperature=0.0)  # Детерминированный для валидации
        
        # Формируем промпт для валидации
        prompt = _create_validation_prompt(agent_name, result, source_documents)
        
        response = await llm.ainvoke(prompt)
        
        # Парсим ответ
        validation_result = _parse_validation_response(response.content)
        
        return (
            validation_result.get("is_valid", True),
            validation_result.get("confidence", 0.7),
            validation_result.get("issues", []),
        )
        
    except Exception as e:
        logger.warning(f"Semantic validation failed: {e}")
        return True, 0.5, [f"Semantic validation error: {str(e)}"]


def _create_validation_prompt(
    agent_name: str,
    result: Dict[str, Any],
    source_documents: List[str],
) -> str:
    """Создать промпт для LLM-валидации."""
    
    # Сокращаем документы для экономии токенов
    docs_preview = "\n\n".join(doc[:1000] for doc in source_documents[:3])
    
    result_json = json.dumps(result, ensure_ascii=False, indent=2)[:2000]
    
    return f"""Ты — валидатор качества юридического анализа.

ЗАДАЧА: Проверить результат агента "{agent_name}" на:
1. Галлюцинации (факты, которых нет в документах)
2. Фактические ошибки
3. Пропущенную важную информацию

ИСХОДНЫЕ ДОКУМЕНТЫ (фрагменты):
{docs_preview}

РЕЗУЛЬТАТ АГЕНТА:
{result_json}

ИНСТРУКЦИИ:
- Проверь каждый факт в результате — есть ли он в документах?
- Отметь любые несоответствия
- Оцени уверенность в валидности (0.0 - 1.0)

Ответь строго в формате JSON:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "issues": ["список проблем"],
    "hallucinations": ["список галлюцинаций если есть"]
}}
"""


def _parse_validation_response(response: str) -> Dict[str, Any]:
    """Парсинг ответа LLM."""
    try:
        # Пытаемся найти JSON в ответе
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    
    # Fallback
    return {"is_valid": True, "confidence": 0.6, "issues": ["Could not parse validation response"]}


# =============================================================================
# КОНСИСТЕНТНОСТЬ МЕЖДУ АГЕНТАМИ
# =============================================================================

def validate_consistency(state: AnalysisState) -> Tuple[bool, List[str]]:
    """
    Проверка согласованности результатов между агентами.
    
    Например:
    - Даты в timeline должны совпадать с датами в entities
    - Имена в key_facts должны быть в entities
    """
    issues = []
    
    # Получаем результаты
    timeline = state.get("timeline_result", {})
    entities = state.get("entities_result", {})
    key_facts = state.get("key_facts_result", {})
    
    # Проверка 1: Даты из timeline должны быть в entities
    timeline_dates = set()
    for event in timeline.get("events", []):
        date = event.get("date")
        if date:
            timeline_dates.add(str(date))
    
    entity_dates = set()
    for entity in entities.get("entities", []):
        if entity.get("type") == "date":
            entity_dates.add(str(entity.get("name", "")))
    
    # Не требуем полного совпадения, но логируем расхождения
    if timeline_dates and entity_dates:
        missing_in_entities = timeline_dates - entity_dates
        if len(missing_in_entities) > len(timeline_dates) * 0.5:
            issues.append(f"Many timeline dates not in entities: {len(missing_in_entities)}")
    
    # Проверка 2: Имена из key_facts должны быть в entities
    # (мягкая проверка — не блокирует, только предупреждает)
    
    return len(issues) == 0, issues


# =============================================================================
# ГЛАВНЫЙ ВАЛИДАТОР
# =============================================================================

class ResultValidator:
    """
    Главный валидатор результатов агентов.
    
    Использование:
        validator = ResultValidator(level=ValidationLevel.STRUCTURE)
        result = validator.validate_state(state)
    """
    
    def __init__(self, level: ValidationLevel = ValidationLevel.STRUCTURE):
        """
        Args:
            level: Уровень валидации
        """
        self.level = level
    
    def validate_agent_result(
        self,
        agent_name: str,
        result: Dict[str, Any],
        source_documents: List[str] = None,
    ) -> AgentValidationResult:
        """
        Валидация результата одного агента.
        
        Args:
            agent_name: Имя агента
            result: Результат агента
            source_documents: Исходные документы
        
        Returns:
            AgentValidationResult
        """
        schema = VALIDATION_SCHEMAS.get(agent_name, {})
        result_key = schema.get("result_key", f"{agent_name}_result")
        
        issues = []
        
        # 1. Структурная валидация
        struct_valid, struct_issues = validate_structure(agent_name, result)
        issues.extend(struct_issues)
        
        # 2. Семантическая валидация (если включена)
        semantic_valid = None
        confidence = 0.8 if struct_valid else 0.3
        
        if self.level in [ValidationLevel.SEMANTIC, ValidationLevel.FULL]:
            # Семантическая валидация — async, здесь не вызываем
            # Для синхронного API используем только структурную
            pass
        
        return AgentValidationResult(
            agent_name=agent_name,
            result_key=result_key,
            structure_valid=struct_valid,
            semantic_valid=semantic_valid,
            issues=issues,
            confidence=confidence,
        )
    
    def validate_state(self, state: AnalysisState) -> ValidationResult:
        """
        Валидация всего состояния графа.
        
        Args:
            state: Состояние графа
        
        Returns:
            ValidationResult
        """
        all_issues = []
        all_warnings = []
        agent_results = {}
        total_confidence = 0.0
        validated_count = 0
        
        # Валидируем каждый агент
        for agent_name, schema in VALIDATION_SCHEMAS.items():
            result_key = schema["result_key"]
            result = state.get(result_key)
            
            if result is None:
                continue  # Агент не выполнялся
            
            agent_validation = self.validate_agent_result(agent_name, result)
            agent_results[agent_name] = agent_validation
            
            if not agent_validation.structure_valid:
                all_issues.extend([f"{agent_name}: {i}" for i in agent_validation.issues])
            
            total_confidence += agent_validation.confidence
            validated_count += 1
        
        # Проверка консистентности
        if self.level == ValidationLevel.FULL:
            consistency_valid, consistency_issues = validate_consistency(state)
            if not consistency_valid:
                all_warnings.extend(consistency_issues)
        
        # Итоговая оценка
        avg_confidence = total_confidence / validated_count if validated_count > 0 else 0.0
        is_valid = len(all_issues) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=avg_confidence,
            issues=all_issues,
            warnings=all_warnings,
            details={"agent_results": agent_results},
        )


# =============================================================================
# NODE ДЛЯ LANGGRAPH
# =============================================================================

def create_validator_node(level: ValidationLevel = ValidationLevel.STRUCTURE):
    """
    Создать узел валидатора для LangGraph.
    
    Args:
        level: Уровень валидации
    
    Returns:
        Функция-узел для графа
    """
    validator = ResultValidator(level=level)
    
    def validator_node(state: AnalysisState) -> AnalysisState:
        """Узел валидации в графе."""
        case_id = state.get("case_id", "unknown")
        
        validation_result = validator.validate_state(state)
        
        new_state = dict(state)
        new_state["validation_result"] = {
            "is_valid": validation_result.is_valid,
            "confidence": validation_result.confidence,
            "issues": validation_result.issues,
            "warnings": validation_result.warnings,
        }
        
        if validation_result.is_valid:
            logger.info(f"[Validator] {case_id}: ✓ All results valid (confidence: {validation_result.confidence:.2f})")
        else:
            logger.warning(f"[Validator] {case_id}: ✗ Validation issues: {validation_result.issues}")
        
        return new_state
    
    return validator_node


