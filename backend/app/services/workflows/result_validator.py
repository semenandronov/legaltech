"""Result Validator - валидация результатов Workflow"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging
import json
import re

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A validation issue"""
    severity: str  # error, warning, info
    message: str
    step_id: Optional[str] = None
    field: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validation"""
    is_valid: bool
    confidence_score: float  # 0.0 - 1.0
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: str = ""


VALIDATION_PROMPT = """Проверь результаты выполнения workflow.

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:
{user_task}

РЕЗУЛЬТАТЫ ВЫПОЛНЕНИЯ:
{results}

ЗАДАЧА:
1. Проверь, соответствуют ли результаты поставленной задаче
2. Оцени качество и полноту результатов
3. Выяви потенциальные проблемы или пропуски

Верни результат в формате JSON:
{{
    "is_valid": true/false,
    "confidence_score": 0.0-1.0,
    "issues": [
        {{
            "severity": "error|warning|info",
            "message": "описание проблемы",
            "step_id": "id шага (если применимо)",
            "suggestion": "рекомендация по исправлению"
        }}
    ],
    "summary": "общий вывод о качестве результатов"
}}"""


class ResultValidator:
    """
    Валидатор результатов Workflow.
    
    Проверяет:
    - Соответствие результатов задаче
    - Полноту выполнения
    - Качество данных
    - Уверенность в результатах
    """
    
    def __init__(self):
        """Initialize validator"""
        self.llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            self.llm = create_llm(temperature=0.1)
            logger.info("ResultValidator: LLM initialized")
        except Exception as e:
            logger.warning(f"ResultValidator: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def validate(
        self,
        user_task: str,
        results: Dict[str, Any],
        expected_schema: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate workflow results
        
        Args:
            user_task: Original user task
            results: Workflow results
            expected_schema: Optional JSON Schema for results
            
        Returns:
            ValidationResult
        """
        issues = []
        
        # Basic validation
        basic_issues = self._basic_validation(results)
        issues.extend(basic_issues)
        
        # Schema validation
        if expected_schema:
            schema_issues = self._validate_schema(results, expected_schema)
            issues.extend(schema_issues)
        
        # LLM validation for quality
        if self.llm:
            llm_result = await self._llm_validation(user_task, results)
            issues.extend(llm_result.issues)
            
            return ValidationResult(
                is_valid=llm_result.is_valid and not any(i.severity == "error" for i in issues),
                confidence_score=llm_result.confidence_score,
                issues=issues,
                summary=llm_result.summary
            )
        
        # Fallback without LLM
        has_errors = any(i.severity == "error" for i in issues)
        
        return ValidationResult(
            is_valid=not has_errors,
            confidence_score=0.7 if not has_errors else 0.3,
            issues=issues,
            summary="Базовая валидация пройдена" if not has_errors else "Обнаружены ошибки"
        )
    
    def _basic_validation(self, results: Dict[str, Any]) -> List[ValidationIssue]:
        """Perform basic validation checks"""
        issues = []
        
        if not results:
            issues.append(ValidationIssue(
                severity="error",
                message="Результаты отсутствуют"
            ))
            return issues
        
        # Check for step results
        steps = results.get("steps", {})
        if not steps:
            issues.append(ValidationIssue(
                severity="warning",
                message="Нет результатов по отдельным шагам"
            ))
        
        # Check for failed steps
        for step_id, step_data in steps.items():
            if not step_data.get("success", True):
                issues.append(ValidationIssue(
                    severity="warning",
                    message=f"Шаг завершился с ошибкой",
                    step_id=step_id
                ))
        
        return issues
    
    def _validate_schema(
        self,
        results: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate results against JSON Schema"""
        issues = []
        
        try:
            import jsonschema
            jsonschema.validate(results, schema)
        except ImportError:
            logger.warning("jsonschema not installed, skipping schema validation")
        except jsonschema.ValidationError as e:
            issues.append(ValidationIssue(
                severity="error",
                message=f"Schema validation error: {e.message}",
                field=str(e.path)
            ))
        
        return issues
    
    async def _llm_validation(
        self,
        user_task: str,
        results: Dict[str, Any]
    ) -> ValidationResult:
        """Validate using LLM"""
        try:
            # Prepare results for LLM
            results_str = json.dumps(results, ensure_ascii=False, indent=2)
            
            # Truncate if too long
            if len(results_str) > 15000:
                results_str = results_str[:15000] + "\n...[обрезано]..."
            
            prompt = ChatPromptTemplate.from_template(VALIDATION_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({
                "user_task": user_task,
                "results": results_str
            })
            
            # Parse response
            return self._parse_validation_response(response.content)
            
        except Exception as e:
            logger.error(f"LLM validation error: {e}")
            return ValidationResult(
                is_valid=True,
                confidence_score=0.5,
                issues=[ValidationIssue(
                    severity="warning",
                    message=f"LLM validation failed: {str(e)}"
                )],
                summary="LLM validation skipped due to error"
            )
    
    def _parse_validation_response(self, response: str) -> ValidationResult:
        """Parse LLM validation response"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                raise ValueError("No JSON in response")
            
            data = json.loads(json_match.group())
            
            issues = []
            for issue_data in data.get("issues", []):
                issues.append(ValidationIssue(
                    severity=issue_data.get("severity", "info"),
                    message=issue_data.get("message", ""),
                    step_id=issue_data.get("step_id"),
                    suggestion=issue_data.get("suggestion")
                ))
            
            return ValidationResult(
                is_valid=data.get("is_valid", True),
                confidence_score=data.get("confidence_score", 0.7),
                issues=issues,
                summary=data.get("summary", "")
            )
            
        except Exception as e:
            logger.error(f"Failed to parse validation response: {e}")
            return ValidationResult(
                is_valid=True,
                confidence_score=0.5,
                summary="Failed to parse validation response"
            )
    
    def calculate_confidence(
        self,
        step_results: Dict[str, Any]
    ) -> float:
        """
        Calculate overall confidence score
        
        Args:
            step_results: Results from all steps
            
        Returns:
            Confidence score 0.0 - 1.0
        """
        if not step_results:
            return 0.0
        
        total_steps = len(step_results)
        successful_steps = sum(
            1 for r in step_results.values()
            if r.get("success", False)
        )
        
        # Base confidence from success rate
        success_rate = successful_steps / total_steps if total_steps > 0 else 0
        
        # Adjust based on individual step confidence scores
        step_confidences = []
        for step_data in step_results.values():
            if isinstance(step_data, dict) and "confidence" in step_data:
                step_confidences.append(step_data["confidence"])
        
        if step_confidences:
            avg_step_confidence = sum(step_confidences) / len(step_confidences)
            # Weighted average: 60% success rate, 40% step confidence
            return 0.6 * success_rate + 0.4 * avg_step_confidence
        
        return success_rate
    
    def get_validation_summary(self, result: ValidationResult) -> str:
        """
        Get human-readable validation summary
        
        Args:
            result: Validation result
            
        Returns:
            Summary string
        """
        lines = [
            f"Валидация: {'✓ Пройдена' if result.is_valid else '✗ Не пройдена'}",
            f"Уверенность: {result.confidence_score:.0%}",
        ]
        
        if result.issues:
            errors = [i for i in result.issues if i.severity == "error"]
            warnings = [i for i in result.issues if i.severity == "warning"]
            
            if errors:
                lines.append(f"Ошибок: {len(errors)}")
            if warnings:
                lines.append(f"Предупреждений: {len(warnings)}")
        
        if result.summary:
            lines.append(f"\n{result.summary}")
        
        return "\n".join(lines)

