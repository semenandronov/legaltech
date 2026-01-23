"""Agent Self-Awareness Service for identifying knowledge gaps"""
from enum import Enum
from typing import List, Dict, Any, Optional
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
import logging

logger = logging.getLogger(__name__)


class GapType(Enum):
    """Types of knowledge gaps"""
    MISSING_NORM = "MISSING_NORM"
    MISSING_PRECEDENT = "MISSING_PRECEDENT"
    MISSING_COURT_POSITION = "MISSING_COURT_POSITION"
    UNCLEAR_INTERPRETATION = "UNCLEAR_INTERPRETATION"


class SelfAwarenessService:
    """
    Service for agent self-awareness
    
    Identifies knowledge gaps in agent's understanding and generates
    search strategies to fill those gaps.
    """
    
    def __init__(self):
        # Используем GigaChat для анализа пробелов
        self.llm = create_llm(temperature=0.1)
        logger.info("✅ SelfAwarenessService initialized with GigaChat")
    
    def identify_knowledge_gaps(
        self,
        case_documents: str,
        agent_output: str,
        task_type: str
    ) -> List[GapType]:
        """
        Определяет пробелы в знаниях через эвристику (можно улучшить через GigaChat)
        
        Args:
            case_documents: Текст документов дела
            agent_output: Вывод агента
            task_type: Тип задачи агента
        
        Returns:
            Список типов пробелов
        """
        gaps = []
        
        # Простая эвристика для MVP
        case_lower = case_documents.lower()
        output_lower = agent_output.lower()
        
        # Проверка на нормы права
        norm_markers = [
            "нужна норма", "требуется норма", "нужна статья", "требуется статья",
            "согласно ст.", "статья", "норма права", "кодекс"
        ]
        has_norm_markers = any(m in output_lower for m in norm_markers)
        has_norm_in_docs = any(m in case_lower for m in ["статья", "норма", "кодекс"])
        
        if has_norm_markers and not has_norm_in_docs:
            gaps.append(GapType.MISSING_NORM)
        
        # Проверка на прецеденты
        precedent_markers = [
            "нужен прецедент", "аналогичные дела", "нужны аналогичные дела",
            "как суды решают", "судебная практика", "прецеденты"
        ]
        has_precedent_markers = any(m in output_lower for m in precedent_markers)
        has_precedent_in_docs = "аналогичное дело" in case_lower or "прецедент" in case_lower
        
        if has_precedent_markers and not has_precedent_in_docs:
            gaps.append(GapType.MISSING_PRECEDENT)
        
        # Проверка на позицию ВС
        court_markers = [
            "позиция вс", "разъяснения верховного суда", "разъяснения вс",
            "постановление пленума", "позиция верховного суда"
        ]
        has_court_markers = any(m in output_lower for m in court_markers)
        has_court_in_docs = "разъяснения вс" in case_lower or "позиция вс" in case_lower
        
        if has_court_markers and not has_court_in_docs:
            gaps.append(GapType.MISSING_COURT_POSITION)
        
        # Проверка на неясное толкование
        unclear_markers = [
            "неясно", "неясное толкование", "требуется уточнение",
            "недостаточно информации", "необходимо проверить"
        ]
        if any(m in output_lower for m in unclear_markers) and len(gaps) == 0:
            gaps.append(GapType.UNCLEAR_INTERPRETATION)
        
        # Можно использовать GigaChat для более точного анализа
        # Для MVP используем эвристику
        
        if gaps:
            logger.info(f"[SelfAwareness] Identified {len(gaps)} knowledge gaps: {[g.value for g in gaps]}")
        
        return gaps
    
    def should_search(self, gaps: List[GapType]) -> bool:
        """
        Определяет, нужен ли поиск
        
        Args:
            gaps: Список пробелов
        
        Returns:
            True если нужен поиск
        """
        return len(gaps) > 0
    
    def generate_search_strategy(self, gaps: List[GapType]) -> List[Dict[str, Any]]:
        """
        Генерирует стратегию поиска на основе пробелов
        
        Args:
            gaps: Список пробелов
        
        Returns:
            Список стратегий поиска с приоритетами
        """
        strategy = []
        for gap in gaps:
            if gap == GapType.MISSING_NORM:
                strategy.append({
                    "tool": "search_legislation_tool",
                    "priority": 1,
                    "gap_type": gap.value,
                    "description": "Поиск нормы права на pravo.gov.ru"
                })
            elif gap == GapType.MISSING_COURT_POSITION:
                strategy.append({
                    "tool": "search_supreme_court_tool",
                    "priority": 2,
                    "gap_type": gap.value,
                    "description": "Поиск позиции Верховного Суда на vsrf.ru"
                })
            elif gap == GapType.MISSING_PRECEDENT:
                strategy.append({
                    "tool": "search_case_law_tool",
                    "priority": 1,
                    "gap_type": gap.value,
                    "description": "Поиск прецедентов на kad.arbitr.ru"
                })
            else:
                strategy.append({
                    "tool": "smart_legal_search_tool",
                    "priority": 3,
                    "gap_type": gap.value,
                    "description": "Умный поиск с автоматическим выбором источника"
                })
        
        # Сортируем по приоритету
        strategy.sort(key=lambda x: x["priority"])
        
        logger.info(f"[SelfAwareness] Generated search strategy: {strategy}")
        
        return strategy


















































