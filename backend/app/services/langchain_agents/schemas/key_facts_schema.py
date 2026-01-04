"""Key Facts Schema - Phase 2.1 Implementation

Schema for key facts extraction agent outputs.
Supports categorized facts with legal significance.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class FactCategory(str, Enum):
    """Categories of key facts."""
    CONTRACTUAL = "contractual"  # Договорные условия
    FINANCIAL = "financial"  # Финансовые обязательства
    VIOLATION = "violation"  # Нарушения
    EVIDENCE = "evidence"  # Доказательства
    PROCEDURAL = "procedural"  # Процессуальные факты
    PARTY_INFO = "party_info"  # Информация о сторонах
    LEGAL_BASIS = "legal_basis"  # Правовые основания
    DISPUTED = "disputed"  # Спорные факты
    UNDISPUTED = "undisputed"  # Бесспорные факты
    CIRCUMSTANTIAL = "circumstantial"  # Обстоятельства дела
    OTHER = "other"


class KeyFact(BaseModel):
    """A single key fact extracted from documents."""
    
    fact_id: Optional[str] = Field(None, description="Unique fact identifier")
    category: FactCategory = Field(FactCategory.OTHER, description="Fact category")
    
    # Fact content
    statement: str = Field(..., description="The fact statement", max_length=2000)
    summary: Optional[str] = Field(None, description="Brief summary", max_length=200)
    
    # Importance and relevance
    importance: str = Field("medium", description="Importance level: high, medium, low")
    relevance_to_case: Optional[str] = Field(None, description="How this fact relates to case")
    legal_significance: Optional[str] = Field(None, description="Legal significance")
    
    # Supporting information
    date: Optional[str] = Field(None, description="Date associated with fact")
    parties_involved: List[str] = Field(default_factory=list, description="Parties related to fact")
    document_references: List[str] = Field(default_factory=list, description="Referenced documents")
    
    # Verification status
    is_disputed: bool = Field(False, description="Whether the fact is disputed")
    disputed_by: Optional[str] = Field(None, description="Who disputes this fact")
    supporting_evidence: List[str] = Field(default_factory=list, description="Evidence supporting fact")
    contradicting_evidence: List[str] = Field(default_factory=list, description="Evidence contradicting fact")
    
    # Amounts if applicable
    amount: Optional[float] = Field(None, description="Associated monetary amount")
    currency: Optional[str] = Field(None, description="Currency for amount")
    
    # Metadata
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence in extraction")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    
    # Relations
    related_facts: List[str] = Field(default_factory=list, description="IDs of related facts")
    contradicts: List[str] = Field(default_factory=list, description="IDs of contradicting facts")
    
    class Config:
        extra = "allow"
        use_enum_values = True


class KeyFactsResult(BaseAgentOutput):
    """Full output from the key facts extraction agent."""
    
    agent_name: str = Field(default="key_facts", description="Agent name")
    
    # All extracted facts
    facts: List[KeyFact] = Field(default_factory=list, description="All key facts")
    total_facts: int = Field(0, description="Total number of facts")
    
    # Grouped by category
    facts_by_category: Dict[str, List[KeyFact]] = Field(
        default_factory=dict,
        description="Facts grouped by category"
    )
    
    # Priority facts
    high_importance_facts: List[KeyFact] = Field(
        default_factory=list,
        description="Facts marked as high importance"
    )
    disputed_facts: List[KeyFact] = Field(
        default_factory=list,
        description="Facts that are disputed"
    )
    
    # Summary
    executive_summary: Optional[str] = Field(
        None,
        description="Executive summary of key facts"
    )
    main_issues: List[str] = Field(
        default_factory=list,
        description="Main issues identified from facts"
    )
    
    # Financial summary
    total_claimed_amount: Optional[float] = Field(
        None,
        description="Total claimed amount from facts"
    )
    currency: Optional[str] = Field(None, description="Currency for amounts")
    
    # Relationships
    fact_chain: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Chain of related facts showing causal relationships"
    )
    
    def compute_statistics(self):
        """Compute summary statistics and group facts."""
        self.total_facts = len(self.facts)
        
        # Group by category
        self.facts_by_category = {}
        self.high_importance_facts = []
        self.disputed_facts = []
        total_amount = 0.0
        
        for fact in self.facts:
            category = fact.category
            if category not in self.facts_by_category:
                self.facts_by_category[category] = []
            self.facts_by_category[category].append(fact)
            
            if fact.importance == "high":
                self.high_importance_facts.append(fact)
            
            if fact.is_disputed:
                self.disputed_facts.append(fact)
            
            if fact.amount:
                total_amount += fact.amount
                if not self.currency and fact.currency:
                    self.currency = fact.currency
        
        if total_amount > 0:
            self.total_claimed_amount = total_amount

