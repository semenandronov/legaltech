"""State definition for LangGraph multi-agent analysis system"""
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage


class AnalysisState(TypedDict):
    """State object for the analysis graph"""
    
    # Case identifier
    case_id: str
    
    # Messages for agent communication
    messages: List[BaseMessage]
    
    # Results from each agent
    timeline_result: Optional[Dict[str, Any]]
    key_facts_result: Optional[Dict[str, Any]]
    discrepancy_result: Optional[Dict[str, Any]]
    risk_result: Optional[Dict[str, Any]]
    summary_result: Optional[Dict[str, Any]]
    
    # Analysis types requested
    analysis_types: List[str]
    
    # Errors encountered during execution
    errors: List[Dict[str, Any]]
    
    # Metadata for tracking
    metadata: Dict[str, Any]
