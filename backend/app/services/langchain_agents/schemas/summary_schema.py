"""Summary Schema - Phase 2.1 Implementation

Schema for case summary and synthesis agent outputs.
Supports multi-section summaries with key insights.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class SummarySection(str, Enum):
    """Standard sections of a case summary."""
    OVERVIEW = "overview"  # Общий обзор дела
    PARTIES = "parties"  # Стороны дела
    SUBJECT_MATTER = "subject_matter"  # Предмет спора
    CHRONOLOGY = "chronology"  # Хронология событий
    CLAIMS = "claims"  # Требования и претензии
    LEGAL_BASIS = "legal_basis"  # Правовые основания
    EVIDENCE = "evidence"  # Доказательная база
    RISKS = "risks"  # Риски и слабые места
    RECOMMENDATIONS = "recommendations"  # Рекомендации
    CONCLUSION = "conclusion"  # Выводы


class SectionSummary(BaseModel):
    """Summary for a specific section of the case."""
    
    section: SummarySection = Field(..., description="Section type")
    section_title: str = Field(..., description="Section title", max_length=200)
    
    # Content
    content: str = Field(..., description="Section content", max_length=5000)
    key_points: List[str] = Field(default_factory=list, description="Key points of section")
    
    # For parties section
    party_info: Optional[Dict[str, Any]] = Field(None, description="Party information")
    
    # For claims section
    claims_summary: Optional[List[Dict[str, Any]]] = Field(None, description="Claims summary")
    total_claimed: Optional[float] = Field(None, description="Total amount claimed")
    
    # For risks section
    risk_summary: Optional[List[Dict[str, Any]]] = Field(None, description="Risk summary")
    
    # Metadata
    word_count: int = Field(0, description="Word count of content")
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence level")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    
    class Config:
        extra = "allow"
        use_enum_values = True
    
    def compute_word_count(self):
        """Compute word count of content."""
        self.word_count = len(self.content.split())


class CaseSummary(BaseModel):
    """Complete case summary combining all sections."""
    
    # Brief summaries
    one_liner: str = Field(..., description="One-line summary", max_length=200)
    executive_summary: str = Field(..., description="Executive summary", max_length=1000)
    
    # Key metadata
    case_type: Optional[str] = Field(None, description="Type of case")
    jurisdiction: Optional[str] = Field(None, description="Jurisdiction")
    status: Optional[str] = Field(None, description="Current status")
    
    # Parties
    plaintiff: Optional[str] = Field(None, description="Plaintiff/Claimant")
    defendant: Optional[str] = Field(None, description="Defendant/Respondent")
    other_parties: List[str] = Field(default_factory=list, description="Other parties")
    
    # Subject matter
    subject_matter: str = Field(..., description="Subject of dispute", max_length=500)
    main_issues: List[str] = Field(default_factory=list, description="Main legal issues")
    
    # Amounts
    total_claimed: Optional[float] = Field(None, description="Total amount claimed")
    currency: Optional[str] = Field(None, description="Currency")
    
    # Key dates
    filing_date: Optional[str] = Field(None, description="Date case was filed")
    key_dates: List[Dict[str, str]] = Field(default_factory=list, description="Key dates")
    next_deadline: Optional[str] = Field(None, description="Next important deadline")
    
    # Assessment
    strength_assessment: Optional[str] = Field(None, description="Case strength assessment")
    likelihood_of_success: Optional[str] = Field(None, description="Likelihood of success")
    main_risks: List[str] = Field(default_factory=list, description="Main risks")
    main_opportunities: List[str] = Field(default_factory=list, description="Main opportunities")
    
    # Recommendations
    immediate_actions: List[str] = Field(
        default_factory=list,
        description="Immediate actions required"
    )
    strategic_recommendations: List[str] = Field(
        default_factory=list,
        description="Strategic recommendations"
    )


class SummaryResult(BaseAgentOutput):
    """Full output from the summary agent."""
    
    agent_name: str = Field(default="summary", description="Agent name")
    
    # Complete case summary
    case_summary: Optional[CaseSummary] = Field(None, description="Complete case summary")
    
    # Individual sections
    sections: List[SectionSummary] = Field(
        default_factory=list,
        description="Individual section summaries"
    )
    
    # Brief summaries at different lengths
    one_liner: Optional[str] = Field(None, max_length=200)
    short_summary: Optional[str] = Field(None, max_length=500)
    medium_summary: Optional[str] = Field(None, max_length=1500)
    full_summary: Optional[str] = Field(None, max_length=5000)
    
    # Key insights
    key_facts: List[str] = Field(default_factory=list, description="Key facts")
    key_issues: List[str] = Field(default_factory=list, description="Key legal issues")
    key_risks: List[str] = Field(default_factory=list, description="Key risks")
    key_recommendations: List[str] = Field(default_factory=list, description="Key recommendations")
    
    # For lawyer quick reference
    lawyer_brief: Optional[str] = Field(
        None,
        description="Quick brief for lawyer review",
        max_length=2000
    )
    
    # Questions that need answers
    open_questions: List[str] = Field(
        default_factory=list,
        description="Questions requiring clarification"
    )
    
    # Next steps
    next_steps: List[str] = Field(
        default_factory=list,
        description="Recommended next steps"
    )
    
    # Statistics
    total_documents_analyzed: int = Field(0, description="Documents analyzed")
    total_pages: int = Field(0, description="Total pages processed")
    word_count: int = Field(0, description="Total word count of summary")
    
    def compute_statistics(self):
        """Compute summary statistics."""
        total_words = 0
        
        for section in self.sections:
            section.compute_word_count()
            total_words += section.word_count
        
        if self.full_summary:
            total_words += len(self.full_summary.split())
        
        self.word_count = total_words
        
        # Extract key elements from case_summary if available
        if self.case_summary:
            if self.case_summary.main_issues:
                self.key_issues = self.case_summary.main_issues
            if self.case_summary.main_risks:
                self.key_risks = self.case_summary.main_risks
            if self.case_summary.immediate_actions:
                self.next_steps = self.case_summary.immediate_actions

