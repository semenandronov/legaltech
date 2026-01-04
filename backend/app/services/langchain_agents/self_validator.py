"""Self-Validator Service - Phase 2.2 Implementation

This module provides LLM-as-judge validation for agent outputs
and self-correction mechanisms.

Features:
- LLM-based validation of agent outputs
- Schema compliance checking
- Error and contradiction detection
- Self-correction loop
- Pattern storage for learning from errors
"""
from typing import Dict, Any, Optional, List, Tuple, Type
from pydantic import BaseModel, ValidationError
from app.config import config
import logging
import json

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result of validation check."""
    
    is_valid: bool = True
    confidence: float = 1.0  # 0-1
    
    # Issues found
    errors: List[str] = []
    warnings: List[str] = []
    suggestions: List[str] = []
    
    # Specific issues
    schema_violations: List[str] = []
    factual_issues: List[str] = []
    logical_inconsistencies: List[str] = []
    missing_elements: List[str] = []
    
    # Corrected output (if correction was applied)
    corrected_output: Optional[Dict[str, Any]] = None
    corrections_made: List[str] = []
    
    class Config:
        extra = "allow"


class SelfValidator:
    """
    LLM-as-judge validator for agent outputs.
    
    Validates outputs against schemas, checks for errors and
    inconsistencies, and can apply self-correction.
    """
    
    def __init__(self, llm=None):
        """
        Initialize the self-validator.
        
        Args:
            llm: Optional LLM instance for validation
        """
        self._llm = llm
        self._error_patterns: Dict[str, List[Dict[str, Any]]] = {}
    
    def _get_llm(self):
        """Get or create LLM instance."""
        if self._llm is None:
            try:
                from app.services.llm_factory import create_llm
                self._llm = create_llm(temperature=0.0)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM for validation: {e}")
        return self._llm
    
    def validate_schema(
        self,
        output: Dict[str, Any],
        schema_class: Type[BaseModel]
    ) -> ValidationResult:
        """
        Validate output against a Pydantic schema.
        
        Args:
            output: The output to validate
            schema_class: The Pydantic model class
            
        Returns:
            ValidationResult with schema validation results
        """
        result = ValidationResult()
        
        try:
            # Try to parse with schema
            parsed = schema_class(**output)
            result.is_valid = True
            result.confidence = 1.0
            
        except ValidationError as e:
            result.is_valid = False
            result.confidence = 0.0
            
            for error in e.errors():
                field = ".".join(str(loc) for loc in error.get("loc", []))
                msg = error.get("msg", "Validation error")
                result.schema_violations.append(f"{field}: {msg}")
                result.errors.append(f"Schema violation in {field}: {msg}")
        
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Unexpected validation error: {str(e)}")
        
        return result
    
    def validate_with_llm(
        self,
        output: Dict[str, Any],
        agent_name: str,
        context: Optional[str] = None,
        expected_format: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate output using LLM-as-judge.
        
        Args:
            output: The output to validate
            agent_name: Name of the agent that produced output
            context: Optional context for validation
            expected_format: Expected output format description
            
        Returns:
            ValidationResult with LLM validation results
        """
        result = ValidationResult()
        
        llm = self._get_llm()
        if not llm:
            result.warnings.append("LLM not available for validation")
            return result
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            # Build validation prompt
            output_str = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
            
            prompt = f"""Ты эксперт по проверке качества результатов анализа юридических документов.

Проверь следующий результат работы агента "{agent_name}":

```json
{output_str}
```

{f'Контекст: {context}' if context else ''}
{f'Ожидаемый формат: {expected_format}' if expected_format else ''}

Проверь:
1. Полноту ответа (все ли необходимые поля заполнены)
2. Логическую согласованность (нет ли противоречий)
3. Корректность (соответствуют ли данные контексту)
4. Точность ссылок на источники

Ответь в формате JSON:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "errors": ["критические ошибки"],
    "warnings": ["предупреждения"],
    "suggestions": ["предложения по улучшению"],
    "factual_issues": ["фактические проблемы"],
    "missing_elements": ["отсутствующие элементы"]
}}"""
            
            response = llm.invoke([
                SystemMessage(content="Ты проверяешь качество аналитических результатов. Отвечай только JSON."),
                HumanMessage(content=prompt)
            ])
            
            # Parse response
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                validation_data = json.loads(json_match.group())
                
                result.is_valid = validation_data.get("is_valid", True)
                result.confidence = validation_data.get("confidence", 0.8)
                result.errors = validation_data.get("errors", [])
                result.warnings = validation_data.get("warnings", [])
                result.suggestions = validation_data.get("suggestions", [])
                result.factual_issues = validation_data.get("factual_issues", [])
                result.missing_elements = validation_data.get("missing_elements", [])
            else:
                result.warnings.append("Could not parse LLM validation response")
                
        except Exception as e:
            logger.error(f"LLM validation error: {e}")
            result.warnings.append(f"LLM validation failed: {str(e)}")
        
        return result
    
    def correct_output(
        self,
        output: Dict[str, Any],
        validation_result: ValidationResult,
        agent_name: str,
        schema_class: Optional[Type[BaseModel]] = None
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Attempt to correct an invalid output.
        
        Args:
            output: The original output
            validation_result: Validation result with issues
            agent_name: Name of the agent
            schema_class: Optional schema for structure
            
        Returns:
            Tuple of (corrected_output, corrections_made)
        """
        corrections = []
        corrected = output.copy()
        
        llm = self._get_llm()
        if not llm:
            return corrected, ["LLM not available for correction"]
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            # Build correction prompt
            issues = []
            if validation_result.errors:
                issues.extend([f"Error: {e}" for e in validation_result.errors])
            if validation_result.schema_violations:
                issues.extend([f"Schema: {s}" for s in validation_result.schema_violations])
            if validation_result.factual_issues:
                issues.extend([f"Factual: {f}" for f in validation_result.factual_issues])
            
            issues_str = "\n".join(issues[:10])  # Limit issues
            output_str = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
            
            prompt = f"""Исправь следующий результат работы агента "{agent_name}".

Исходный результат:
```json
{output_str}
```

Обнаруженные проблемы:
{issues_str}

Исправь проблемы и верни исправленный JSON.
Верни ТОЛЬКО исправленный JSON, без пояснений."""
            
            response = llm.invoke([
                SystemMessage(content="Ты исправляешь ошибки в аналитических результатах."),
                HumanMessage(content=prompt)
            ])
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                corrected = json.loads(json_match.group())
                corrections.append(f"LLM corrected {len(issues)} issues")
                
                # Validate corrected output if schema provided
                if schema_class:
                    try:
                        schema_class(**corrected)
                        corrections.append("Corrected output passes schema validation")
                    except ValidationError as e:
                        corrections.append(f"Corrected output still has schema issues: {len(e.errors())}")
            else:
                corrections.append("Could not extract corrected JSON")
                
        except Exception as e:
            logger.error(f"Correction error: {e}")
            corrections.append(f"Correction failed: {str(e)}")
        
        return corrected, corrections
    
    def validate_and_correct(
        self,
        output: Dict[str, Any],
        agent_name: str,
        schema_class: Optional[Type[BaseModel]] = None,
        context: Optional[str] = None,
        max_correction_attempts: int = 2
    ) -> Tuple[Dict[str, Any], ValidationResult]:
        """
        Full validation and correction loop.
        
        Args:
            output: The output to validate
            agent_name: Name of the agent
            schema_class: Optional schema class
            context: Optional context for validation
            max_correction_attempts: Maximum correction attempts
            
        Returns:
            Tuple of (final_output, final_validation_result)
        """
        current_output = output
        
        for attempt in range(max_correction_attempts + 1):
            # Validate schema if provided
            if schema_class:
                schema_result = self.validate_schema(current_output, schema_class)
                if not schema_result.is_valid:
                    if attempt < max_correction_attempts:
                        current_output, corrections = self.correct_output(
                            current_output,
                            schema_result,
                            agent_name,
                            schema_class
                        )
                        schema_result.corrections_made.extend(corrections)
                        continue
                    return current_output, schema_result
            
            # LLM validation
            llm_result = self.validate_with_llm(
                current_output,
                agent_name,
                context
            )
            
            # Merge results
            if schema_class:
                llm_result.schema_violations = schema_result.schema_violations
            
            # If valid or no more attempts, return
            if llm_result.is_valid or attempt >= max_correction_attempts:
                return current_output, llm_result
            
            # Attempt correction
            current_output, corrections = self.correct_output(
                current_output,
                llm_result,
                agent_name,
                schema_class
            )
            llm_result.corrections_made.extend(corrections)
        
        return current_output, llm_result
    
    def record_error_pattern(
        self,
        agent_name: str,
        error_type: str,
        context: Dict[str, Any],
        resolution: Optional[str] = None
    ):
        """
        Record an error pattern for learning.
        
        Args:
            agent_name: Name of the agent
            error_type: Type of error
            context: Context when error occurred
            resolution: How the error was resolved
        """
        if agent_name not in self._error_patterns:
            self._error_patterns[agent_name] = []
        
        pattern = {
            "error_type": error_type,
            "context": context,
            "resolution": resolution,
            "count": 1
        }
        
        # Check if pattern already exists
        for existing in self._error_patterns[agent_name]:
            if existing["error_type"] == error_type:
                existing["count"] += 1
                if resolution:
                    existing["resolution"] = resolution
                return
        
        self._error_patterns[agent_name].append(pattern)
        logger.debug(f"Recorded error pattern for {agent_name}: {error_type}")
    
    def get_error_patterns(self, agent_name: str) -> List[Dict[str, Any]]:
        """Get recorded error patterns for an agent."""
        return self._error_patterns.get(agent_name, [])


# Global validator instance
_validator: Optional[SelfValidator] = None


def get_self_validator() -> SelfValidator:
    """Get or create the global self-validator instance."""
    global _validator
    
    if _validator is None:
        _validator = SelfValidator()
    
    return _validator

