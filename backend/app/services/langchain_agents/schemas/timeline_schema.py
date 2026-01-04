"""Timeline Schema - Phase 2.1 Implementation

Schema for timeline extraction agent outputs.
Supports events, milestones, deadlines, and temporal relationships.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
from enum import Enum
from datetime import date, datetime
from .base_schema import BaseAgentOutput, SourceReference, Confidence


class TimelineEventType(str, Enum):
    """Types of timeline events."""
    CONTRACT_SIGNING = "contract_signing"  # Подписание договора
    PAYMENT = "payment"  # Платеж
    DELIVERY = "delivery"  # Поставка/передача
    VIOLATION = "violation"  # Нарушение
    CLAIM_FILED = "claim_filed"  # Подача иска
    COURT_HEARING = "court_hearing"  # Судебное заседание
    COURT_DECISION = "court_decision"  # Решение суда
    APPEAL = "appeal"  # Апелляция
    DEADLINE = "deadline"  # Срок/дедлайн
    COMMUNICATION = "communication"  # Переписка/уведомление
    MEETING = "meeting"  # Встреча
    INSPECTION = "inspection"  # Проверка
    REGISTRATION = "registration"  # Регистрация
    TERMINATION = "termination"  # Расторжение
    DISPUTE_START = "dispute_start"  # Начало спора
    SETTLEMENT = "settlement"  # Урегулирование
    ENFORCEMENT = "enforcement"  # Принудительное исполнение
    OTHER = "other"


class TimelineEvent(BaseModel):
    """A single event in the timeline."""
    
    event_id: Optional[str] = Field(None, description="Unique event identifier")
    event_type: TimelineEventType = Field(TimelineEventType.OTHER, description="Type of event")
    
    # Date information
    date: Optional[str] = Field(None, description="Event date (ISO format)")
    date_approximate: bool = Field(False, description="Whether date is approximate")
    date_range_start: Optional[str] = Field(None, description="Start of date range")
    date_range_end: Optional[str] = Field(None, description="End of date range")
    time: Optional[str] = Field(None, description="Time of event if known")
    
    # Event description
    title: str = Field(..., description="Short title of the event", max_length=200)
    description: str = Field(..., description="Detailed description", max_length=2000)
    summary: Optional[str] = Field(None, description="Brief summary", max_length=300)
    
    # Participants and context
    participants: List[str] = Field(default_factory=list, description="Parties involved")
    location: Optional[str] = Field(None, description="Location of event")
    document_reference: Optional[str] = Field(None, description="Related document")
    
    # Legal significance
    legal_significance: Optional[str] = Field(None, description="Legal importance of event")
    is_deadline: bool = Field(False, description="Whether this is a deadline")
    deadline_type: Optional[str] = Field(None, description="Type of deadline")
    
    # Amounts and values
    amount: Optional[float] = Field(None, description="Associated monetary amount")
    currency: Optional[str] = Field(None, description="Currency for amount")
    
    # Metadata
    confidence: Confidence = Field(Confidence.MEDIUM, description="Confidence in extraction")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    
    # Relationships
    related_events: List[str] = Field(default_factory=list, description="IDs of related events")
    caused_by: Optional[str] = Field(None, description="ID of event that caused this one")
    leads_to: List[str] = Field(default_factory=list, description="IDs of resulting events")
    
    class Config:
        extra = "allow"
        use_enum_values = True
    
    @validator('date', 'date_range_start', 'date_range_end', pre=True)
    def parse_date(cls, v):
        """Parse and validate date strings."""
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v).strip()


class TimelineResult(BaseAgentOutput):
    """Full output from the timeline extraction agent."""
    
    agent_name: str = Field(default="timeline", description="Agent name")
    
    # All events sorted by date
    events: List[TimelineEvent] = Field(default_factory=list, description="Timeline events")
    total_events: int = Field(0, description="Total number of events")
    
    # Key dates
    earliest_date: Optional[str] = Field(None, description="Earliest date in timeline")
    latest_date: Optional[str] = Field(None, description="Latest date in timeline")
    key_dates: List[str] = Field(default_factory=list, description="Most significant dates")
    
    # Grouped events
    events_by_type: Dict[str, List[TimelineEvent]] = Field(
        default_factory=dict,
        description="Events grouped by type"
    )
    deadlines: List[TimelineEvent] = Field(default_factory=list, description="Deadline events")
    court_events: List[TimelineEvent] = Field(default_factory=list, description="Court-related events")
    
    # Narrative summary
    narrative: Optional[str] = Field(None, description="Narrative summary of timeline")
    key_milestones: List[str] = Field(default_factory=list, description="Key milestones summary")
    
    # Gaps and issues
    timeline_gaps: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Gaps or missing information in timeline"
    )
    conflicting_dates: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Conflicting date information found"
    )
    
    def compute_statistics(self):
        """Compute summary statistics and group events."""
        self.total_events = len(self.events)
        
        # Sort events by date
        def get_sort_key(event):
            if event.date:
                return event.date
            if event.date_range_start:
                return event.date_range_start
            return "9999-99-99"  # Events without dates at end
        
        self.events.sort(key=get_sort_key)
        
        # Find date range
        dated_events = [e for e in self.events if e.date or e.date_range_start]
        if dated_events:
            self.earliest_date = get_sort_key(dated_events[0])
            self.latest_date = get_sort_key(dated_events[-1])
        
        # Group by type
        self.events_by_type = {}
        self.deadlines = []
        self.court_events = []
        
        court_types = {
            TimelineEventType.CLAIM_FILED,
            TimelineEventType.COURT_HEARING,
            TimelineEventType.COURT_DECISION,
            TimelineEventType.APPEAL
        }
        
        for event in self.events:
            event_type = event.event_type
            if event_type not in self.events_by_type:
                self.events_by_type[event_type] = []
            self.events_by_type[event_type].append(event)
            
            if event.is_deadline:
                self.deadlines.append(event)
            
            if event_type in court_types:
                self.court_events.append(event)

