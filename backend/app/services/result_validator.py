"""Result Validator for validating search results"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation"""
    is_valid: bool
    confidence: float
    issues: List[str]
    cross_check_score: Optional[float] = None
    relevance_score: Optional[float] = None


class ResultValidator:
    """
    Validates results from tools
    
    Performs:
    - Basic structure validation
    - Required fields check
    - Quality check
    - Cross-check with other results
    - Relevance check
    """
    
    def __init__(self):
        # Используем GigaChat для валидации релевантности
        self.llm = create_llm(temperature=0.1)
        logger.info("✅ ResultValidator initialized with GigaChat")
    
    def validate(
        self,
        result: Dict[str, Any],
        tool_name: str,
        expected_type: Optional[str] = None,
        cross_check_results: Optional[List[Dict]] = None
    ) -> ValidationResult:
        """
        Валидирует результат инструмента
        
        Args:
            result: Результат инструмента
            tool_name: Имя инструмента
            expected_type: Ожидаемый тип результата
            cross_check_results: Другие результаты для cross-check
        
        Returns:
            ValidationResult
        """
        issues = []
        
        # 1. Базовая проверка структуры
        if not isinstance(result, dict):
            issues.append("Result is not a dictionary")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                issues=issues
            )
        
        # 2. Проверка обязательных полей
        required_fields = ["content", "title", "url"]
        for field in required_fields:
            if field not in result or not result[field]:
                issues.append(f"Missing required field: {field}")
        
        # 3. Проверка качества
        if "content" in result:
            content = result["content"]
            if len(content) < 10:
                issues.append("Content too short")
            if len(content) > 100000:
                issues.append("Content too long")
        
        # 4. Cross-check с другими результатами
        cross_check_score = None
        if cross_check_results:
            cross_check_score = self._cross_check(result, cross_check_results)
            if cross_check_score < 0.3:
                issues.append("Low cross-check score with other results")
        
        # 5. Проверка релевантности (если есть query)
        relevance_score = None
        if "query" in result:
            relevance_score = self._check_relevance(result["query"], [result])
            if relevance_score < 0.5:
                issues.append("Low relevance score")
        
        is_valid = len(issues) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=1.0 - (len(issues) * 0.2),  # Простая эвристика
            issues=issues,
            cross_check_score=cross_check_score,
            relevance_score=relevance_score
        )
    
    def _cross_check(
        self,
        result: Dict[str, Any],
        other_results: List[Dict[str, Any]]
    ) -> float:
        """
        Cross-check результата с другими результатами
        
        Args:
            result: Результат для проверки
            other_results: Другие результаты
        
        Returns:
            Score от 0 до 1
        """
        if not other_results:
            return 1.0
        
        # Простая эвристика: проверяем совпадение URL и похожесть контента
        result_url = result.get("url", "")
        result_content = result.get("content", "")[:200]  # Первые 200 символов
        
        matches = 0
        for other in other_results:
            other_url = other.get("url", "")
            other_content = other.get("content", "")[:200]
            
            # Проверка URL
            if result_url and other_url and result_url == other_url:
                matches += 1
                continue
            
            # Проверка похожести контента (простая эвристика)
            if result_content and other_content:
                # Подсчитываем общие слова
                result_words = set(result_content.lower().split())
                other_words = set(other_content.lower().split())
                common_words = result_words & other_words
                
                if len(common_words) > 5:  # Порог совпадения
                    matches += 0.5
        
        return min(matches / len(other_results), 1.0) if other_results else 0.0
    
    def _check_relevance(
        self,
        query: str,
        results: List[Dict]
    ) -> float:
        """
        Проверяет релевантность результатов запросу
        
        Args:
            query: Поисковый запрос
            results: Список результатов
        
        Returns:
            Relevance score от 0 до 1
        """
        if not results:
            return 0.0
        
        # Простая эвристика: проверяем наличие ключевых слов запроса в результатах
        query_words = set(query.lower().split())
        
        relevant_count = 0
        for result in results:
            content = result.get("content", "").lower()
            title = result.get("title", "").lower()
            
            # Подсчитываем совпадения ключевых слов
            content_words = set(content.split())
            title_words = set(title.split())
            
            matches = len(query_words & (content_words | title_words))
            if matches >= len(query_words) * 0.3:  # Порог релевантности
                relevant_count += 1
        
        return relevant_count / len(results) if results else 0.0
    
    def mark_as_verified(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Помечает результат как проверенный
        
        Args:
            result: Результат
        
        Returns:
            Результат с меткой verified
        """
        result["verified"] = True
        result["verified_at"] = datetime.now().isoformat()
        return result

