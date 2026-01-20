"""Cost Tracking Middleware for token-level cost tracking

Tracks token usage and calculates costs for each LLM call across agents.
"""
from typing import Dict, Any, Optional, List
from app.services.langchain_agents.state import AnalysisState
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


# Pricing per 1K tokens (input/output) for different models
# Prices in USD (approximate, should be updated with actual pricing)
PRICING_PER_1K_TOKENS = {
    "gigachat-pro": {"input": 0.001, "output": 0.002},  # $0.001/$0.002 per 1K tokens
    "gigachat-lite": {"input": 0.0005, "output": 0.001},  # $0.0005/$0.001 per 1K tokens
    "gigachat": {"input": 0.001, "output": 0.002},  # Default to pro pricing
    # Add other models as needed
}

# Default pricing if model not found
DEFAULT_PRICING = {"input": 0.001, "output": 0.002}


class CostTrackingMiddleware:
    """
    Middleware для отслеживания расходов токенов по агентам.
    
    Перехватывает вызовы LLM и записывает стоимость каждого вызова.
    Интегрируется с MetricsCollector для агрегации.
    """
    
    def __init__(self, enable_tracking: bool = True):
        """
        Initialize cost tracking middleware.
        
        Args:
            enable_tracking: Enable cost tracking (default: True)
        """
        self.enable_tracking = enable_tracking
        self.pricing = PRICING_PER_1K_TOKENS.copy()
    
    def get_model_pricing(self, model_name: str) -> Dict[str, float]:
        """
        Get pricing for a specific model.
        
        Args:
            model_name: Name of the model
        
        Returns:
            Dictionary with input and output pricing per 1K tokens
        """
        # Normalize model name
        model_key = model_name.lower()
        
        # Check exact match
        if model_key in self.pricing:
            return self.pricing[model_key]
        
        # Check partial match (e.g., "gigachat-pro-v1" -> "gigachat-pro")
        for key, pricing in self.pricing.items():
            if key in model_key or model_key in key:
                return pricing
        
        # Default pricing
        logger.debug(f"Model {model_name} not found in pricing table, using default")
        return DEFAULT_PRICING
    
    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model_name: str
    ) -> float:
        """
        Calculate cost for token usage.
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            model_name: Name of the model used
        
        Returns:
            Total cost in USD
        """
        pricing = self.get_model_pricing(model_name)
        
        input_cost = (input_tokens / 1000.0) * pricing["input"]
        output_cost = (output_tokens / 1000.0) * pricing["output"]
        
        total_cost = input_cost + output_cost
        
        logger.debug(
            f"Cost calculation: {input_tokens} input + {output_tokens} output tokens "
            f"({model_name}) = ${total_cost:.6f}"
        )
        
        return total_cost
    
    def before_llm_call(
        self,
        state: AnalysisState,
        node_name: str,
        model_name: Optional[str] = None
    ) -> AnalysisState:
        """
        Called before LLM call to initialize tracking.
        
        Args:
            state: Current graph state
            node_name: Name of the node/agent
            model_name: Optional model name
        
        Returns:
            Updated state with tracking initialization
        """
        if not self.enable_tracking:
            return state
        
        # Initialize cost tracking in metadata if not present
        new_state = dict(state)
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        
        if "cost_tracking" not in new_state["metadata"]:
            new_state["metadata"]["cost_tracking"] = {}
        
        if node_name not in new_state["metadata"]["cost_tracking"]:
            new_state["metadata"]["cost_tracking"][node_name] = {
                "calls": [],
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "model": model_name or "unknown"
            }
        
        # Record start of call
        call_id = f"{node_name}_{int(time.time() * 1000)}"
        new_state["metadata"]["cost_tracking"][node_name]["current_call"] = {
            "call_id": call_id,
            "start_time": time.time(),
            "model": model_name or "unknown"
        }
        
        return new_state
    
    def after_llm_call(
        self,
        state: AnalysisState,
        node_name: str,
        response: Any,
        model_name: Optional[str] = None
    ) -> AnalysisState:
        """
        Called after LLM call to record usage and calculate cost.
        
        Args:
            state: Current graph state
            node_name: Name of the node/agent
            response: LLM response object
            model_name: Optional model name (extracted from response if not provided)
        
        Returns:
            Updated state with cost tracking
        """
        if not self.enable_tracking:
            return state
        
        new_state = dict(state)
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        if "cost_tracking" not in new_state["metadata"]:
            new_state["metadata"]["cost_tracking"] = {}
        if node_name not in new_state["metadata"]["cost_tracking"]:
            new_state["metadata"]["cost_tracking"][node_name] = {
                "calls": [],
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "model": model_name or "unknown"
            }
        
        tracking = new_state["metadata"]["cost_tracking"][node_name]
        current_call = tracking.get("current_call", {})
        
        # Extract token usage from response
        input_tokens = 0
        output_tokens = 0
        
        # Try different ways to extract usage metadata
        usage_metadata = None
        if hasattr(response, 'response_metadata'):
            usage_metadata = response.response_metadata
        elif hasattr(response, 'usage_metadata'):
            usage_metadata = response.usage_metadata
        elif isinstance(response, dict):
            usage_metadata = response.get("usage_metadata") or response.get("response_metadata")
        
        if usage_metadata:
            input_tokens = usage_metadata.get("input_tokens", 0) or usage_metadata.get("prompt_tokens", 0)
            output_tokens = usage_metadata.get("output_tokens", 0) or usage_metadata.get("completion_tokens", 0)
        
        # If not found, try LLMResult format
        if input_tokens == 0 and output_tokens == 0:
            if hasattr(response, 'llm_output') and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                if isinstance(token_usage, dict):
                    input_tokens = token_usage.get("prompt_tokens", 0)
                    output_tokens = token_usage.get("completion_tokens", 0)
        
        # Extract model name if not provided
        if not model_name:
            if usage_metadata and "model" in usage_metadata:
                model_name = usage_metadata["model"]
            elif hasattr(response, 'response_metadata') and hasattr(response.response_metadata, 'get'):
                model_name = response.response_metadata.get("model")
            else:
                model_name = tracking.get("model", "unknown")
        
        # Calculate cost
        cost = self.calculate_cost(input_tokens, output_tokens, model_name)
        
        # Record call
        call_record = {
            "call_id": current_call.get("call_id", f"{node_name}_{int(time.time() * 1000)}"),
            "timestamp": datetime.now().isoformat(),
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost": cost,
            "duration": time.time() - current_call.get("start_time", time.time())
        }
        
        tracking["calls"].append(call_record)
        tracking["total_cost"] += cost
        tracking["total_input_tokens"] += input_tokens
        tracking["total_output_tokens"] += output_tokens
        tracking["total_tokens"] = tracking["total_input_tokens"] + tracking["total_output_tokens"]
        tracking["model"] = model_name
        
        # Clean up current_call
        if "current_call" in tracking:
            del tracking["current_call"]
        
        logger.debug(
            f"[CostTracking] {node_name}: {input_tokens + output_tokens} tokens, "
            f"${cost:.6f} ({model_name})"
        )
        
        return new_state
    
    def get_cost_summary(self, state: AnalysisState) -> Dict[str, Any]:
        """
        Get cost summary for all agents in the state.
        
        Args:
            state: Current graph state
        
        Returns:
            Dictionary with cost summary per agent and total
        """
        if not self.enable_tracking:
            return {}
        
        cost_tracking = state.get("metadata", {}).get("cost_tracking", {})
        
        summary = {
            "agents": {},
            "total_cost": 0.0,
            "total_tokens": 0,
            "total_calls": 0
        }
        
        for agent_name, tracking in cost_tracking.items():
            agent_summary = {
                "cost": tracking.get("total_cost", 0.0),
                "input_tokens": tracking.get("total_input_tokens", 0),
                "output_tokens": tracking.get("total_output_tokens", 0),
                "total_tokens": tracking.get("total_tokens", 0),
                "calls": len(tracking.get("calls", [])),
                "model": tracking.get("model", "unknown")
            }
            summary["agents"][agent_name] = agent_summary
            summary["total_cost"] += agent_summary["cost"]
            summary["total_tokens"] += agent_summary["total_tokens"]
            summary["total_calls"] += agent_summary["calls"]
        
        return summary
































