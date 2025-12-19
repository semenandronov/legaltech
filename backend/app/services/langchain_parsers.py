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
    reasoning: str = Field(description="Объяснение почему это событие было извлечено из документа")
    confidence: float = Field(description="Уверенность в извлечении события (0-1)", ge=0.0, le=1.0)


class DiscrepancyModel(BaseModel):
    """Model for discrepancy"""
    type: str = Field(description="Type of discrepancy (e.g., 'contradiction', 'missing_info', 'date_mismatch')")
    severity: str = Field(description="Severity level: HIGH, MEDIUM, or LOW")
    description: str = Field(description="Description of the discrepancy")
    source_documents: List[str] = Field(description="List of source document filenames")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    reasoning: str = Field(description="Объяснение почему это противоречие было обнаружено")
    confidence: float = Field(description="Уверенность в обнаружении противоречия (0-1)", ge=0.0, le=1.0)


class KeyFactModel(BaseModel):
    """Model for key fact"""
    fact_type: str = Field(description="Type of fact (e.g., 'party', 'amount', 'date', 'condition')")
    value: str = Field(description="Value of the fact")
    description: Optional[str] = Field(None, description="Additional description")
    source_document: str = Field(description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    reasoning: str = Field(description="Объяснение почему этот факт считается ключевым")


class DocumentClassificationModel(BaseModel):
    """Model for document classification"""
    doc_type: str = Field(description="Тип документа: письмо, контракт, отчет и т.д.")
    relevance_score: int = Field(description="Релевантность к делу (0-100)", ge=0, le=100)
    is_privileged: bool = Field(description="Защищено ли привилегией (предварительная оценка)")
    privilege_type: str = Field(description="Тип привилегии: attorney-client, work-product, none")
    key_topics: List[str] = Field(description="Массив основных тем документа")
    confidence: float = Field(description="Уверенность классификации (0-1)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Подробное объяснение решения классификации - это критично!")


class EntityModel(BaseModel):
    """Model for extracted entity"""
    text: str = Field(description="Текст сущности")
    type: str = Field(description="Тип сущности: PERSON, ORG, DATE, AMOUNT, CONTRACT_TERM")
    confidence: float = Field(description="Уверенность в извлечении (0-1)", ge=0.0, le=1.0)
    context: str = Field(description="Контекст, в котором была найдена сущность")


class EntitiesExtractionModel(BaseModel):
    """Model for entities extraction result"""
    entities: List[EntityModel] = Field(description="Извлеченные сущности")


class PrivilegeCheckModel(BaseModel):
    """Model for privilege check result"""
    is_privileged: bool = Field(description="Защищено ли привилегией")
    privilege_type: str = Field(description="Тип привилегии: attorney-client, work-product, none")
    confidence: float = Field(description="Уверенность проверки (0-100, критично >95%)", ge=0.0, le=100.0)
    reasoning: List[str] = Field(description="Ключевые факторы для решения (массив строк)")
    withhold_recommendation: bool = Field(description="Рекомендация не раскрывать документ")


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
    def parse_document_classification(text: str) -> DocumentClassificationModel:
        """
        Parse document classification from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            DocumentClassificationModel object
        """
        try:
            import json
            # Extract JSON from text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            
            # Handle both dict and single object
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            classification = DocumentClassificationModel(**data)
            return classification
        except Exception as e:
            logger.error(f"Error parsing document classification: {e}")
            # Return default classification on error
            return DocumentClassificationModel(
                doc_type="unknown",
                relevance_score=0,
                is_privileged=False,
                privilege_type="none",
                key_topics=[],
                confidence=0.0,
                reasoning=f"Ошибка парсинга: {str(e)}"
            )
    
    @staticmethod
    def parse_entities(text: str) -> EntitiesExtractionModel:
        """
        Parse entities extraction from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            EntitiesExtractionModel object
        """
        try:
            import json
            # Extract JSON from text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            
            # Handle both dict with entities key and direct list
            if isinstance(data, dict) and "entities" in data:
                entities_data = data["entities"]
            elif isinstance(data, list):
                entities_data = data
            else:
                entities_data = []
            
            entities = []
            for item in entities_data:
                try:
                    entity = EntityModel(**item)
                    entities.append(entity)
                except Exception as e:
                    logger.warning(f"Failed to parse entity: {e}, data: {item}")
            
            return EntitiesExtractionModel(entities=entities)
        except Exception as e:
            logger.error(f"Error parsing entities: {e}")
            return EntitiesExtractionModel(entities=[])
    
    @staticmethod
    def parse_privilege_check(text: str) -> PrivilegeCheckModel:
        """
        Parse privilege check from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            PrivilegeCheckModel object
        """
        try:
            import json
            # Extract JSON from text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            
            # Handle both dict and single object
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            privilege_check = PrivilegeCheckModel(**data)
            return privilege_check
        except Exception as e:
            logger.error(f"Error parsing privilege check: {e}")
            # Return default privilege check on error (safe default: not privileged)
            return PrivilegeCheckModel(
                is_privileged=False,
                privilege_type="none",
                confidence=0.0,
                reasoning=[f"Ошибка парсинга: {str(e)}"],
                withhold_recommendation=False
            )
    
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
