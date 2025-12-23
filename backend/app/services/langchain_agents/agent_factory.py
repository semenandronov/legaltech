"""Factory для создания агентов с обратной совместимостью"""
from langchain_openai import ChatOpenAI
from typing import List, Any, Optional, Dict
from langchain_core.messages import HumanMessage, AIMessage
import logging

logger = logging.getLogger(__name__)


def create_legal_agent(
    llm: ChatOpenAI,
    tools: List[Any],
    system_prompt: Optional[str] = None,
    messages_modifier: Optional[Any] = None
) -> Any:
    """
    Создать агента с поддержкой нового и старого API
    
    Приоритет: новый API (create_agent) > старый API (create_react_agent)
    
    Args:
        llm: LLM instance (ChatOpenAI)
        tools: List of tools for the agent
        system_prompt: System prompt string (новый API)
        messages_modifier: Messages modifier function или prompt (старый API)
    
    Returns:
        Compiled agent graph
    
    Raises:
        ImportError: Если ни один из API недоступен
    """
    # Попробовать новый API из langchain.agents или langchain_core
    try:
        try:
            from langchain.agents import create_agent
        except ImportError:
            # LangChain 1.x - try alternative location
            from langchain_core.agents import create_agent
        prompt = system_prompt or (messages_modifier if isinstance(messages_modifier, str) else None)
        if prompt:
            agent = create_agent(
                model=llm,
                tools=tools,
                system_prompt=prompt
            )
            logger.debug("Using create_agent (LangChain v1.0+)")
            return agent
    except (ImportError, AttributeError, TypeError) as e:
        logger.debug(f"create_agent not available: {e}, trying create_react_agent")
    
    # Fallback на старый API
    try:
        from langgraph.prebuilt import create_react_agent
        modifier = messages_modifier or system_prompt
        agent = create_react_agent(llm, tools, messages_modifier=modifier)
        logger.debug("Using create_react_agent (legacy)")
        return agent
    except ImportError as e:
        raise ImportError(
            f"Neither create_agent nor create_react_agent available. "
            f"Please ensure langchain>=0.1.0 or langgraph>=0.2.0 is installed. Error: {e}"
        )


def safe_agent_invoke(
    agent: Any,
    llm: ChatOpenAI,
    input_data: Dict[str, Any],
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Безопасный вызов агента с fallback на прямой вызов LLM при ошибках tool use
    
    Args:
        agent: Agent instance
        llm: LLM instance for fallback
        input_data: Input data for agent (must contain "messages")
        config: Optional config for agent
        
    Returns:
        Agent result or fallback LLM response
    """
    try:
        agent_config = config or {}
        agent_config.setdefault("recursion_limit", 25)
        result = agent.invoke(input_data, config=agent_config)
        return result
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        
        # Check if error is related to tool use not being supported
        # YandexGPT doesn't support bind_tools(), which raises NotImplementedError
        is_tool_error = (
            error_type == "NotImplementedError" or
            "bind_tools" in error_msg or
            any(keyword in error_msg.lower() for keyword in [
                "tool use", "404", "no endpoints found", "not support", 
                "notimplemented", "function calling", "tools not available"
            ])
        )
        
        if is_tool_error:
            logger.warning(
                f"Model does not support tool use (error: {error_type}: {error_msg[:200]}). "
                "Falling back to direct LLM call without tools."
            )
            # Fallback: use LLM directly without tools
            messages = input_data.get("messages", [])
            if not messages:
                raise ValueError("No messages provided in input_data")
            
            # Get the last user message
            last_message = messages[-1] if messages else None
            if not last_message:
                raise ValueError("No valid message found")
            
            # Create a simple prompt from the message
            if isinstance(last_message, HumanMessage):
                prompt = last_message.content
            elif hasattr(last_message, 'content'):
                prompt = str(last_message.content)
            else:
                prompt = str(last_message)
            
            # Call LLM directly
            response = llm.invoke([HumanMessage(content=prompt)])
            
            # Return in the same format as agent
            return {
                "messages": [response] if response else [],
                "case_id": input_data.get("case_id")
            }
        else:
            # Re-raise if it's a different error
            logger.error(f"Agent invoke error (not tool-related): {error_type}: {error_msg}")
            raise
