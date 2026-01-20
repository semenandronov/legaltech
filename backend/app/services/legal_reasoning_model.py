"""Legal Reasoning Model for determining when and what to search"""
from enum import Enum
from typing import Optional, Dict, Any
from app.services.llm_factory import create_llm
import logging
import re

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of legal tasks"""
    FIND_NORM = "find_norm"
    FIND_PRECEDENT = "find_precedent"
    FIND_COURT_POSITION = "find_court_position"
    ANALYSIS = "analysis"


class SourceType(Enum):
    """Types of legal sources"""
    PRAVO = "pravo.gov.ru"
    VS = "vsrf.ru"
    KAD = "kad.arbitr.ru"
    UNKNOWN = "unknown"


class LegalReasoningModel:
    """
    Model for legal reasoning and decision-making about search
    
    Determines:
    - What type of task (find norm, precedent, court position)
    - Whether search is needed
    - Which source to use
    - How to formulate the query
    """
    
    def __init__(self):
        # Используем GigaChat для классификации задач
        self.llm = create_llm(temperature=0.1)
        logger.info("✅ LegalReasoningModel initialized with GigaChat")
    
    def identify_task_type(self, prompt: str, context: Optional[Dict] = None) -> TaskType:
        """
        Определяет тип задачи через эвристику (можно улучшить через GigaChat)
        
        Args:
            prompt: Текст запроса или анализа
            context: Дополнительный контекст
        
        Returns:
            TaskType
        """
        # Простая эвристика для быстрой классификации
        prompt_lower = prompt.lower()
        
        # Проверка на норму права
        if any(keyword in prompt_lower for keyword in ["статья", "гк рф", "норма", "кодекс", "закон"]):
            return TaskType.FIND_NORM
        
        # Проверка на позицию ВС
        if any(keyword in prompt_lower for keyword in [
            "разъяснения", "постановление вс", "позиция верховного суда",
            "пленум вс", "разъяснения верховного суда"
        ]):
            return TaskType.FIND_COURT_POSITION
        
        # Проверка на прецеденты
        if any(keyword in prompt_lower for keyword in [
            "решения по", "аналогичные дела", "прецедент", "судебная практика",
            "как суды решают", "практика судов"
        ]):
            return TaskType.FIND_PRECEDENT
        
        # Можно использовать GigaChat для более точной классификации
        # Для MVP используем эвристику
        return TaskType.ANALYSIS
    
    def should_search(self, analysis_text: str) -> bool:
        """
        Определяет, нужен ли поиск через анализ текста
        
        Args:
            analysis_text: Текст анализа агента
        
        Returns:
            True если нужен поиск
        """
        # Маркеры пробелов в знаниях
        markers = [
            "неясн", "нет нормы", "нужен прецедент", "нехватает",
            "требуется уточнение", "недостаточно информации",
            "необходимо проверить", "следует найти", "нужна норма",
            "требуется норма", "нужны разъяснения", "нужна позиция"
        ]
        analysis_lower = analysis_text.lower()
        return any(m in analysis_lower for m in markers)
    
    def determine_source_type(self, task: TaskType) -> SourceType:
        """
        Определяет тип источника на основе задачи
        
        Args:
            task: Тип задачи
        
        Returns:
            SourceType
        """
        if task == TaskType.FIND_NORM:
            return SourceType.PRAVO
        if task == TaskType.FIND_COURT_POSITION:
            return SourceType.VS
        if task == TaskType.FIND_PRECEDENT:
            return SourceType.KAD
        return SourceType.UNKNOWN
    
    def formulate_query(self, task: TaskType, facts: str, context: Optional[Dict] = None) -> str:
        """
        Формирует поисковый запрос на основе задачи и фактов
        
        Args:
            task: Тип задачи
            facts: Факты из дела
            context: Дополнительный контекст
        
        Returns:
            Оптимизированный поисковый запрос
        """
        # Базовые шаблоны
        if task == TaskType.FIND_NORM:
            # Извлекаем номер статьи если есть
            article_match = re.search(r'статья\s+(\d+)\s+ГК', facts, re.IGNORECASE)
            if article_match:
                return f"статья {article_match.group(1)} ГК РФ"
            
            # Пробуем найти другие упоминания статей
            article_match = re.search(r'ст\.\s*(\d+)', facts, re.IGNORECASE)
            if article_match:
                return f"статья {article_match.group(1)} ГК РФ"
            
            return f"статья ГК РФ {facts[:100]}".strip()
        
        if task == TaskType.FIND_COURT_POSITION:
            # Извлекаем ключевые слова из фактов
            keywords = facts[:150].strip()
            return f"разъяснения Верховного Суда РФ {keywords}".strip()
        
        if task == TaskType.FIND_PRECEDENT:
            # Извлекаем ключевые слова для поиска прецедентов
            keywords = facts[:150].strip()
            return f"решение арбитражного суда {keywords}".strip()
        
        return facts[:200].strip()














































