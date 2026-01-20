"""Agent Results Schema Mapping

Provides mapping from agent names to their Pydantic result schemas
for use with StructuredOutputHandler.

This module maps agent names to their output schema classes,
enabling automatic schema-based parsing and validation.
"""
from typing import Dict, Type, Optional
from pydantic import BaseModel

# Import all result schemas
from .timeline_schema import TimelineResult
from .key_facts_schema import KeyFactsResult
from .entity_schema import EntityExtractionOutput, EntityResult
from .discrepancy_schema import DiscrepancyResult
from .risk_schema import RiskResult
from .summary_schema import SummaryResult
from .base_schema import BaseAgentOutput

# Mapping from agent name to result schema class
AGENT_RESULT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "timeline": TimelineResult,
    "key_facts": KeyFactsResult,
    "entity_extraction": EntityExtractionOutput,
    "discrepancy": DiscrepancyResult,
    "risk": RiskResult,
    "summary": SummaryResult,
    # Document classifier and privilege check might not have specific schemas
    # Add them if they exist
}

# Mapping for backward compatibility (agent name aliases)
AGENT_ALIASES: Dict[str, str] = {
    "entities": "entity_extraction",
    "document_classifier": "document_classifier",  # Add schema when available
    "privilege_check": "privilege_check",  # Add schema when available
    "relationship": "relationship",  # Add schema when available
}


def get_agent_schema(agent_name: str) -> Optional[Type[BaseModel]]:
    """
    Get Pydantic schema class for an agent.
    
    Args:
        agent_name: Name of the agent (e.g., "timeline", "key_facts")
    
    Returns:
        Pydantic model class for the agent's output, or None if not found
    """
    # Check direct mapping
    if agent_name in AGENT_RESULT_SCHEMAS:
        return AGENT_RESULT_SCHEMAS[agent_name]
    
    # Check aliases
    if agent_name in AGENT_ALIASES:
        alias_name = AGENT_ALIASES[agent_name]
        return AGENT_RESULT_SCHEMAS.get(alias_name)
    
    return None


def has_schema(agent_name: str) -> bool:
    """
    Check if an agent has a defined output schema.
    
    Args:
        agent_name: Name of the agent
    
    Returns:
        True if schema exists, False otherwise
    """
    return get_agent_schema(agent_name) is not None


def register_agent_schema(agent_name: str, schema_class: Type[BaseModel]) -> None:
    """
    Register a schema for an agent (for extensibility).
    
    Args:
        agent_name: Name of the agent
        schema_class: Pydantic model class for the agent's output
    """
    AGENT_RESULT_SCHEMAS[agent_name] = schema_class


__all__ = [
    "AGENT_RESULT_SCHEMAS",
    "AGENT_ALIASES",
    "get_agent_schema",
    "has_schema",
    "register_agent_schema",
    # Re-export commonly used schemas
    "TimelineResult",
    "KeyFactsResult",
    "EntityExtractionOutput",
    "EntityResult",
    "DiscrepancyResult",
    "RiskResult",
    "SummaryResult",
]




























