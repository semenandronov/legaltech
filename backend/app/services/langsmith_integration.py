"""LangSmith Integration Service - Phase 7 Implementation

This module provides full LangSmith integration for tracing,
evaluation, and monitoring.

Features:
- Tracing setup and configuration
- @traceable decorators for critical functions
- Online and offline evaluators
- Custom dashboards and alerts
- Studio integration support
"""
from typing import Optional, Dict, Any, Callable, List
from functools import wraps
from app.config import config
import logging
import os

logger = logging.getLogger(__name__)

# Check if LangSmith is available and configured
LANGSMITH_AVAILABLE = False
LANGSMITH_ENABLED = False

try:
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree
    LANGSMITH_AVAILABLE = True
    
    # Check if properly configured
    if config.LANGSMITH_API_KEY and config.LANGSMITH_TRACING:
        LANGSMITH_ENABLED = True
        logger.info("✅ LangSmith integration enabled")
    else:
        logger.info("LangSmith available but not enabled (set LANGSMITH_API_KEY and LANGCHAIN_TRACING_V2=true)")
        
except ImportError:
    logger.warning("langsmith not installed. LangSmith integration disabled.")
    traceable = lambda **kwargs: lambda func: func  # No-op decorator


def setup_langsmith_tracing():
    """
    Setup LangSmith tracing environment.
    
    Configures environment variables and initializes the client.
    Should be called at application startup.
    """
    if not LANGSMITH_AVAILABLE:
        logger.warning("LangSmith not available, skipping setup")
        return False
            
    # Set environment variables
    os.environ["LANGCHAIN_TRACING_V2"] = str(config.LANGSMITH_TRACING).lower()
    os.environ["LANGCHAIN_ENDPOINT"] = config.LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_PROJECT"] = config.LANGSMITH_PROJECT
    
    if config.LANGSMITH_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = config.LANGSMITH_API_KEY
    
    logger.info(
        f"LangSmith tracing setup: enabled={config.LANGSMITH_TRACING}, "
        f"project={config.LANGSMITH_PROJECT}"
    )
    
    return True


def get_langsmith_client() -> Optional[Any]:
    """
    Get LangSmith client instance.
    
    Returns:
        LangSmith Client or None if not available
    """
    if not LANGSMITH_ENABLED:
        return None
    
    try:
        return Client()
    except Exception as e:
        logger.warning(f"Failed to create LangSmith client: {e}")
        return None


