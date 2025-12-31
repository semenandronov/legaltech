"""Analysis service for coordinating different types of analysis"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.analysis import AnalysisResult
from app.services.timeline_extractor import TimelineExtractor
from app.services.discrepancy_finder import DiscrepancyFinder
from app.services.key_facts_extractor import KeyFactsExtractor
from app.services.langchain_agents import AgentCoordinator
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.config import config
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
        
        # Initialize agent coordinator if enabled
        self.use_agents = config.AGENT_ENABLED
        if self.use_agents:
            try:
                rag_service = RAGService()
                document_processor = DocumentProcessor()
                self.agent_coordinator = AgentCoordinator(db, rag_service, document_processor)
                logger.info("Multi-agent system enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize agent coordinator, falling back to legacy: {e}")
                self.use_agents = False
        else:
            logger.info("Multi-agent system disabled, using legacy extractors")
    
    def run_agent_analysis(self, case_id: str, analysis_types: List[str], step_callback: Optional[Any] = None) -> Dict[str, Any]:
        """
        Run analysis using multi-agent system
        
        Args:
            case_id: Case identifier
            analysis_types: List of analysis types to run
            step_callback: Optional callback function to be called for each execution step
        
        Returns:
            Dictionary with all analysis results
        """
        if not self.use_agents:
            raise ValueError("Agent system is disabled. Use individual methods or enable AGENT_ENABLED.")
        
        return self.agent_coordinator.run_analysis(case_id, analysis_types, step_callback=step_callback)
    
    def extract_timeline(self, case_id: str) -> Dict[str, Any]:
        """
        Extract timeline from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with timeline data
        """
        if self.use_agents:
            results = self.agent_coordinator.run_analysis(case_id, ["timeline"])
            return results.get("timeline") or {}
        return self.timeline_extractor.extract(case_id)
    
    def find_discrepancies(self, case_id: str) -> Dict[str, Any]:
        """
        Find discrepancies in case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with discrepancies data
        """
        if self.use_agents:
            results = self.agent_coordinator.run_analysis(case_id, ["discrepancy"])
            return results.get("discrepancies") or {}
        return self.discrepancy_finder.find(case_id)
    
    def extract_key_facts(self, case_id: str) -> Dict[str, Any]:
        """
        Extract key facts from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with key facts data
        """
        if self.use_agents:
            results = self.agent_coordinator.run_analysis(case_id, ["key_facts"])
            return results.get("key_facts") or {}
        return self.key_facts_extractor.extract(case_id)
    
    def generate_summary(self, case_id: str) -> Dict[str, Any]:
        """
        Generate summary of the case
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with summary data
        """
        if self.use_agents:
            results = self.agent_coordinator.run_analysis(case_id, ["key_facts", "summary"])
            summary_result = results.get("summary")
            if summary_result:
                return summary_result
        
        # Fallback to legacy method
        # Get case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Use key facts extractor for summary
        key_facts = self.extract_key_facts(case_id)
        
        # Generate summary text using GigaChat
        from app.services.llm_factory import create_llm
        from langchain_core.prompts import ChatPromptTemplate
        
        llm = create_llm(temperature=0.7)
        
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
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        chain = prompt | llm
        response = chain.invoke({})
        summary_text = response.content if hasattr(response, 'content') else str(response)
        
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
        if self.use_agents:
            results = self.agent_coordinator.run_analysis(case_id, ["discrepancy", "risk"])
            risk_result = results.get("risk_analysis")
            if risk_result:
                return risk_result
        
        # Fallback to legacy method
        # Get case and related data
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Get discrepancies
        discrepancies = self.find_discrepancies(case_id)
        
        # Use LLM for risk analysis using GigaChat
        from app.services.llm_factory import create_llm
        from langchain_core.prompts import ChatPromptTemplate
        
        llm = create_llm(temperature=0.7)
        
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
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        chain = prompt | llm
        response = chain.invoke({})
        risk_analysis = response.content if hasattr(response, 'content') else str(response)
        
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

