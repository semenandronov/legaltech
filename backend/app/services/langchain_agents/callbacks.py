"""Custom callback handlers for LangChain chains"""
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List, Optional
import logging
import time

logger = logging.getLogger(__name__)


class AnalysisCallbackHandler(BaseCallbackHandler):
    """Custom callback handler for analysis chains with metrics collection"""
    
    def __init__(self, agent_name: str = "unknown"):
        """
        Initialize callback handler
        
        Args:
            agent_name: Name of the agent using this callback
        """
        super().__init__()
        self.agent_name = agent_name
        
        # Metrics tracking
        self.llm_calls: int = 0
        self.tool_calls: int = 0
        self.tokens_used: int = 0
        self.errors: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.tool_names: List[str] = []  # Track which tools were used
    
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts"""
        if serialized is None:
            serialized = {}
        if self.start_time is None:
            self.start_time = time.time()
        logger.debug(f"[{self.agent_name}] Chain started: {serialized.get('name', 'unknown')}")
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain ends"""
        if self.end_time is None:
            self.end_time = time.time()
        logger.debug(f"[{self.agent_name}] Chain ended successfully")
    
    def on_chain_error(self, error: Exception, **kwargs) -> None:
        """Called when a chain encounters an error"""
        logger.error(f"[{self.agent_name}] Chain error: {error}", exc_info=True)
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts"""
        self.llm_calls += 1
        logger.debug(f"[{self.agent_name}] LLM started, prompts: {len(prompts)}")
    
    def on_llm_end(self, response: Any, **kwargs) -> None:
        """Called when LLM ends - collect token usage"""
        logger.debug(f"[{self.agent_name}] LLM ended successfully")
        
        # Extract token usage from response
        try:
            if isinstance(response, LLMResult):
                if response.llm_output and "token_usage" in response.llm_output:
                    token_usage = response.llm_output["token_usage"]
                    # Token usage can be a dict with keys like "prompt_tokens", "completion_tokens", "total_tokens"
                    if isinstance(token_usage, dict):
                        total = token_usage.get("total_tokens", 0)
                        if total:
                            self.tokens_used += total
                    elif isinstance(token_usage, (int, float)):
                        self.tokens_used += int(token_usage)
            elif hasattr(response, 'llm_output'):
                # Try to get token usage from response object
                if hasattr(response.llm_output, 'get'):
                    token_usage = response.llm_output.get("token_usage", {})
                    if isinstance(token_usage, dict):
                        total = token_usage.get("total_tokens", 0)
                        if total:
                            self.tokens_used += total
        except Exception as e:
            logger.debug(f"Could not extract token usage: {e}")
    
    def on_llm_error(self, error: Exception, **kwargs) -> None:
        """Called when LLM encounters an error"""
        self.errors.append({
            "type": "llm_error",
            "error_type": type(error).__name__,
            "message": str(error),
            "timestamp": time.time()
        })
        logger.error(f"[{self.agent_name}] LLM error: {error}", exc_info=True)
    
    def on_parser_start(self, serialized: Dict[str, Any], **kwargs) -> None:
        """Called when parser starts"""
        logger.debug(f"[{self.agent_name}] Parser started")
    
    def on_parser_end(self, parsed: Any, **kwargs) -> None:
        """Called when parser ends"""
        logger.debug(f"[{self.agent_name}] Parser ended successfully")
    
    def on_parser_error(self, error: Exception, **kwargs) -> None:
        """Called when parser encounters an error"""
        logger.warning(f"[{self.agent_name}] Parser error: {error}")
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Called when a tool starts"""
        if serialized is None:
            serialized = {}
        tool_name = serialized.get('name', 'unknown')
        self.tool_calls += 1
        if tool_name not in self.tool_names:
            self.tool_names.append(tool_name)
        logger.debug(f"[{self.agent_name}] Tool started: {tool_name}")
    
    def on_tool_end(self, output: str, **kwargs) -> None:
        """Called when a tool ends"""
        logger.debug(f"[{self.agent_name}] Tool ended successfully")
    
    def on_tool_error(self, error: Exception, **kwargs) -> None:
        """Called when a tool encounters an error"""
        self.errors.append({
            "type": "tool_error",
            "error_type": type(error).__name__,
            "message": str(error),
            "timestamp": time.time()
        })
        logger.error(f"[{self.agent_name}] Tool error: {error}", exc_info=True)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get all collected metrics
        
        Returns:
            Dictionary with metrics
        """
        execution_time = None
        if self.start_time and self.end_time:
            execution_time = self.end_time - self.start_time
        elif self.start_time:
            execution_time = time.time() - self.start_time
        
        return {
            "agent_name": self.agent_name,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tokens_used": self.tokens_used,
            "errors": self.errors,
            "error_count": len(self.errors),
            "execution_time": execution_time,
            "tools_used": list(set(self.tool_names)),  # Unique tools
            "start_time": self.start_time,
            "end_time": self.end_time
        }
    
    def reset(self):
        """Reset all metrics"""
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_used = 0
        self.errors = []
        self.start_time = None
        self.end_time = None
        self.tool_names = []









