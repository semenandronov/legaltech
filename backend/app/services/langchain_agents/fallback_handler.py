"""Simplified fallback handler with retry and exponential backoff"""
from typing import Dict, Any, List, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.unified_error_handler import UnifiedErrorHandler, ErrorResult
import logging

logger = logging.getLogger(__name__)


class FallbackResult:
    """Result of fallback handling"""
    def __init__(
        self,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        strategy: str = "none",
        message: str = "",
        partial: bool = False
    ):
        self.success = success
        self.result = result
        self.strategy = strategy
        self.message = message
        self.partial = partial
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "strategy": self.strategy,
            "message": self.message,
            "partial": self.partial
        }


class FallbackHandler:
    """
    Simplified fallback handler with retry and exponential backoff.
    
    Removed alternative agents - they mask real problems.
    Focuses on retry with exponential backoff for transient errors.
    """
    
    def __init__(self, max_retries: int = 3, base_retry_delay: float = 1.0):
        """
        Initialize fallback handler
        
        Args:
            max_retries: Maximum number of retries
            base_retry_delay: Base delay in seconds for exponential backoff
        """
        self.unified_error_handler = UnifiedErrorHandler(
            max_retries=max_retries,
            base_retry_delay=base_retry_delay
        )
    
    def handle_failure(
        self,
        agent_name: str,
        error: Exception,
        state: AnalysisState,
        retry_count: int = 0
    ) -> FallbackResult:
        """
        Handles agent failure using unified error handler
        
        Args:
            agent_name: Name of failed agent
            error: Exception that occurred
            state: Current analysis state
            retry_count: Current retry count
        
        Returns:
            FallbackResult with handling strategy and result
        """
        logger.info(f"Handling failure for {agent_name}: {str(error)[:100]}")
        
        # Use unified error handler
        context = {
            "case_id": state.get("case_id", "unknown"),
            "agent_name": agent_name,
            "state_keys": list(state.keys())
        }
        
        error_result = self.unified_error_handler.handle_agent_error(
            agent_name=agent_name,
            error=error,
            context=context,
            retry_count=retry_count
        )
        
        # Convert ErrorResult to FallbackResult
        return FallbackResult(
            success=error_result.success,
            result=None,  # No result on failure
            strategy=error_result.strategy.value,
            message=error_result.message,
            partial=False
        )
    
    def should_retry(self, error_result: FallbackResult) -> bool:
        """Check if error should be retried based on strategy"""
        return error_result.strategy == "retry"
    
    def get_retry_delay(self, retry_count: int) -> float:
        """Get retry delay with exponential backoff"""
        return self.unified_error_handler.get_retry_delay(retry_count)
    
    def combine_results(
        self,
        results: List[Dict[str, Any]],
        agent_name: str
    ) -> Dict[str, Any]:
        """
        Combines results from multiple sources
        
        Args:
            results: List of result dictionaries
            agent_name: Name of the agent
        
        Returns:
            Combined result dictionary
        """
        if not results:
            return {}
        
        if agent_name == "timeline":
            all_events = []
            for result in results:
                events = result.get("events", [])
                if events:
                    all_events.extend(events)
            # Remove duplicates
            seen = set()
            unique_events = []
            for event in all_events:
                event_key = (event.get("date"), event.get("description"))
                if event_key not in seen:
                    seen.add(event_key)
                    unique_events.append(event)
            return {"events": unique_events, "total_events": len(unique_events)}
        
        elif agent_name == "key_facts":
            all_facts = []
            for result in results:
                facts = result.get("facts", result.get("key_facts", []))
                if facts:
                    all_facts.extend(facts)
            # Remove duplicates
            seen = set()
            unique_facts = []
            for fact in all_facts:
                if isinstance(fact, dict):
                    fact_key = fact.get("value", fact.get("description", ""))
                else:
                    fact_key = str(fact)
                if fact_key not in seen:
                    seen.add(fact_key)
                    unique_facts.append(fact)
            return {"facts": unique_facts, "total_facts": len(unique_facts)}
        
        else:
            # Generic combination: merge all keys
            combined = {}
            for result in results:
                for key, value in result.items():
                    if key not in ["error", "errors"]:
                        if key in combined:
                            if isinstance(combined[key], list) and isinstance(value, list):
                                combined[key].extend(value)
                            elif isinstance(combined[key], dict) and isinstance(value, dict):
                                combined[key].update(value)
                        else:
                            combined[key] = value
            return combined

