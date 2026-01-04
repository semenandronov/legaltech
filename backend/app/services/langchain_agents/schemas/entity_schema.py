"""Entity Extraction Schema - Phase 2.1 Implementation

Schema for entity extraction agent outputs.
Supports persons, organizations, documents, dates, amounts, etc.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
from enum import Enum
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class EntityType(str, Enum):
    """Types of entities that can be extracted."""
    PERSON = "person"  # Физическое лицо
    ORGANIZATION = "organization"  # Юридическое лицо
    DOCUMENT = "document"  # Документ
    DATE = "date"  # Дата
    AMOUNT = "amount"  # Денежная сумма
    ADDRESS = "address"  # Адрес
    COURT = "court"  # Суд
    CASE_NUMBER = "case_number"  # Номер дела
    LAW_REFERENCE = "law_reference"  # Ссылка на законодательство
    CONTRACT = "contract"  # Договор
    PROPERTY = "property"  # Имущество
    PHONE = "phone"  # Телефон
    EMAIL = "email"  # Email
    INN = "inn"  # ИНН
    OGRN = "ogrn"  # ОГРН
    BANK_ACCOUNT = "bank_account"  # Банковский счет
    OTHER = "other"  # Другое


class Entity(BaseModel):
    """A single extracted entity."""
    
    entity_id: Optional[str] = Field(None, description="Unique identifier for the entity")
    entity_type: EntityType = Field(..., description="Type of the entity")
    value: str = Field(..., description="The extracted value", min_length=1, max_length=2000)
    normalized_value: Optional[str] = Field(None, description="Normalized form of the value")
    
    # Additional properties based on entity type
    role: Optional[str] = Field(None, description="Role in the case (e.g., 'истец', 'ответчик')")
    aliases: List[str] = Field(default_factory=list, description="Alternative names/references")
    
    # For persons
    full_name: Optional[str] = Field(None, description="Full name if entity is a person")
    position: Optional[str] = Field(None, description="Position/title if applicable")
    
    # For organizations
    legal_form: Optional[str] = Field(None, description="Legal form (ООО, АО, ИП, etc.)")
    registration_number: Optional[str] = Field(None, description="Registration number (ОГРН/ИНН)")
    
    # For amounts
    currency: Optional[str] = Field(None, description="Currency if entity is an amount")
    numeric_value: Optional[float] = Field(None, description="Parsed numeric value")
    
    # For dates
    date_parsed: Optional[str] = Field(None, description="Parsed date in ISO format")
    date_type: Optional[str] = Field(None, description="Type of date (signing, deadline, etc.)")
    
    # Metadata
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence in extraction")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    context: Optional[str] = Field(None, description="Surrounding context", max_length=500)
    
    # Relationships
    related_entities: List[str] = Field(default_factory=list, description="IDs of related entities")
    
    class Config:
        extra = "allow"
        use_enum_values = True
    
    @validator('value')
    def clean_value(cls, v):
        """Clean the value string."""
        if v:
            return v.strip()
        return v


class EntityResult(BaseModel):
    """Result of entity extraction for a single document or chunk."""
    
    document_id: Optional[str] = Field(None, description="Document ID")
    entities: List[Entity] = Field(default_factory=list, description="Extracted entities")
    entity_count: int = Field(0, description="Total number of entities")
    
    # Grouped entities by type
    persons: List[Entity] = Field(default_factory=list)
    organizations: List[Entity] = Field(default_factory=list)
    documents: List[Entity] = Field(default_factory=list)
    dates: List[Entity] = Field(default_factory=list)
    amounts: List[Entity] = Field(default_factory=list)
    
    def update_counts(self):
        """Update entity counts and group by type."""
        self.entity_count = len(self.entities)
        self.persons = [e for e in self.entities if e.entity_type == EntityType.PERSON]
        self.organizations = [e for e in self.entities if e.entity_type == EntityType.ORGANIZATION]
        self.documents = [e for e in self.entities if e.entity_type == EntityType.DOCUMENT]
        self.dates = [e for e in self.entities if e.entity_type == EntityType.DATE]
        self.amounts = [e for e in self.entities if e.entity_type == EntityType.AMOUNT]


class EntityExtractionOutput(BaseAgentOutput):
    """Full output from the entity extraction agent."""
    
    agent_name: str = Field(default="entity_extraction", description="Agent name")
    
    # All extracted entities
    entities: List[Entity] = Field(default_factory=list, description="All extracted entities")
    total_entities: int = Field(0, description="Total number of entities")
    
    # Grouped by type for easy access
    persons: List[Entity] = Field(default_factory=list)
    organizations: List[Entity] = Field(default_factory=list)
    documents: List[Entity] = Field(default_factory=list)
    dates: List[Entity] = Field(default_factory=list)
    amounts: List[Entity] = Field(default_factory=list)
    addresses: List[Entity] = Field(default_factory=list)
    law_references: List[Entity] = Field(default_factory=list)
    
    # Entity relationships graph
    relationships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Relationships between entities"
    )
    
    # Summary statistics
    entity_type_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of entities by type"
    )
    
    def compute_statistics(self):
        """Compute summary statistics from entities."""
        self.total_entities = len(self.entities)
        
        # Group by type
        self.persons = []
        self.organizations = []
        self.documents = []
        self.dates = []
        self.amounts = []
        self.addresses = []
        self.law_references = []
        
        type_counts = {}
        
        for entity in self.entities:
            entity_type = entity.entity_type
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
            
            if entity_type == EntityType.PERSON:
                self.persons.append(entity)
            elif entity_type == EntityType.ORGANIZATION:
                self.organizations.append(entity)
            elif entity_type == EntityType.DOCUMENT:
                self.documents.append(entity)
            elif entity_type == EntityType.DATE:
                self.dates.append(entity)
            elif entity_type == EntityType.AMOUNT:
                self.amounts.append(entity)
            elif entity_type == EntityType.ADDRESS:
                self.addresses.append(entity)
            elif entity_type == EntityType.LAW_REFERENCE:
                self.law_references.append(entity)
        
        self.entity_type_counts = type_counts

