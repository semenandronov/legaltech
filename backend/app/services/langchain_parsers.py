"""LangChain output parsers for Legal AI Vault"""
from typing import List, Dict, Any, Optional, Annotated
import logging

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field, field_validator, model_validator, BeforeValidator
from datetime import datetime

from app.services.date_validator import parse_and_normalize_date, validate_date_sequence

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

# Annotated type for date validation
DateStr = Annotated[str, BeforeValidator(parse_and_normalize_date)]


class TimelineEventModel(BaseModel):
    """Model for timeline event with date validation"""
    date: DateStr = Field(description="Date of the event in YYYY-MM-DD format or description")
    event_type: str = Field(description="Type of event (e.g., 'contract_signed', 'payment', 'deadline')")
    description: str = Field(description="Description of the event")
    source_document: str = Field(description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number in source document")
    source_line: Optional[int] = Field(None, description="Line number in source document")
    reasoning: Optional[str] = Field(None, description="Объяснение почему это событие было извлечено из документа")
    confidence: Optional[float] = Field(0.8, description="Уверенность в извлечении события (0-1)", ge=0.0, le=1.0)
    verification_status: Optional[str] = Field(None, description="Статус верификации цитаты: 'verified', 'unverified', 'pending'")
    
    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """
        Validate and normalize date format.
        
        Ensures date is in YYYY-MM-DD format after parsing.
        """
        if not v:
            raise ValueError("Date cannot be empty")
        
        # Check if already in correct format
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            # Try to normalize
            try:
                normalized = parse_and_normalize_date(v)
                # Verify normalized date
                datetime.strptime(normalized, "%Y-%m-%d")
                return normalized
            except Exception as e:
                logger.warning(f"Could not normalize date '{v}': {e}")
                # Return as-is, will be caught by model validator
                return v
    
    @field_validator('date')
    @classmethod
    def validate_date_reasonable(cls, v: str) -> str:
        """
        Validate that date is within reasonable bounds.
        """
        try:
            event_date = datetime.strptime(v, "%Y-%m-%d").date()
            if event_date.year < 1900:
                raise ValueError(f"Date {v} is before 1900 (likely parsing error)")
            if event_date.year > 2100:
                raise ValueError(f"Date {v} is after 2100 (likely parsing error)")
        except ValueError as e:
            if "parsing error" in str(e) or "after 2100" in str(e):
                raise
            # If it's a format error, let it pass (will be caught elsewhere)
            pass
        return v
    
    @model_validator(mode='after')
    def validate_date_context(self):
        """
        Validate date in context of other fields.
        Can be used for cross-field validation if needed.
        """
        return self


class DiscrepancyModel(BaseModel):
    """Model for discrepancy"""
    type: str = Field(description="Type of discrepancy (e.g., 'contradiction', 'missing_info', 'date_mismatch')")
    severity: str = Field(description="Severity level: HIGH, MEDIUM, or LOW")
    description: str = Field(description="Description of the discrepancy")
    source_documents: List[str] = Field(description="List of source document filenames")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    reasoning: str = Field(description="Объяснение почему это противоречие было обнаружено")
    confidence: float = Field(description="Уверенность в обнаружении противоречия (0-1)", ge=0.0, le=1.0)
    verification_status: Optional[str] = Field(None, description="Статус верификации цитаты: 'verified', 'unverified', 'pending'")


class KeyFactModel(BaseModel):
    """Model for key fact"""
    fact_type: str = Field(description="Type of fact (e.g., 'party', 'amount', 'date', 'condition')")
    value: str = Field(description="Value of the fact")
    description: Optional[str] = Field(None, description="Additional description")
    source_document: str = Field(description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    reasoning: str = Field(description="Объяснение почему этот факт считается ключевым")
    verification_status: Optional[str] = Field(None, description="Статус верификации цитаты: 'verified', 'unverified', 'pending'")


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


class RiskModel(BaseModel):
    """Model for risk analysis with Pydantic validators"""
    risk_name: str = Field(description="Название риска")
    risk_category: str = Field(description="Категория риска: legal, financial, reputational, procedural")
    probability: str = Field(description="Вероятность риска: HIGH, MEDIUM, LOW")
    impact: str = Field(description="Влияние риска: HIGH, MEDIUM, LOW")
    description: str = Field(description="Описание риска")
    evidence: List[str] = Field(description="Список документов-доказательств риска")
    recommendation: str = Field(description="Рекомендации по митигации риска")
    reasoning: str = Field(description="Обоснование риска с ссылками на документы")
    confidence: float = Field(description="Уверенность в оценке риска (0-1)", ge=0.0, le=1.0)
    verification_status: Optional[str] = Field(None, description="Статус верификации цитаты: 'verified', 'unverified', 'pending'")
    
    @field_validator('risk_category')
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate risk category"""
        valid_categories = ['legal', 'financial', 'reputational', 'procedural']
        v_lower = v.lower()
        if v_lower not in valid_categories:
            logger.warning(f"Invalid risk category '{v}', using 'legal' as default")
            return 'legal'
        return v_lower
    
    @field_validator('probability')
    @classmethod
    def validate_probability(cls, v: str) -> str:
        """Validate probability level"""
        valid_levels = ['HIGH', 'MEDIUM', 'LOW']
        v_upper = v.upper()
        if v_upper not in valid_levels:
            logger.warning(f"Invalid probability '{v}', using 'MEDIUM' as default")
            return 'MEDIUM'
        return v_upper
    
    @field_validator('impact')
    @classmethod
    def validate_impact(cls, v: str) -> str:
        """Validate impact level"""
        valid_levels = ['HIGH', 'MEDIUM', 'LOW']
        v_upper = v.upper()
        if v_upper not in valid_levels:
            logger.warning(f"Invalid impact '{v}', using 'MEDIUM' as default")
            return 'MEDIUM'
        return v_upper
    
    @field_validator('evidence')
    @classmethod
    def validate_evidence_not_empty(cls, v: List[str]) -> List[str]:
        """Validate that evidence list is not empty"""
        if not v or len(v) == 0:
            raise ValueError("Evidence list cannot be empty - risk must be supported by documents")
        return v


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
    def create_risk_parser() -> Optional[PydanticOutputParser]:
        """Create parser for risks"""
        if PydanticOutputParser is None:
            logger.warning("PydanticOutputParser not available")
            return None
        return PydanticOutputParser(pydantic_object=RiskModel)
    
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
                    # Добавляем значения по умолчанию для опциональных полей
                    if "reasoning" not in item:
                        item["reasoning"] = None
                    if "confidence" not in item:
                        item["confidence"] = 0.8
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
                    # Normalize field names - fix common LLM mistakes (кириллица -> латиница)
                    # LLM sometimes returns 'reasonинг' instead of 'reasoning'
                    if isinstance(item, dict):
                        # Fix reasoning field name
                        if 'reasonинг' in item and 'reasoning' not in item:
                            item['reasoning'] = item.pop('reasonинг')
                        # Ensure reasoning field exists (required by KeyFactModel)
                        if 'reasoning' not in item:
                            item['reasoning'] = item.get('reasonинг', '')
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
    
    @staticmethod
    def parse_risks(text: str) -> List[RiskModel]:
        """
        Parse risks from LLM output
        
        Args:
            text: LLM output text
            
        Returns:
            List of RiskModel objects
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
            
            risks = []
            for item in data:
                try:
                    risk = RiskModel(**item)
                    risks.append(risk)
                except Exception as e:
                    logger.warning(f"Failed to parse risk: {e}, data: {item}")
            
            return risks
        except Exception as e:
            logger.error(f"Error parsing risks: {e}")
            # Fallback: try to parse with parser if available
            parser = ParserService.create_risk_parser()
            if parser is not None:
                try:
                    parsed = parser.parse(text)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed]
                except:
                    pass
            return []
