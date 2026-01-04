"""Risk Assessment Schema - Phase 2.1 Implementation

Schema for risk assessment agent outputs.
Supports legal, financial, procedural, and other risk categories.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class RiskLevel(str, Enum):
    """Risk severity levels."""
    CRITICAL = "critical"  # Критический риск
    HIGH = "high"  # Высокий риск
    MEDIUM = "medium"  # Средний риск
    LOW = "low"  # Низкий риск
    MINIMAL = "minimal"  # Минимальный риск


class RiskCategory(str, Enum):
    """Categories of legal risks."""
    LEGAL = "legal"  # Правовой риск
    FINANCIAL = "financial"  # Финансовый риск
    PROCEDURAL = "procedural"  # Процессуальный риск
    EVIDENTIARY = "evidentiary"  # Доказательственный риск
    REPUTATIONAL = "reputational"  # Репутационный риск
    COMPLIANCE = "compliance"  # Риск несоответствия
    CONTRACTUAL = "contractual"  # Договорной риск
    STATUTE_OF_LIMITATIONS = "statute_of_limitations"  # Риск истечения срока давности
    ENFORCEMENT = "enforcement"  # Риск исполнения решения
    JURISDICTIONAL = "jurisdictional"  # Юрисдикционный риск
    OTHER = "other"


class Risk(BaseModel):
    """A single identified risk."""
    
    risk_id: Optional[str] = Field(None, description="Unique risk identifier")
    category: RiskCategory = Field(RiskCategory.OTHER, description="Risk category")
    level: RiskLevel = Field(RiskLevel.MEDIUM, description="Risk level")
    
    # Description
    title: str = Field(..., description="Short title of risk", max_length=200)
    description: str = Field(..., description="Detailed description", max_length=2000)
    
    # Impact
    probability: Optional[float] = Field(
        None, 
        ge=0.0, 
        le=1.0,
        description="Probability of risk materializing (0-1)"
    )
    impact_description: Optional[str] = Field(None, description="Description of potential impact")
    financial_impact: Optional[float] = Field(None, description="Estimated financial impact")
    currency: Optional[str] = Field(None, description="Currency for financial impact")
    
    # Legal basis
    legal_basis: Optional[str] = Field(None, description="Legal basis for risk")
    relevant_laws: List[str] = Field(default_factory=list, description="Relevant laws/regulations")
    case_law_references: List[str] = Field(default_factory=list, description="Relevant case law")
    
    # Trigger and timeline
    trigger_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions that would trigger risk"
    )
    timeline: Optional[str] = Field(None, description="When risk may materialize")
    deadline: Optional[str] = Field(None, description="Relevant deadline")
    
    # Affected parties
    affected_parties: List[str] = Field(default_factory=list, description="Parties affected")
    responsible_party: Optional[str] = Field(None, description="Party responsible for risk")
    
    # Mitigation
    mitigation_strategies: List[str] = Field(
        default_factory=list,
        description="Strategies to mitigate risk"
    )
    mitigation_cost: Optional[float] = Field(None, description="Estimated cost to mitigate")
    mitigation_timeline: Optional[str] = Field(None, description="Time to implement mitigation")
    
    # Current status
    current_status: Optional[str] = Field(None, description="Current status of risk")
    actions_taken: List[str] = Field(default_factory=list, description="Actions already taken")
    
    # Metadata
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence in assessment")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    
    # Relations
    related_risks: List[str] = Field(default_factory=list, description="IDs of related risks")
    dependent_on: List[str] = Field(default_factory=list, description="Risk dependencies")
    
    class Config:
        extra = "allow"
        use_enum_values = True
    
    def compute_risk_score(self) -> float:
        """Compute a numerical risk score."""
        level_scores = {
            RiskLevel.CRITICAL: 1.0,
            RiskLevel.HIGH: 0.8,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.LOW: 0.3,
            RiskLevel.MINIMAL: 0.1
        }
        
        base_score = level_scores.get(self.level, 0.5)
        
        if self.probability is not None:
            return base_score * self.probability
        
        return base_score


class RiskResult(BaseAgentOutput):
    """Full output from the risk assessment agent."""
    
    agent_name: str = Field(default="risk", description="Agent name")
    
    # All identified risks
    risks: List[Risk] = Field(default_factory=list, description="All identified risks")
    total_risks: int = Field(0, description="Total count")
    
    # Grouped by level
    critical_risks: List[Risk] = Field(default_factory=list)
    high_risks: List[Risk] = Field(default_factory=list)
    medium_risks: List[Risk] = Field(default_factory=list)
    low_risks: List[Risk] = Field(default_factory=list)
    
    # Grouped by category
    risks_by_category: Dict[str, List[Risk]] = Field(
        default_factory=dict,
        description="Risks grouped by category"
    )
    
    # Overall assessment
    overall_risk_level: RiskLevel = Field(
        RiskLevel.LOW,
        description="Overall risk assessment"
    )
    overall_risk_score: float = Field(0.0, description="Computed overall risk score (0-1)")
    
    # Summary
    executive_summary: Optional[str] = Field(
        None,
        description="Executive summary of risk assessment"
    )
    key_concerns: List[str] = Field(
        default_factory=list,
        description="Key risk concerns"
    )
    
    # Financial summary
    total_financial_exposure: Optional[float] = Field(
        None,
        description="Total estimated financial exposure"
    )
    currency: Optional[str] = Field(None, description="Currency for amounts")
    
    # Recommendations
    priority_actions: List[str] = Field(
        default_factory=list,
        description="Priority actions to mitigate risks"
    )
    monitoring_recommendations: List[str] = Field(
        default_factory=list,
        description="Recommendations for ongoing monitoring"
    )
    
    # Opportunities
    opportunities: List[str] = Field(
        default_factory=list,
        description="Potential opportunities identified"
    )
    
    def compute_statistics(self):
        """Compute summary statistics and group risks."""
        self.total_risks = len(self.risks)
        
        # Group by level
        self.critical_risks = []
        self.high_risks = []
        self.medium_risks = []
        self.low_risks = []
        self.risks_by_category = {}
        
        level_scores = {
            RiskLevel.CRITICAL: 1.0,
            RiskLevel.HIGH: 0.8,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.LOW: 0.3,
            RiskLevel.MINIMAL: 0.1
        }
        
        max_level = RiskLevel.MINIMAL
        total_score = 0.0
        total_exposure = 0.0
        
        for risk in self.risks:
            # Group by level
            if risk.level == RiskLevel.CRITICAL:
                self.critical_risks.append(risk)
            elif risk.level == RiskLevel.HIGH:
                self.high_risks.append(risk)
            elif risk.level == RiskLevel.MEDIUM:
                self.medium_risks.append(risk)
            else:
                self.low_risks.append(risk)
            
            # Track max level
            if level_scores.get(risk.level, 0) > level_scores.get(max_level, 0):
                max_level = risk.level
            
            # Accumulate scores
            total_score += risk.compute_risk_score()
            
            # Sum financial exposure
            if risk.financial_impact:
                total_exposure += risk.financial_impact
                if not self.currency and risk.currency:
                    self.currency = risk.currency
            
            # Group by category
            category = risk.category
            if category not in self.risks_by_category:
                self.risks_by_category[category] = []
            self.risks_by_category[category].append(risk)
        
        self.overall_risk_level = max_level
        self.overall_risk_score = total_score / len(self.risks) if self.risks else 0.0
        
        if total_exposure > 0:
            self.total_financial_exposure = total_exposure

