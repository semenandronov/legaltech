"""Analysis service for coordinating different types of analysis"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.analysis import AnalysisResult
from app.services.timeline_extractor import TimelineExtractor
from app.services.discrepancy_finder import DiscrepancyFinder
from app.services.key_facts_extractor import KeyFactsExtractor
import logging

logger = logging.getLogger(__name__)


class AnalysisService:
    """Service for coordinating analysis operations"""
    
    def __init__(self, db: Session):
        """Initialize analysis service"""
        self.db = db
        self.timeline_extractor = TimelineExtractor(db)
        self.discrepancy_finder = DiscrepancyFinder(db)
        self.key_facts_extractor = KeyFactsExtractor(db)
    
    def extract_timeline(self, case_id: str) -> Dict[str, Any]:
        """
        Extract timeline from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with timeline data
        """
        return self.timeline_extractor.extract(case_id)
    
    def find_discrepancies(self, case_id: str) -> Dict[str, Any]:
        """
        Find discrepancies in case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with discrepancies data
        """
        return self.discrepancy_finder.find(case_id)
    
    def extract_key_facts(self, case_id: str) -> Dict[str, Any]:
        """
        Extract key facts from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with key facts data
        """
        return self.key_facts_extractor.extract(case_id)
    
    def generate_summary(self, case_id: str) -> Dict[str, Any]:
        """
        Generate summary of the case
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with summary data
        """
        # Get case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Use key facts extractor for summary
        key_facts = self.extract_key_facts(case_id)
        
        # Generate summary text
        from app.services.llm_service import LLMService
        llm_service = LLMService()
        
        system_prompt = """Ты эксперт по анализу юридических дел.
Создай краткое резюме дела на основе предоставленной информации."""
        
        user_prompt = f"""Создай краткое резюме следующего дела:

{key_facts.get('facts', {})}

Создай структурированное резюме с разделами:
1. Суть дела
2. Стороны спора
3. Ключевые факты
4. Основные даты
5. Текущий статус"""
        
        summary_text = llm_service.generate(system_prompt, user_prompt)
        
        # Save to database
        result = AnalysisResult(
            case_id=case_id,
            analysis_type="summary",
            result_data={"summary": summary_text, "key_facts": key_facts},
            status="completed"
        )
        self.db.add(result)
        self.db.commit()
        
        return {
            "summary": summary_text,
            "key_facts": key_facts,
            "result_id": result.id
        }
    
    def analyze_risks(self, case_id: str) -> Dict[str, Any]:
        """
        Analyze risks for the case
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with risk analysis data
        """
        # Get case and related data
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Get discrepancies
        discrepancies = self.find_discrepancies(case_id)
        
        # Use LLM for risk analysis
        from app.services.llm_service import LLMService
        llm_service = LLMService()
        
        system_prompt = """Ты эксперт по анализу юридических рисков.
Оцени риски дела на основе предоставленной информации.
Укажи уровень риска: HIGH, MEDIUM, LOW для каждого аспекта."""
        
        user_prompt = f"""Проанализируй риски следующего дела:

Тип дела: {case.case_type or 'Не указан'}
Описание: {case.description or 'Нет описания'}

Найденные противоречия:
{discrepancies.get('discrepancies', [])}

Оцени риски по следующим категориям:
1. Юридические риски
2. Финансовые риски
3. Репутационные риски
4. Процессуальные риски

Для каждой категории укажи:
- Уровень риска (HIGH/MEDIUM/LOW)
- Обоснование
- Рекомендации"""
        
        risk_analysis = llm_service.generate(system_prompt, user_prompt)
        
        # Save to database
        result = AnalysisResult(
            case_id=case_id,
            analysis_type="risk_analysis",
            result_data={
                "analysis": risk_analysis,
                "discrepancies": discrepancies
            },
            status="completed"
        )
        self.db.add(result)
        self.db.commit()
        
        return {
            "analysis": risk_analysis,
            "discrepancies": discrepancies,
            "result_id": result.id
        }

