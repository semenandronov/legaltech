"""LangChain output parsers for Legal AI Vault"""
from typing import List, Dict, Any, Optional
import logging

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import parsers with fallback strategies
PydanticOutputParser = None
StructuredOutputParser = None
CommaSeparatedListOutputParser = None

try:
    from langchain_core.output_parsers import PydanticOutputParser, CommaSeparatedListOutputParser
    logger.debug("PydanticOutputParser and CommaSeparatedListOutputParser imported from langchain_core")
except ImportError:
    try:
        from langchain.output_parsers import PydanticOutputParser, CommaSeparatedListOutputParser
        logger.debug("PydanticOutputParser and CommaSeparatedListOutputParser imported from langchain")
    except ImportError:
        logger.warning("PydanticOutputParser and CommaSeparatedListOutputParser not available")

try:
    from langchain_core.output_parsers import StructuredOutputParser
    logger.debug("StructuredOutputParser imported from langchain_core")
except ImportError:
    try:
        from langchain.output_parsers import StructuredOutputParser
        logger.debug("StructuredOutputParser imported from langchain")
    except ImportError:
        logger.warning("StructuredOutputParser not available")


# Pydantic models for structured outputs
class TimelineEventModel(BaseModel):
    """Model for timeline event"""
    date: str = Field(description="Date of the event in YYYY-MM-DD format or description")
    event_type: str = Field(description="Type of event (e.g., 'contract_signed', 'payment', 'deadline')")
    description: str = Field(description="Description of the event")
    source_document: str = Field(description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number in source document")
    source_line: Optional[int] = Field(None, description="Line number in source document")


class DiscrepancyModel(BaseModel):
    """Model for discrepancy"""
    type: str = Field(description="Type of discrepancy (e.g., 'contradiction', 'missing_info', 'date_mismatch')")
    severity: str = Field(description="Severity level: HIGH, MEDIUM, or LOW")
    description: str = Field(description="Description of the discrepancy")
    source_documents: List[str] = Field(description="List of source document filenames")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")


class KeyFactModel(BaseModel):
    """Model for key fact"""
    fact_type: str = Field(description="Type of fact (e.g., 'party', 'amount', 'date', 'condition')")
    value: str = Field(description="Value of the fact")
    description: Optional[str] = Field(None, description="Additional description")
    source_document: str = Field(description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number")
    confidence: Optional[float] = Field(None, description="Confidence score 0-1")


class ParserService:
    """Service for output parsing"""
    
    @staticmethod
    def create_timeline_parser() -> Optional[PydanticOutputParser]:
        """Create parser for timeline events"""
        if PydanticOutputParser is None:
            logger.warning("PydanticOutputParser not available")
            return None
        return PydanticOutputParser(pydantic_object=TimelineEventModel)
    
    @staticmethod
    def create_discrepancy_parser() -> Optional[PydanticOutputParser]:
        """Create parser for discrepancies"""
        if PydanticOutputParser is None:
            logger.warning("PydanticOutputParser not available")
            return None
        return PydanticOutputParser(pydantic_object=DiscrepancyModel)
    
    @staticmethod
    def create_key_facts_parser() -> Optional[PydanticOutputParser]:
        """Create parser for key facts"""
        if PydanticOutputParser is None:
            logger.warning("PydanticOutputParser not available")
            return None
        return PydanticOutputParser(pydantic_object=KeyFactModel)
    
    @staticmethod
    def create_list_parser() -> Optional[CommaSeparatedListOutputParser]:
        """Create parser for comma-separated lists"""
        if CommaSeparatedListOutputParser is None:
            logger.warning("CommaSeparatedListOutputParser not available")
            return None
        return CommaSeparatedListOutputParser()
    
    @staticmethod
    def create_structured_parser(response_schema: Dict[str, Any]) -> Optional[StructuredOutputParser]:
        """Create structured output parser from schema"""
        if StructuredOutputParser is None:
            logger.warning("StructuredOutputParser not available")
            return None
        return StructuredOutputParser.from_response_schema(response_schema)
    
    @staticmethod
    def parse_timeline_events(text: str) -> List[TimelineEventModel]:
        """
        Parse timeline events from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            List of TimelineEventModel objects
        """
        try:
            # Try to parse as JSON array
            import json
            # Extract JSON from text if wrapped in markdown
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            data = json.loads(text)
            
            # Handle both single object and array
            if isinstance(data, dict):
                data = [data]
            
            # Parse each event
            events = []
            for item in data:
                try:
                    event = TimelineEventModel(**item)
                    events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to parse timeline event: {e}, data: {item}")
            
            return events
        except Exception as e:
            logger.error(f"Error parsing timeline events: {e}")
            # Fallback: try to parse with parser if available
            parser = ParserService.create_timeline_parser()
            if parser is not None:
                try:
                    parsed = parser.parse(text)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed]
                except:
                    pass
            return []
    
    @staticmethod
    def parse_discrepancies(text: str) -> List[DiscrepancyModel]:
        """
        Parse discrepancies from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            List of DiscrepancyModel objects
        """
        try:
            import json
            # Extract JSON from text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            
            if isinstance(data, dict):
                data = [data]
            
            discrepancies = []
            for item in data:
                try:
                    disc = DiscrepancyModel(**item)
                    discrepancies.append(disc)
                except Exception as e:
                    logger.warning(f"Failed to parse discrepancy: {e}, data: {item}")
            
            return discrepancies
        except Exception as e:
            logger.error(f"Error parsing discrepancies: {e}")
            # Fallback: try to parse with parser if available
            parser = ParserService.create_discrepancy_parser()
            if parser is not None:
                try:
                    parsed = parser.parse(text)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed]
                except:
                    pass
            return []
    
    @staticmethod
    def parse_key_facts(text: str) -> List[KeyFactModel]:
        """
        Parse key facts from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            List of KeyFactModel objects
        """
        try:
            import json
            # Extract JSON from text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            
            if isinstance(data, dict):
                data = [data]
            
            facts = []
            for item in data:
                try:
                    fact = KeyFactModel(**item)
                    facts.append(fact)
                except Exception as e:
                    logger.warning(f"Failed to parse key fact: {e}, data: {item}")
            
            return facts
        except Exception as e:
            logger.error(f"Error parsing key facts: {e}")
            # Fallback: try to parse with parser if available
            parser = ParserService.create_key_facts_parser()
            if parser is not None:
                try:
                    parsed = parser.parse(text)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed]
                except:
                    pass
            return []
