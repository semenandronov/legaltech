"""Key facts extractor service"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.analysis import AnalysisResult
from app.services.rag_service import RAGService
from app.services.llm_factory import create_llm
from app.services.langchain_parsers import ParserService, KeyFactModel
import json
import re
import logging

logger = logging.getLogger(__name__)


class KeyFactsExtractor:
    """Service for extracting key facts from documents"""
    
    def __init__(self, db: Session):
        """Initialize key facts extractor"""
        self.db = db
        self.rag_service = RAGService()
        # Use use_rate_limiting=False for LangChain | operator compatibility
        self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
    
    def extract(self, case_id: str) -> Dict[str, Any]:
        """
        Extract key facts from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with key facts data
        """
        # Get case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Use RAG to find key information
        query = "Извлеки ключевые факты: стороны спора, суммы, даты, суть спора, судья, суд"
        relevant_docs = self.rag_service.retrieve_context(case_id, query, k=20)
        
        # Create parser for key facts
        parser = ParserService.create_key_facts_parser()
        if parser is not None:
            format_instructions = parser.get_format_instructions()
        else:
            format_instructions = "Верни результат в формате JSON массива объектов с полями: fact_type, value, description, source_document, source_page (опционально), confidence (опционально)."
        
        # Use LLM to extract structured key facts
        system_prompt = f"""Ты эксперт по извлечению ключевых фактов из юридических документов.
Извлеки структурированную информацию о деле.

Формат ответа:
{format_instructions}

ВАЖНО: Верни результат в формате JSON массива объектов с фактами."""
        
        sources_text = self.rag_service.format_sources_for_prompt(relevant_docs)
        user_prompt = f"""Извлеки ключевые факты из следующих документов:

{sources_text}

Верни результат в формате JSON массива фактов.
Каждый факт должен содержать: fact_type, value, description (опционально), source_document, source_page (опционально), confidence (опционально)."""
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            full_system_prompt = f"{system_prompt}\n\n{format_instructions}"
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", full_system_prompt),
                ("human", user_prompt)
            ])
            chain = prompt | self.llm
            response = chain.invoke({})
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse using ParserService
            parsed_facts = ParserService.parse_key_facts(response_text)
            
            # Convert to structured format
            facts_data = {
                "parties": [],
                "amounts": [],
                "dates": [],
                "other": []
            }
            
            for fact_model in parsed_facts:
                fact_dict = {
                    "fact_type": fact_model.fact_type,
                    "value": fact_model.value,
                    "description": fact_model.description,
                    "source_document": fact_model.source_document,
                    "source_page": fact_model.source_page,
                    "confidence": fact_model.confidence
                }
                
                # Categorize facts
                if fact_model.fact_type in ["plaintiff", "defendant", "party"]:
                    facts_data["parties"].append(fact_dict)
                elif fact_model.fact_type in ["amount", "payment", "penalty", "cost"]:
                    facts_data["amounts"].append(fact_dict)
                elif fact_model.fact_type in ["date", "deadline", "event_date"]:
                    facts_data["dates"].append(fact_dict)
                else:
                    facts_data["other"].append(fact_dict)
            
            # Save to database
            result = AnalysisResult(
                case_id=case_id,
                analysis_type="key_facts",
                result_data=facts_data,
                status="completed"
            )
            self.db.add(result)
            self.db.commit()
            
            return {
                "facts": facts_data,
                "result_id": result.id
            }
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении ключевых фактов: {e}")
            raise

