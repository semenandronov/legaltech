"""Discrepancy finder service"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.analysis import Discrepancy
from app.services.rag_service import RAGService
from app.services.llm_service import LLMService
from app.services.langchain_parsers import ParserService, DiscrepancyModel
import re
import logging

logger = logging.getLogger(__name__)


class DiscrepancyFinder:
    """Service for finding discrepancies in documents"""
    
    def __init__(self, db: Session):
        """Initialize discrepancy finder"""
        self.db = db
        self.rag_service = RAGService()
        self.llm_service = LLMService()
    
    def find(self, case_id: str) -> Dict[str, Any]:
        """
        Find discrepancies in case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with discrepancies data
        """
        # Get case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Use RAG to find potential discrepancies
        query = "Найди все противоречия, несоответствия и расхождения между документами"
        relevant_docs = self.rag_service.retrieve_context(case_id, query, k=30)
        
        # Create parser for discrepancies
        parser = ParserService.create_discrepancy_parser()
        format_instructions = parser.get_format_instructions()
        
        # Use LLM to analyze discrepancies
        system_prompt = f"""Ты эксперт по анализу юридических документов.
Найди все противоречия, несоответствия и расхождения между документами.

Формат ответа:
{format_instructions}

ВАЖНО: Верни результат в формате JSON массива объектов."""
        
        sources_text = self.rag_service.format_sources_for_prompt(relevant_docs)
        user_prompt = f"""Проанализируй следующие документы и найди все противоречия:

{sources_text}

Верни результат в формате JSON массива противоречий."""
        
        try:
            full_system_prompt = f"{system_prompt}\n\n{format_instructions}"
            response = self.llm_service.generate(full_system_prompt, user_prompt, temperature=0.3)
            
            # Parse using ParserService
            parsed_discrepancies = ParserService.parse_discrepancies(response)
            
            # Save discrepancies to database
            saved_discrepancies = []
            for disc_model in parsed_discrepancies:
                try:
                    discrepancy = Discrepancy(
                        case_id=case_id,
                        type=disc_model.type,
                        severity=disc_model.severity,
                        description=disc_model.description,
                        source_documents=disc_model.source_documents,
                        details=disc_model.details
                    )
                    self.db.add(discrepancy)
                    saved_discrepancies.append(discrepancy)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении противоречия: {e}, discrepancy: {disc_model}")
                    continue
            
            self.db.commit()
            
            # Create result
            result = {
                "discrepancies": [
                    {
                        "id": disc.id,
                        "type": disc.type,
                        "severity": disc.severity,
                        "description": disc.description,
                        "source_documents": disc.source_documents,
                        "details": disc.details
                    }
                    for disc in saved_discrepancies
                ],
                "total": len(saved_discrepancies),
                "high_risk": len([d for d in saved_discrepancies if d.severity == "HIGH"]),
                "medium_risk": len([d for d in saved_discrepancies if d.severity == "MEDIUM"]),
                "low_risk": len([d for d in saved_discrepancies if d.severity == "LOW"])
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при поиске противоречий: {e}")
            raise

