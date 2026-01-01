"""Factory для создания агентов с обратной совместимостью"""
from langchain_openai import ChatOpenAI
from typing import List, Any, Optional, Dict
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
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
        # #region agent log
        import json
        import os
        try:
            log_path = os.path.join(os.getcwd(), '.cursor', 'debug.log')
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, 'a') as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "agent-invoke-start",
                    "hypothesisId": "H4",
                    "location": "agent_factory.py:safe_agent_invoke",
                    "message": "Invoking agent",
                    "data": {
                        "has_messages": "messages" in input_data,
                        "messages_count": len(input_data.get("messages", [])),
                        "case_id": input_data.get("case_id"),
                        "recursion_limit": agent_config.get("recursion_limit")
                    },
                    "timestamp": int(__import__('time').time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        result = agent.invoke(input_data, config=agent_config)
        return result
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        # #region agent log
        try:
            import json
            import os
            import traceback
            log_path = os.path.join(os.getcwd(), '.cursor', 'debug.log')
            with open(log_path, 'a') as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "agent-invoke-error",
                    "hypothesisId": "H5",
                    "location": "agent_factory.py:safe_agent_invoke:exception",
                    "message": "Agent invoke error",
                    "data": {
                        "error_type": error_type,
                        "error_message": error_msg[:500],
                        "is_tool_error": "bind_tools" in error_msg or "tool use" in error_msg.lower(),
                        "traceback": traceback.format_exc()[:1000]
                    },
                    "timestamp": int(__import__('time').time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        
        # Check if error is related to tool use not being supported
        # Check if error is related to tool use not being supported
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


def create_agent_chain_lcel(
    agent_type: str,
    llm: ChatOpenAI,
    tools: List[Any],
    system_prompt: str,
    rag_service: Optional[Any] = None,
    case_id: Optional[str] = None
) -> Any:
    """
    Create agent chain using LangChain Expression Language (LCEL)
    
    LCEL provides more flexible composition and easier testing of individual steps.
    
    Args:
        agent_type: Type of agent (timeline, key_facts, etc.)
        llm: LLM instance
        tools: List of tools for the agent
        system_prompt: System prompt for the agent
        rag_service: Optional RAG service for document retrieval
        case_id: Optional case ID for context
        
    Returns:
        LCEL chain (Runnable)
    """
    try:
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain_core.pydantic_v1 import BaseModel
        from typing import List as TypingList
        
        # Step 1: Prepare context (RunnableLambda)
        def prepare_context(state: Dict[str, Any]) -> Dict[str, Any]:
            """Prepare context for agent execution"""
            context = {
                "query": state.get("query", ""),
                "case_id": state.get("case_id", case_id),
                "previous_results": state.get("previous_results", {})
            }
            
            # Add document retrieval if RAG service available
            if rag_service and context["case_id"]:
                try:
                    # Retrieve relevant documents
                    documents = rag_service.retrieve_documents(
                        query=context["query"],
                        case_id=context["case_id"],
                        k=20
                    )
                    context["documents"] = "\n\n".join([
                        f"Document: {doc.page_content[:500]}" 
                        for doc in documents[:10]  # Limit to 10 docs
                    ])
                except Exception as e:
                    logger.warning(f"Error retrieving documents in LCEL chain: {e}")
                    context["documents"] = ""
            
            return context
        
        prepare_context_step = RunnableLambda(prepare_context)
        
        # Step 2: Create prompt template
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", """Запрос: {query}

Документы:
{documents}

Предыдущие результаты:
{previous_results}

Выполни задачу и верни результат.""")
        ])
        
        # Step 3: LLM with tools (if tools available)
        if tools and hasattr(llm, 'bind_tools'):
            try:
                llm_with_tools = llm.bind_tools(tools)
            except Exception as e:
                logger.warning(f"Could not bind tools to LLM: {e}, using LLM without tools")
                llm_with_tools = llm
        else:
            llm_with_tools = llm
        
        # Step 4: Parse output (optional, can be added later)
        # For now, return raw LLM response
        
        # Chain: prepare_context | prompt_template | llm_with_tools
        chain = (
            prepare_context_step
            | prompt_template
            | llm_with_tools
        )
        
        logger.debug(f"Created LCEL chain for {agent_type}")
        return chain
        
    except Exception as e:
        logger.warning(f"Failed to create LCEL chain for {agent_type}: {e}, falling back to regular agent")
        # Fallback to regular agent creation
        return create_legal_agent(llm, tools, system_prompt=system_prompt)
