"""Entity Extraction Service for Tabular Review Entity Table mode"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.case import File
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class Entity(BaseModel):
    """Single entity extracted from document"""
    index: int = Field(description="Order index of entity in document")
    fields: Dict[str, Any] = Field(description="Extracted fields for this entity")
    source_page: Optional[int] = Field(None, description="Page number where entity was found")
    source_section: Optional[str] = Field(None, description="Section where entity was found")
    source_text: Optional[str] = Field(None, description="Source text excerpt for this entity")


class EntityExtractionResult(BaseModel):
    """Result of entity extraction"""
    entities: List[Entity] = Field(description="List of extracted entities")
    total_count: int = Field(description="Total number of entities found")


class EntityExtractionService:
    """Service for extracting entities from documents for Entity Table mode"""
    
    def __init__(self, db: Session):
        """Initialize entity extraction service"""
        self.db = db
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
        except Exception as e:
            self.llm = None
            logger.warning(f"GigaChat not configured: {e}, entity extraction will not work")
    
    async def extract_entities(
        self,
        file: File,
        entity_config: Dict[str, Any]
    ) -> List[Entity]:
        """
        Extract entities from a document
        
        Args:
            file: File to extract entities from
            entity_config: Configuration dict with:
                - entity_type: str (e.g., "payment", "shipment", "letter")
                - extraction_prompt: str (prompt for extracting entities)
                - grouping_key: Optional[str] (key for grouping entities)
        
        Returns:
            List of Entity objects
        """
        if not self.llm:
            raise ValueError("LLM not configured")
        
        if not file.original_text:
            logger.warning(f"File {file.id} has no text content")
            return []
        
        entity_type = entity_config.get("entity_type", "entity")
        extraction_prompt = entity_config.get("extraction_prompt", f"Extract all {entity_type} entities from this document")
        
        # Build prompt for entity extraction
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""Ты эксперт по извлечению структурированных данных из юридических документов.

Твоя задача: извлечь все сущности типа "{entity_type}" из документа.

Для каждой сущности верни:
- index: порядковый номер сущности в документе (начиная с 0)
- fields: словарь с извлеченными полями (зависит от типа сущности)
- source_page: номер страницы (если доступно)
- source_section: раздел документа (если доступно)
- source_text: короткая цитата из документа для этой сущности

ВАЖНО:
- Извлекай ВСЕ сущности данного типа из документа
- Для каждой сущности указывай точные координаты (страница, раздел)
- Если сущностей нет, верни пустой список
- Сохраняй порядок появления сущностей в документе (index должен соответствовать порядку)"""),
            ("human", f"""{extraction_prompt}

Документ:
{file.original_text}

Извлеки все сущности типа "{entity_type}" и верни их в виде списка.""")
        ])
        
        try:
            # Use structured output
            structured_llm = self.llm.with_structured_output(
                EntityExtractionResult,
                method="json_schema"
            )
            chain = prompt | structured_llm
            result = await chain.ainvoke({})
            
            return result.entities
            
        except Exception as e:
            logger.error(f"Error extracting entities from file {file.id}: {e}", exc_info=True)
            # Fallback: try to parse as JSON
            try:
                chain = prompt | self.llm
                response = await chain.ainvoke({})
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Try to parse JSON manually
                import json
                data = json.loads(response_text)
                if isinstance(data, dict) and "entities" in data:
                    entities_data = data["entities"]
                    return [Entity(**entity_data) for entity_data in entities_data]
                else:
                    logger.warning(f"Unexpected response format for entity extraction: {response_text[:200]}")
                    return []
            except Exception as parse_error:
                logger.error(f"Failed to parse entity extraction response: {parse_error}")
                return []
    
    def create_virtual_file_id(self, real_file_id: str, entity_index: int) -> str:
        """Create virtual file_id for entity row"""
        return f"{real_file_id}_entity_{entity_index}"
    
    def parse_virtual_file_id(self, virtual_file_id: str) -> Optional[Dict[str, Any]]:
        """Parse virtual file_id to extract real file_id and entity_index"""
        if "_entity_" not in virtual_file_id:
            return None
        
        parts = virtual_file_id.rsplit("_entity_", 1)
        if len(parts) != 2:
            return None
        
        try:
            return {
                "source_file_id": parts[0],
                "entity_index": int(parts[1])
            }
        except ValueError:
            return None

