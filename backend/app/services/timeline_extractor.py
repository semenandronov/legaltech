"""Timeline extractor service"""
from typing import Dict, Any, List
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.analysis import TimelineEvent
from app.services.rag_service import RAGService
from app.services.llm_factory import create_llm
from app.services.langchain_parsers import ParserService, TimelineEventModel
import re
import logging
import json

logger = logging.getLogger(__name__)


class TimelineExtractor:
    """Service for extracting timeline events from documents"""
    
    def __init__(self, db: Session):
        """Initialize timeline extractor"""
        self.db = db
        self.rag_service = RAGService()
        # Use use_rate_limiting=False for LangChain | operator compatibility
        self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
    
    def extract(self, case_id: str) -> Dict[str, Any]:
        """
        Extract timeline from case documents
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with timeline events
        """
        # Get case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Use RAG to find date-related information
        query = "Найди все даты и события в хронологическом порядке с указанием источников"
        relevant_docs = self.rag_service.retrieve_context(case_id, query, k=20)
        
        # Create parser for timeline events
        parser = ParserService.create_timeline_parser()
        if parser is not None:
            format_instructions = parser.get_format_instructions()
        else:
            format_instructions = "Верни результат в формате JSON массива объектов с полями: date, event_type, description, source_document, source_page (опционально), source_line (опционально)."
        
        # Use LLM to extract structured timeline
        system_prompt = f"""Ты эксперт по извлечению временных событий из юридических документов.
Извлеки все даты и события из предоставленных документов.

Формат ответа:
{format_instructions}

ВАЖНО: Верни результат в формате JSON массива объектов, каждый объект соответствует одному событию.
Каждый объект должен содержать: date, event_type, description, source_document, source_page (опционально), source_line (опционально)."""
        
        sources_text = self.rag_service.format_sources_for_prompt(relevant_docs)
        
        # Add format instructions to prompt
        full_system_prompt = f"{system_prompt}\n\n{format_instructions}"
        user_prompt = f"""Извлеки все даты и события из следующих документов:

{sources_text}

Верни результат в формате JSON массив событий:
[
  {{
    "date": "YYYY-MM-DD",
    "event_type": "тип события",
    "description": "описание",
    "source_file": "имя файла",
    "source_page": номер страницы,
    "source_line": номер строки
  }}
]"""
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", full_system_prompt),
                ("human", user_prompt)
            ])
            chain = prompt | self.llm
            response = chain.invoke({})
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse using ParserService
            parsed_events = ParserService.parse_timeline_events(response_text)
            
            # Save events to database
            saved_events = []
            for event_model in parsed_events:
                try:
                    # Parse date
                    date_str = event_model.date
                    try:
                        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except:
                        # Try other date formats or use current date
                        event_date = datetime.now().date()
                    
                    # Create timeline event
                    event = TimelineEvent(
                        case_id=case_id,
                        date=event_date,  # Use date field from model
                        event_type=event_model.event_type,
                        description=event_model.description,
                        source_document=event_model.source_document,
                        source_page=event_model.source_page,
                        source_line=event_model.source_line,
                        event_metadata={"parsed_from_llm": True}
                    )
                    self.db.add(event)
                    saved_events.append(event)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении события: {e}, event: {event_model}")
                    continue
            
            self.db.commit()
            
            logger.info(f"Extracted {len(saved_events)} timeline events for case {case_id}")
            
            # Create result
            result = {
                "events": [
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "event_type": event.event_type,
                        "description": event.description,
                        "source_document": event.source_document,
                        "source_page": event.source_page,
                        "source_line": event.source_line
                    }
                    for event in saved_events
                ],
                "total_events": len(saved_events)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении таймлайна: {e}", exc_info=True)
            raise