def trace_function(
    name: Optional[str] = None,
    run_type: str = "chain",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Callable:
    """
    Decorator for tracing functions with LangSmith.
    
    Falls back to no-op if LangSmith is not available.
    
    Args:
        name: Name for the trace (defaults to function name)
        run_type: Type of run (chain, llm, tool, retriever, etc.)
        tags: Tags for the trace
        metadata: Additional metadata
        
    Returns:
        Decorated function with tracing
    """
    def decorator(func: Callable) -> Callable:
        if not LANGSMITH_ENABLED:
            return func
        
        trace_name = name or func.__name__
        trace_tags = tags or []
        trace_metadata = metadata or {}
        
        @traceable(
            name=trace_name,
            run_type=run_type,
            tags=trace_tags,
            metadata=trace_metadata
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def trace_agent(
    agent_name: str,
    agent_role: Optional[str] = None
) -> Callable:
    """
    Decorator for tracing agent execution.
    
    Adds agent-specific metadata to traces.
    
    Args:
        agent_name: Name of the agent
        agent_role: Role of the agent in the system
    
    Returns:
        Decorated function with agent tracing
    """
    return trace_function(
        name=f"agent:{agent_name}",
        run_type="chain",
        tags=["agent", agent_name],
        metadata={
            "agent_name": agent_name,
            "agent_role": agent_role or agent_name
        }
    )


def trace_llm_call(
    model_name: Optional[str] = None,
    provider: str = "gigachat"
) -> Callable:
    """
    Decorator for tracing LLM calls.
    
    Args:
        model_name: Name of the model
        provider: LLM provider name
        
    Returns:
        Decorated function with LLM tracing
    """
    return trace_function(
        name=f"llm:{provider}:{model_name or 'default'}",
        run_type="llm",
        tags=["llm", provider],
        metadata={
            "model_name": model_name,
            "provider": provider
        }
    )


def trace_retrieval(
    retriever_type: str = "hybrid"
) -> Callable:
    """
    Decorator for tracing retrieval operations.
    
    Args:
        retriever_type: Type of retriever
        
    Returns:
        Decorated function with retrieval tracing
    """
    return trace_function(
        name=f"retrieval:{retriever_type}",
        run_type="retriever",
        tags=["retrieval", retriever_type],
        metadata={
            "retriever_type": retriever_type
        }
    )


def trace_tool(
    tool_name: str
) -> Callable:
    """
    Decorator for tracing tool usage.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Decorated function with tool tracing
    """
    return trace_function(
        name=f"tool:{tool_name}",
        run_type="tool",
        tags=["tool", tool_name],
        metadata={
            "tool_name": tool_name
        }
    )


def add_run_metadata(metadata: Dict[str, Any]) -> bool:
    """
    Add metadata to the current run.
    
    Args:
        metadata: Metadata to add
    
    Returns:
        True if successful, False otherwise
    """
    if not LANGSMITH_ENABLED:
        return False
    
    try:
        run_tree = get_current_run_tree()
        if run_tree:
            run_tree.extra["metadata"] = run_tree.extra.get("metadata", {})
            run_tree.extra["metadata"].update(metadata)
            return True
    except Exception as e:
        logger.debug(f"Could not add run metadata: {e}")
    
    return False


def add_run_tags(tags: List[str]) -> bool:
    """
    Add tags to the current run.
    
    Args:
        tags: Tags to add
        
    Returns:
        True if successful, False otherwise
    """
    if not LANGSMITH_ENABLED:
        return False
    
    try:
        run_tree = get_current_run_tree()
        if run_tree:
            run_tree.tags = list(set(run_tree.tags or []) | set(tags))
            return True
    except Exception as e:
        logger.debug(f"Could not add run tags: {e}")
    
    return False


class LangSmithEvaluator:
    """
    Evaluator for LangSmith-based output quality assessment.
    
    Provides online and offline evaluation capabilities.
    """
    
    def __init__(self):
        """Initialize the evaluator."""
        self._client = get_langsmith_client()
    
    def evaluate_correctness(
        self,
        prediction: str,
        reference: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate correctness of a prediction.
        
        Uses LLM-as-judge for correctness scoring.
        
        Args:
            prediction: The prediction to evaluate
            reference: Reference answer
            context: Optional context
            
        Returns:
            Evaluation result with score and reasoning
        """
        if not self._client:
            return {"score": None, "error": "LangSmith not available"}
        
        try:
            from app.services.llm_factory import create_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm = create_llm(temperature=0.0)
            
            prompt = f"""Оцени корректность предсказания по сравнению с эталоном.

Предсказание: {prediction[:1000]}

Эталон: {reference[:1000]}

{f'Контекст: {context[:500]}' if context else ''}

Ответь в формате:
SCORE: [0-10]
REASONING: [обоснование]"""
            
            response = llm.invoke([
                SystemMessage(content="Ты оцениваешь качество ответов AI системы."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse score
            import re
            score_match = re.search(r'SCORE:\s*(\d+)', content)
            score = int(score_match.group(1)) / 10.0 if score_match else None
            
            return {
                "score": score,
                "reasoning": content,
                "evaluator": "correctness"
            }
            
        except Exception as e:
            logger.error(f"Correctness evaluation error: {e}")
            return {"score": None, "error": str(e)}
    
    def evaluate_groundedness(
        self,
        answer: str,
        context: str
    ) -> Dict[str, Any]:
        """
        Evaluate if answer is grounded in context.
        
        Args:
            answer: The answer to evaluate
            context: The source context
        
        Returns:
            Evaluation result with score
        """
        if not self._client:
            return {"score": None, "error": "LangSmith not available"}
        
        try:
            from app.services.llm_factory import create_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm = create_llm(temperature=0.0)
            
            prompt = f"""Оцени, насколько ответ обоснован контекстом (grounded).

Ответ: {answer[:1000]}

Контекст: {context[:2000]}

Оцени от 0 до 10:
- 10 = полностью обоснован контекстом
- 5 = частично обоснован
- 0 = не обоснован контекстом

Ответь: SCORE: [число]"""
            
            response = llm.invoke([
                SystemMessage(content="Оценивай обоснованность ответов."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            
            import re
            score_match = re.search(r'SCORE:\s*(\d+)', content)
            score = int(score_match.group(1)) / 10.0 if score_match else None
            
            return {
                "score": score,
                "reasoning": content,
                "evaluator": "groundedness"
            }
            
        except Exception as e:
            logger.error(f"Groundedness evaluation error: {e}")
            return {"score": None, "error": str(e)}


def get_langsmith_stats() -> Dict[str, Any]:
    """
    Get LangSmith integration statistics.
    
    Returns:
        Dictionary with LangSmith status and stats
    """
    return {
        "langsmith_available": LANGSMITH_AVAILABLE,
        "langsmith_enabled": LANGSMITH_ENABLED,
        "project": config.LANGSMITH_PROJECT if LANGSMITH_ENABLED else None,
        "endpoint": config.LANGSMITH_ENDPOINT if LANGSMITH_ENABLED else None,
        "tracing_enabled": config.LANGSMITH_TRACING
    }


# Initialize on import
if LANGSMITH_ENABLED:
    setup_langsmith_tracing()
