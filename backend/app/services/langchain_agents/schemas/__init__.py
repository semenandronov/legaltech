"""Pydantic Schemas for Agent Outputs - Phase 2.1 Implementation

This module provides structured output schemas for all agent types.
Using Pydantic models ensures consistent, validated outputs from agents.

Usage:
    from app.services.langchain_agents.schemas import EntityResult, TimelineResult
"""

from .entity_schema import (
    Entity,
    EntityType,
    EntityResult,
    EntityExtractionOutput
)
from .timeline_schema import (
    TimelineEvent,
    TimelineEventType,
    TimelineResult
)
from .key_facts_schema import (
    KeyFact,
    FactCategory,
    KeyFactsResult
)
from .discrepancy_schema import (
    Discrepancy,
    DiscrepancySeverity,
    DiscrepancyResult
)
from .risk_schema import (
    Risk,
    RiskLevel,
    RiskCategory,
    RiskResult
)
from .summary_schema import (
    SectionSummary,
    CaseSummary,
    SummaryResult
)
from .base_schema import (
    BaseAgentOutput,
    SourceReference,
    Confidence,
    validate_agent_output
)

__all__ = [
    # Base
    "BaseAgentOutput",
    "SourceReference",
    "Confidence",
    "validate_agent_output",
    # Entities
    "Entity",
    "EntityType",
    "EntityResult",
    "EntityExtractionOutput",
    # Timeline
    "TimelineEvent",
    "TimelineEventType",
    "TimelineResult",
    # Key Facts
    "KeyFact",
    "FactCategory",
    "KeyFactsResult",
    # Discrepancies
    "Discrepancy",
    "DiscrepancySeverity",
    "DiscrepancyResult",
    # Risks
    "Risk",
    "RiskLevel",
    "RiskCategory",
    "RiskResult",
    # Summary
    "SectionSummary",
    "CaseSummary",
    "SummaryResult",
]

