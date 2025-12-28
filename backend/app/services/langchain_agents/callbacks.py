"""Custom callback handlers for LangChain chains"""
from langchain_core.callbacks import BaseCallbackHandler
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class AnalysisCallbackHandler(BaseCallbackHandler):
    """Custom callback handler for analysis chains"""
    
    def __init__(self, agent_name: str = "unknown"):
        """
        Initialize callback handler
        
        Args:
            agent_name: Name of the agent using this callback
        """
        super().__init__()
        self.agent_name = agent_name
    
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts"""
        logger.debug(f"[{self.agent_name}] Chain started: {serialized.get('name', 'unknown')}")
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain ends"""
        logger.debug(f"[{self.agent_name}] Chain ended successfully")
    
    def on_chain_error(self, error: Exception, **kwargs) -> None:
        """Called when a chain encounters an error"""
        logger.error(f"[{self.agent_name}] Chain error: {error}", exc_info=True)
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts"""
        logger.debug(f"[{self.agent_name}] LLM started, prompts: {len(prompts)}")
    
    def on_llm_end(self, response: Any, **kwargs) -> None:
        """Called when LLM ends"""
        logger.debug(f"[{self.agent_name}] LLM ended successfully")
    
    def on_llm_error(self, error: Exception, **kwargs) -> None:
        """Called when LLM encounters an error"""
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
        tool_name = serialized.get('name', 'unknown')
        logger.debug(f"[{self.agent_name}] Tool started: {tool_name}")
    
    def on_tool_end(self, output: str, **kwargs) -> None:
        """Called when a tool ends"""
        logger.debug(f"[{self.agent_name}] Tool ended successfully")
    
    def on_tool_error(self, error: Exception, **kwargs) -> None:
        """Called when a tool encounters an error"""
        logger.error(f"[{self.agent_name}] Tool error: {error}", exc_info=True)



