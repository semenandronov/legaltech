"""Base agent node class to eliminate code duplication across agent nodes"""
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.langchain_agents.memory_manager import AgentMemoryManager
from app.services.langchain_agents.file_system_helper import get_file_system_context_from_state
from app.services.langchain_agents.file_system_tools import initialize_file_system_tools
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
import logging

logger = logging.getLogger(__name__)


class BaseAgentNode(ABC):
    """
    Base class for agent nodes to eliminate code duplication.
    
    Provides common functionality:
    - Tool initialization
    - LLM setup
    - Memory management
    - File system context
    - Error handling
    """
    
    def __init__(
        self,
        agent_name: str,
        db: Optional[Session] = None,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None
    ):
        """
        Initialize base agent node
        
        Args:
            agent_name: Name of the agent (e.g., "timeline", "key_facts")
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.agent_name = agent_name
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
    
    def execute(
        self,
        state: AnalysisState,
        db: Optional[Session] = None,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None
    ) -> AnalysisState:
        """
        Execute agent node - main entry point
        
        Args:
            state: Current graph state
            db: Database session (overrides instance db if provided)
            rag_service: RAG service (overrides instance if provided)
            document_processor: Document processor (overrides instance if provided)
            
        Returns:
            Updated state with agent result
        """
        # Use provided services or instance services
        db = db or self.db
        rag_service = rag_service or self.rag_service
        document_processor = document_processor or self.document_processor
        
        case_id = state.get("case_id", "unknown")
        
        try:
            logger.info(f"{self.agent_name} agent: Starting for case {case_id}")
            
            # Initialize file system context
            self._initialize_file_system_context(state)
            
            # Initialize tools
            self._initialize_tools(rag_service, document_processor)
            
            # Get tools
            tools = get_all_tools()
            
            # Initialize LLM
            llm = create_llm(temperature=0.1)
            
            # Initialize memory manager
            memory_manager = AgentMemoryManager(case_id, llm)
            memory_context = memory_manager.get_context_for_agent(self.agent_name, "")
            
            # Check if LLM supports function calling
            use_tools = hasattr(llm, 'bind_tools')
            
            if use_tools and rag_service:
                # Use agent with tools
                result = self._execute_with_tools(
                    state=state,
                    llm=llm,
                    tools=tools,
                    memory_context=memory_context,
                    rag_service=rag_service,
                    case_id=case_id
                )
            else:
                # Fallback to direct LLM call
                logger.warning(f"{self.agent_name} agent: LLM doesn't support tools, using direct call")
                result = self._execute_without_tools(
                    state=state,
                    llm=llm,
                    memory_context=memory_context,
                    case_id=case_id
                )
            
            # Process and format result
            formatted_result = self._format_result(result, state)
            
            # Update state
            new_state = dict(state)
            result_key = f"{self.agent_name}_result"
            new_state[result_key] = formatted_result
            
            # Update completed steps
            if "completed_steps" not in new_state:
                new_state["completed_steps"] = []
            step_id = f"{self.agent_name}_{case_id}_{len(new_state['completed_steps'])}"
            if step_id not in new_state["completed_steps"]:
                new_state["completed_steps"].append(step_id)
            
            # Save to memory
            if memory_context:
                memory_manager.save_to_memory(
                    self.agent_name,
                    str(state.get("analysis_types", [])),
                    str(formatted_result)[:500]
                )
            
            logger.info(f"{self.agent_name} agent: Completed successfully for case {case_id}")
            return new_state
            
        except Exception as e:
            logger.error(f"{self.agent_name} agent error for case {case_id}: {e}", exc_info=True)
            return self._handle_error(state, e)
    
    def _initialize_file_system_context(self, state: AnalysisState) -> None:
        """Initialize file system context if available"""
        file_system_context = get_file_system_context_from_state(state)
        if file_system_context:
            initialize_file_system_tools(file_system_context)
        else:
            case_id = state.get("case_id", "unknown")
            logger.debug(f"FileSystemContext not in state for case {case_id}, will auto-initialize when needed")
    
    def _initialize_tools(
        self,
        rag_service: Optional[RAGService],
        document_processor: Optional[DocumentProcessor]
    ) -> None:
        """Initialize tools if services available"""
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
    
    def _execute_with_tools(
        self,
        state: AnalysisState,
        llm: Any,
        tools: List[Any],
        memory_context: Optional[str],
        rag_service: RAGService,
        case_id: str
    ) -> Dict[str, Any]:
        """
        Execute agent with tools support
        
        Args:
            state: Current state
            llm: LLM instance
            tools: List of tools
            memory_context: Memory context from previous runs
            rag_service: RAG service
            case_id: Case identifier
            
        Returns:
            Agent result
        """
        base_prompt = get_agent_prompt(self.agent_name)
        
        # Add memory context if available
        if memory_context:
            prompt = f"""{base_prompt}

Предыдущий контекст из памяти:
{memory_context}

Используй этот контекст для улучшения анализа."""
        else:
            prompt = base_prompt
        
        # Create agent
        agent = create_legal_agent(llm, tools, system_prompt=prompt)
        
        # Create user query
        user_query = self._create_user_query(case_id, state)
        initial_message = HumanMessage(content=user_query)
        
        # Invoke agent
        from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
        callback = AnalysisCallbackHandler(agent_name=self.agent_name)
        
        result = safe_agent_invoke(
            agent,
            llm,
            {
                "messages": [initial_message],
                "case_id": case_id
            },
            config={"recursion_limit": 15, "callbacks": [callback]}
        )
        
        return result
    
    def _execute_without_tools(
        self,
        state: AnalysisState,
        llm: Any,
        memory_context: Optional[str],
        case_id: str
    ) -> Dict[str, Any]:
        """
        Execute agent without tools (fallback)
        
        Args:
            state: Current state
            llm: LLM instance
            memory_context: Memory context
            case_id: Case identifier
            
        Returns:
            Agent result
        """
        base_prompt = get_agent_prompt(self.agent_name)
        user_query = self._create_user_query(case_id, state)
        
        if memory_context:
            full_prompt = f"""{base_prompt}

Предыдущий контекст:
{memory_context}

Запрос: {user_query}"""
        else:
            full_prompt = f"""{base_prompt}

Запрос: {user_query}"""
        
        response = llm.invoke([HumanMessage(content=full_prompt)])
        
        return {
            "messages": [response] if response else [],
            "case_id": case_id
        }
    
    @abstractmethod
    def _create_user_query(self, case_id: str, state: AnalysisState) -> str:
        """
        Create user query for the agent (must be implemented by subclasses)
        
        Args:
            case_id: Case identifier
            state: Current state
            
        Returns:
            User query string
        """
        pass
    
    @abstractmethod
    def _format_result(self, result: Dict[str, Any], state: AnalysisState) -> Dict[str, Any]:
        """
        Format agent result (must be implemented by subclasses)
        
        Args:
            result: Raw agent result
            state: Current state
            
        Returns:
            Formatted result dictionary
        """
        pass
    
    def _handle_error(self, state: AnalysisState, error: Exception) -> AnalysisState:
        """
        Handle error in agent execution
        
        Args:
            state: Current state
            error: Exception that occurred
            
        Returns:
            Updated state with error information
        """
        new_state = dict(state)
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": self.agent_name,
            "error": str(error)
        })
        
        # Set result to None to indicate failure
        result_key = f"{self.agent_name}_result"
        new_state[result_key] = None
        
        return new_state

