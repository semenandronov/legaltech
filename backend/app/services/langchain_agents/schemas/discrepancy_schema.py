"""Discrepancy Schema - Phase 2.1 Implementation

Schema for discrepancy detection agent outputs.
Supports contradictions, inconsistencies, and conflicts in documents.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class DiscrepancySeverity(str, Enum):
    """Severity levels for discrepancies."""
    CRITICAL = "critical"  # Критическое противоречие
    HIGH = "high"  # Серьезное противоречие
    MEDIUM = "medium"  # Умеренное противоречие
    LOW = "low"  # Незначительное расхождение
    INFO = "info"  # Информационное (требует внимания)


class DiscrepancyType(str, Enum):
    """Types of discrepancies."""
    DATE_CONFLICT = "date_conflict"  # Конфликт дат
    AMOUNT_MISMATCH = "amount_mismatch"  # Расхождение сумм
    PARTY_INCONSISTENCY = "party_inconsistency"  # Несоответствие сторон
    STATEMENT_CONTRADICTION = "statement_contradiction"  # Противоречие в показаниях
    DOCUMENT_CONFLICT = "document_conflict"  # Конфликт документов
    LEGAL_INCONSISTENCY = "legal_inconsistency"  # Правовое несоответствие
    PROCEDURAL_ERROR = "procedural_error"  # Процессуальная ошибка
    FACTUAL_DISCREPANCY = "factual_discrepancy"  # Фактическое расхождение
    SIGNATURE_ISSUE = "signature_issue"  # Проблема с подписью
    MISSING_ELEMENT = "missing_element"  # Отсутствующий элемент
    OTHER = "other"


class Discrepancy(BaseModel):
    """A single discrepancy or contradiction found."""
    
    discrepancy_id: Optional[str] = Field(None, description="Unique discrepancy identifier")
    discrepancy_type: DiscrepancyType = Field(DiscrepancyType.OTHER, description="Type of discrepancy")
    severity: DiscrepancySeverity = Field(DiscrepancySeverity.MEDIUM, description="Severity level")
    
    # Description
    title: str = Field(..., description="Short title of discrepancy", max_length=200)
    description: str = Field(..., description="Detailed description", max_length=2000)
    
    # Conflicting elements
    element_a: str = Field(..., description="First conflicting element")
    element_b: str = Field(..., description="Second conflicting element")
    source_a: Optional[SourceReference] = Field(None, description="Source of element A")
    source_b: Optional[SourceReference] = Field(None, description="Source of element B")
    
    # For date conflicts
    date_a: Optional[str] = Field(None, description="First date (for date conflicts)")
    date_b: Optional[str] = Field(None, description="Second date (for date conflicts)")
    
    # For amount mismatches
    amount_a: Optional[float] = Field(None, description="First amount")
    amount_b: Optional[float] = Field(None, description="Second amount")
    amount_difference: Optional[float] = Field(None, description="Difference between amounts")
    currency: Optional[str] = Field(None, description="Currency for amounts")
    
    # Context
    context: Optional[str] = Field(None, description="Context of discrepancy", max_length=500)
    parties_involved: List[str] = Field(default_factory=list, description="Parties involved")
    
    # Impact assessment
    legal_impact: Optional[str] = Field(None, description="Legal impact of discrepancy")
    case_impact: Optional[str] = Field(None, description="Impact on case outcome")
    requires_resolution: bool = Field(True, description="Whether resolution is needed")
    
    # Resolution
    resolution_suggestion: Optional[str] = Field(None, description="Suggested resolution")
    additional_investigation: Optional[str] = Field(None, description="Additional investigation needed")
    
    # Metadata
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence in finding")
    sources: List[SourceReference] = Field(default_factory=list, description="All source references")
    
    class Config:
        extra = "allow"
        use_enum_values = True


class DiscrepancyResult(BaseAgentOutput):
    """Full output from the discrepancy detection agent."""
    
    agent_name: str = Field(default="discrepancy", description="Agent name")
    
    # All discrepancies found
    discrepancies: List[Discrepancy] = Field(
        default_factory=list,
        description="All discrepancies found"
    )
    total_discrepancies: int = Field(0, description="Total count")
    
    # Grouped by severity
    critical_discrepancies: List[Discrepancy] = Field(default_factory=list)
    high_severity: List[Discrepancy] = Field(default_factory=list)
    medium_severity: List[Discrepancy] = Field(default_factory=list)
    low_severity: List[Discrepancy] = Field(default_factory=list)
    
    # Grouped by type
    discrepancies_by_type: Dict[str, List[Discrepancy]] = Field(
        default_factory=dict,
        description="Discrepancies grouped by type"
    )
    
    # Summary
    summary: Optional[str] = Field(
        None,
        description="Executive summary of discrepancies"
    )
    key_issues: List[str] = Field(
        default_factory=list,
        description="Key issues identified"
    )
    
    # Impact assessment
    overall_severity: DiscrepancySeverity = Field(
        DiscrepancySeverity.LOW,
        description="Overall severity assessment"
    )
    case_impact_summary: Optional[str] = Field(
        None,
        description="Summary of impact on case"
    )
    
    # Recommendations
    priority_actions: List[str] = Field(
        default_factory=list,
        description="Priority actions to take"
    )
    investigation_needed: List[str] = Field(
        default_factory=list,
        description="Areas requiring investigation"
    )
    
    def compute_statistics(self):
        """Compute summary statistics and group discrepancies."""
        self.total_discrepancies = len(self.discrepancies)
        
        # Group by severity
        self.critical_discrepancies = []
        self.high_severity = []
        self.medium_severity = []
        self.low_severity = []
        self.discrepancies_by_type = {}
        
        max_severity = DiscrepancySeverity.LOW
        severity_order = {
            DiscrepancySeverity.CRITICAL: 4,
            DiscrepancySeverity.HIGH: 3,
            DiscrepancySeverity.MEDIUM: 2,
            DiscrepancySeverity.LOW: 1,
            DiscrepancySeverity.INFO: 0
        }
        
        for disc in self.discrepancies:
            # Group by severity
            if disc.severity == DiscrepancySeverity.CRITICAL:
                self.critical_discrepancies.append(disc)
            elif disc.severity == DiscrepancySeverity.HIGH:
                self.high_severity.append(disc)
            elif disc.severity == DiscrepancySeverity.MEDIUM:
                self.medium_severity.append(disc)
            else:
                self.low_severity.append(disc)
            
            # Track max severity
            if severity_order.get(disc.severity, 0) > severity_order.get(max_severity, 0):
                max_severity = disc.severity
            
            # Group by type
            disc_type = disc.discrepancy_type
            if disc_type not in self.discrepancies_by_type:
                self.discrepancies_by_type[disc_type] = []
            self.discrepancies_by_type[disc_type].append(disc)
        
        self.overall_severity = max_severity

