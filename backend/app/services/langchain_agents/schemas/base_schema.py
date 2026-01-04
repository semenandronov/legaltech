"""Base Schema for Agent Outputs - Phase 2.1 Implementation

Provides common base classes and utilities for all agent output schemas.
"""
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Confidence(str, Enum):
    """Confidence level for extracted information."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


class SourceReference(BaseModel):
    """Reference to a source document or passage."""
    
    document_id: Optional[str] = Field(None, description="ID of the source document")
    document_name: Optional[str] = Field(None, description="Name of the source file")
    page: Optional[int] = Field(None, description="Page number in document")
    paragraph: Optional[int] = Field(None, description="Paragraph number")
    start_char: Optional[int] = Field(None, description="Start character position")
    end_char: Optional[int] = Field(None, description="End character position")
    quote: Optional[str] = Field(None, description="Exact quote from source", max_length=500)
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Relevance score")
    
    class Config:
        extra = "allow"


class BaseAgentOutput(BaseModel):
    """Base class for all agent outputs."""
    
    agent_name: str = Field(..., description="Name of the agent that produced this output")
    case_id: str = Field(..., description="ID of the case being analyzed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the output was generated")
    processing_time_seconds: Optional[float] = Field(None, description="Time taken to produce output")
    confidence: Confidence = Field(Confidence.MEDIUM, description="Overall confidence in the output")
    sources: List[SourceReference] = Field(default_factory=list, description="Source references")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        extra = "allow"
        use_enum_values = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        data = self.dict()
        # Convert datetime to ISO string
        if isinstance(data.get('timestamp'), datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseAgentOutput":
        """Create from dictionary."""
        # Parse timestamp if string
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


def validate_agent_output(
    output: Union[Dict[str, Any], BaseAgentOutput],
    schema_class: type,
    strict: bool = False
) -> tuple:
    """
    Validate agent output against a Pydantic schema.
    
    Args:
        output: The output to validate (dict or BaseAgentOutput)
        schema_class: The Pydantic model class to validate against
        strict: If True, raise on validation errors; if False, return errors
        
    Returns:
        Tuple of (validated_output, errors)
        - validated_output: Parsed model instance or None if validation failed
        - errors: List of validation error messages
    """
    errors = []
    
    try:
        if isinstance(output, BaseAgentOutput):
            output = output.dict()
        
        validated = schema_class(**output)
        return validated, errors
        
    except Exception as e:
        error_msg = str(e)
        errors.append(error_msg)
        logger.warning(f"Schema validation failed for {schema_class.__name__}: {error_msg}")
        
        if strict:
            raise ValueError(f"Schema validation failed: {error_msg}")
        
        return None, errors


def create_partial_output(
    schema_class: type,
    data: Dict[str, Any],
    defaults: Optional[Dict[str, Any]] = None
) -> BaseAgentOutput:
    """
    Create a partial output with defaults for missing fields.
    
    Useful when agent output is incomplete but we want to
    preserve what was extracted.
    
    Args:
        schema_class: The Pydantic model class
        data: The partial data
        defaults: Default values for missing fields
        
    Returns:
        Model instance with defaults applied
    """
    defaults = defaults or {}
    
    # Get schema fields and their defaults
    schema_fields = schema_class.__fields__
    
    # Apply defaults for missing fields
    for field_name, field in schema_fields.items():
        if field_name not in data:
            if field_name in defaults:
                data[field_name] = defaults[field_name]
            elif field.default is not None:
                data[field_name] = field.default
            elif field.default_factory is not None:
                data[field_name] = field.default_factory()
    
    try:
        return schema_class(**data)
    except Exception as e:
        logger.error(f"Failed to create partial output: {e}")
        # Return minimal valid output
        return schema_class(
            agent_name=data.get("agent_name", "unknown"),
            case_id=data.get("case_id", "unknown"),
            errors=[str(e)]
        )

