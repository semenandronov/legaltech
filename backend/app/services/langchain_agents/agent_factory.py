"""Factory для создания агентов с обратной совместимостью"""
from langchain_openai import ChatOpenAI
from typing import List, Any, Optional
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
