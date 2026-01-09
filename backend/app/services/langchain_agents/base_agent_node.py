"""Base agent node class to eliminate code duplication across agent nodes

Phase 1.2: Added PostgresStore-based caching support.
Phase 1.3: Added Pydantic structured output support.
"""
from typing import Dict, Any, Optional, List, Type
from abc import ABC, abstractmethod
from pydantic import BaseModel
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.llm_factory import create_llm, create_llm_for_agent
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.langchain_agents.memory_manager import AgentMemoryManager
from app.services.langchain_agents.file_system_helper import get_file_system_context_from_state
from app.services.langchain_agents.file_system_tools import initialize_file_system_tools
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_ENABLED = True  # Can be overridden by config
CACHE_PROMPT_VERSION = "v1"  # Increment when prompts change significantly


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
        document_processor: Optional[DocumentProcessor] = None,
        output_schema: Optional[Type[BaseModel]] = None
    ):
        """
        Initialize base agent node
        
        Args:
            agent_name: Name of the agent (e.g., "timeline", "key_facts")
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
            output_schema: Optional Pydantic model class for structured output validation
        """
        self.agent_name = agent_name
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        self._cache_service = None
        self._use_cache = CACHE_ENABLED
        # Auto-detect schema from agent_results if not provided
        if output_schema is None:
            try:
                from app.services.langchain_agents.schemas.agent_results import get_agent_schema
                output_schema = get_agent_schema(agent_name)
            except Exception as e:
                logger.debug(f"Could not auto-detect schema for {agent_name}: {e}")
        
        self.output_schema = output_schema
        self._structured_output_handler = None
    
    def _get_structured_output_handler(self, llm: Optional[Any] = None):
        """
        Get or create StructuredOutputHandler for this agent.
        
        Args:
            llm: Optional LLM instance for error fixing
        
        Returns:
            StructuredOutputHandler instance or None if no schema defined
        """
        if not self.output_schema:
            return None
        
        if self._structured_output_handler is None:
            from app.services.langchain_agents.structured_output_handler import StructuredOutputHandler
            self._structured_output_handler = StructuredOutputHandler(
                model_class=self.output_schema,
                max_retries=3,
                llm=llm
            )
        
        return self._structured_output_handler
    
    def _format_result_with_schema(
        self,
        result: Dict[str, Any],
        state: AnalysisState,
        llm: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Format result using structured output handler if schema is defined.
        
        This is an optional helper method that can be called from _format_result
        in subclasses to get validated output.
        
        Args:
            result: Raw agent result
            state: Current state
            llm: Optional LLM instance for error fixing
        
        Returns:
            Formatted result dictionary (validated if schema is defined)
        """
        handler = self._get_structured_output_handler(llm)
        
        if handler and isinstance(result, dict):
            # Try to extract response text from result
            response_text = None
            if "messages" in result:
                messages = result.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    response_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
            
            if response_text:
                try:
                    # Try to parse with structured output handler
                    validated_model = handler.parse_with_retry(response_text, llm)
                    # Convert to dict for compatibility
                    if hasattr(validated_model, 'dict'):
                        return validated_model.dict()
                    elif hasattr(validated_model, 'model_dump'):
                        return validated_model.model_dump()
                    else:
                        return result
                except Exception as e:
                    logger.warning(f"{self.agent_name} structured output validation failed: {e}, using raw result")
                    return result
        
        # No schema or parsing failed, return as-is
        return result
    
    def _get_cache_service(self, db: Session):
        """Get or create the cache service instance."""
        if not self._use_cache or db is None:
            return None
        
        if self._cache_service is None:
            try:
                from app.services.langchain_agents.store_cache_service import get_store_cache_service
                self._cache_service = get_store_cache_service(db)
            except Exception as e:
                logger.warning(f"Cache service not available: {e}")
                self._use_cache = False
                return None
        
        return self._cache_service
    
    def _get_document_hash(self, state: AnalysisState) -> Optional[str]:
        """Generate a hash of documents for cache invalidation."""
        try:
            documents = state.get("documents", [])
            if not documents:
                return None
            
            # Create a hash of document IDs and modification times
            doc_data = []
            for doc in documents:
                if isinstance(doc, dict):
                    doc_data.append({
                        "id": doc.get("id", ""),
                        "content_hash": hashlib.md5(
                            str(doc.get("content", ""))[:1000].encode()
                        ).hexdigest()[:8]
                    })
            
            return hashlib.md5(
                json.dumps(doc_data, sort_keys=True).encode()
            ).hexdigest()[:16]
        except Exception:
            return None
    
    def _check_cache(
        self,
        state: AnalysisState,
        db: Session,
        case_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if result is cached."""
        cache_service = self._get_cache_service(db)
        if not cache_service:
            return None
        
        try:
            # Create cache key from analysis types
            query = json.dumps(state.get("analysis_types", []), sort_keys=True)
            document_hash = self._get_document_hash(state)
            
            cached = cache_service.get(
                query=query,
                agent_name=self.agent_name,
                case_id=case_id,
                prompt_version=CACHE_PROMPT_VERSION,
                document_hash=document_hash
            )
            
            if cached:
                logger.info(f"{self.agent_name} agent: Using cached result for case {case_id}")
                return cached
            
            return None
        except Exception as e:
            logger.warning(f"Cache lookup error: {e}")
            return None
    
    def _save_to_cache(
        self,
        state: AnalysisState,
        result: Dict[str, Any],
        db: Session,
        case_id: str
    ) -> None:
        """Save result to cache."""
        cache_service = self._get_cache_service(db)
        if not cache_service:
            return
        
        try:
            query = json.dumps(state.get("analysis_types", []), sort_keys=True)
            document_hash = self._get_document_hash(state)
            
            cache_service.set(
                query=query,
                agent_name=self.agent_name,
                result=result,
                case_id=case_id,
                prompt_version=CACHE_PROMPT_VERSION,
                document_hash=document_hash,
                metadata={
                    "analysis_types": state.get("analysis_types", [])
                }
            )
            
            logger.debug(f"{self.agent_name} agent: Cached result for case {case_id}")
        except Exception as e:
            logger.warning(f"Cache save error: {e}")
    
    def execute(
        self,
        state: AnalysisState,
        db: Optional[Session] = None,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None,
        retry_count: int = 0
    ) -> AnalysisState:
        """
        Execute agent node - main entry point with smart retry
        
        Args:
            state: Current graph state
            db: Database session (overrides instance db if provided)
            rag_service: RAG service (overrides instance if provided)
            document_processor: Document processor (overrides instance if provided)
            retry_count: Current retry attempt (for smart retry)
            
        Returns:
            Updated state with agent result
        """
        # Use provided services or instance services
        db = db or self.db
        rag_service = rag_service or self.rag_service
        document_processor = document_processor or self.document_processor
        
        case_id = state.get("case_id", "unknown")
        
        try:
            logger.info(f"{self.agent_name} agent: Starting for case {case_id} (attempt {retry_count + 1})")
            
            # Check circuit breaker before execution
            from app.services.langchain_agents.unified_error_handler import UnifiedErrorHandler
            error_handler = UnifiedErrorHandler()
            circuit_check = error_handler.check_circuit_breaker(self.agent_name)
            
            if circuit_check:
                # Circuit открыт, использовать fallback
                logger.warning(
                    f"{self.agent_name} agent: Circuit breaker OPEN, using fallback strategy"
                )
                # Попробовать получить cached result как fallback
                if retry_count == 0:
                    cached_result = self._check_cache(state, db, case_id)
                    if cached_result:
                        new_state = dict(state)
                        result_key = f"{self.agent_name}_result"
                        new_state[result_key] = cached_result
                        new_state["errors"] = state.get("errors", []) + [{
                            "agent": self.agent_name,
                            "error": "Circuit breaker open, used cached result",
                            "circuit_breaker": True
                        }]
                        return new_state
                
                # Если нет кэша, пропустить агента
                new_state = dict(state)
                new_state["errors"] = state.get("errors", []) + [{
                    "agent": self.agent_name,
                    "error": "Circuit breaker open, agent skipped",
                    "circuit_breaker": True
                }]
                return new_state
            
            # Check cache first (only on first attempt)
            if retry_count == 0:
                cached_result = self._check_cache(state, db, case_id)
                if cached_result:
                    # Return cached result
                    new_state = dict(state)
                    result_key = f"{self.agent_name}_result"
                    new_state[result_key] = cached_result
                    
                    if "completed_steps" not in new_state:
                        new_state["completed_steps"] = []
                    step_id = f"{self.agent_name}_{case_id}_{len(new_state['completed_steps'])}_cached"
                    if step_id not in new_state["completed_steps"]:
                        new_state["completed_steps"].append(step_id)
                    
                    return new_state
            
            # Check for intermediate checkpoint (для длительных операций)
            try:
                from app.services.langchain_agents.checkpoint_manager import CheckpointManager
                # Получить checkpointer из context если доступен
                checkpointer = context.get("checkpointer") if context else None
                checkpoint_manager = CheckpointManager(state, checkpointer)
                
                if checkpoint_manager.should_checkpoint():
                    checkpoint_manager.save_checkpoint()
                    logger.debug(f"{self.agent_name} agent: Saved intermediate checkpoint")
            except Exception as checkpoint_error:
                logger.debug(f"Checkpoint manager error (non-critical): {checkpoint_error}")
            
            # Initialize file system context
            self._initialize_file_system_context(state)
            
            # Initialize tools
            self._initialize_tools(rag_service, document_processor)
            
            # Get tools
            tools = get_all_tools()
            
            # Initialize LLM with temperature based on retry count (increase for retries)
            temperature = 0.1 if retry_count == 0 else min(0.3 + retry_count * 0.1, 0.7)
            
            # Determine complexity and context for model selection
            complexity = None
            context_size = None
            document_count = None
            
            # Extract complexity from state if available
            understanding_result = state.get("understanding_result", {})
            if understanding_result:
                complexity = understanding_result.get("complexity")
            
            # Extract document count from context
            context = state.get("context")
            if context and hasattr(context, 'num_documents'):
                document_count = context.num_documents
            
            # Estimate context size (rough approximation)
            messages = state.get("messages", [])
            if messages:
                context_size = sum(len(str(msg)) for msg in messages)
            
            # Use dynamic model selection
            llm = create_llm_for_agent(
                agent_name=self.agent_name,
                complexity=complexity,
                context_size=context_size,
                document_count=document_count,
                state=state,
                temperature=temperature
            )
            
            # Initialize memory manager
            memory_manager = AgentMemoryManager(case_id, llm)
            memory_context = memory_manager.get_context_for_agent(self.agent_name, "")
            
            # Reduce memory context on retries (simplify context)
            if retry_count > 0 and memory_context:
                # Truncate memory context for retries
                max_context_length = 500 if retry_count == 1 else 300
                if len(memory_context) > max_context_length:
                    memory_context = memory_context[:max_context_length] + "... [truncated for retry]"
                    logger.info(f"{self.agent_name} agent: Reduced memory context to {max_context_length} chars for retry")
            
            # Check if LLM supports function calling
            use_tools = hasattr(llm, 'bind_tools')
            
            if use_tools and rag_service:
                # Use agent with tools (with simplified prompt on retry)
                result = self._execute_with_tools(
                    state=state,
                    llm=llm,
                    tools=tools,
                    memory_context=memory_context,
                    rag_service=rag_service,
                    case_id=case_id,
                    retry_count=retry_count
                )
            else:
                # Fallback to direct LLM call
                logger.warning(f"{self.agent_name} agent: LLM doesn't support tools, using direct call")
                result = self._execute_without_tools(
                    state=state,
                    llm=llm,
                    memory_context=memory_context,
                    case_id=case_id,
                    retry_count=retry_count
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
            
            # Save to cache (Phase 1.2)
            self._save_to_cache(state, formatted_result, db, case_id)
            
            logger.info(f"{self.agent_name} agent: Completed successfully for case {case_id}")
            
            # Записать успех в circuit breaker
            from app.services.langchain_agents.circuit_breaker import get_circuit_breaker
            circuit_breaker = get_circuit_breaker()
            circuit_breaker.record_success(self.agent_name)
            
            return new_state
            
        except Exception as e:
            logger.error(f"{self.agent_name} agent error for case {case_id} (attempt {retry_count + 1}): {e}", exc_info=True)
            
            # Try smart retry with simplified parameters
            if retry_count < 2:  # Max 2 retries with smart modifications
                logger.info(f"{self.agent_name} agent: Attempting smart retry {retry_count + 1}/2 with simplified parameters")
                try:
                    return self.execute(
                        state=state,
                        db=db,
                        rag_service=rag_service,
                        document_processor=document_processor,
                        retry_count=retry_count + 1
                    )
                except Exception as retry_error:
                    logger.error(f"{self.agent_name} agent: Smart retry also failed: {retry_error}")
                    return self._handle_error(state, retry_error)
            
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
        case_id: str,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """
        Execute agent with tools support (with smart retry simplifications)
        
        Args:
            state: Current state
            llm: LLM instance
            tools: List of tools
            memory_context: Memory context from previous runs
            rag_service: RAG service
            case_id: Case identifier
            retry_count: Current retry attempt (for prompt simplification)
            
        Returns:
            Agent result
        """
        base_prompt = get_agent_prompt(self.agent_name)
        
        # Simplify prompt on retries
        if retry_count > 0:
            prompt = self._simplify_prompt(base_prompt, retry_count)
            logger.info(f"{self.agent_name} agent: Using simplified prompt for retry {retry_count}")
        else:
            prompt = base_prompt
        
        # Add memory context if available (but only if not retry or first retry)
        if memory_context and retry_count <= 1:
            prompt = f"""{prompt}

Предыдущий контекст из памяти:
{memory_context}

Используй этот контекст для улучшения анализа."""
        
        # Create agent
        agent = create_legal_agent(llm, tools, system_prompt=prompt)
        
        # Create user query (simplified on retries)
        user_query = self._create_user_query(case_id, state, retry_count=retry_count)
        initial_message = HumanMessage(content=user_query)
        
        # Invoke agent with reduced recursion limit on retries
        from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
        callback = AnalysisCallbackHandler(agent_name=self.agent_name)
        
        recursion_limit = 15 if retry_count == 0 else max(10 - retry_count * 2, 5)
        
        result = safe_agent_invoke(
            agent,
            llm,
            {
                "messages": [initial_message],
                "case_id": case_id
            },
            config={"recursion_limit": recursion_limit, "callbacks": [callback]}
        )
        
        return result
    
    def _execute_without_tools(
        self,
        state: AnalysisState,
        llm: Any,
        memory_context: Optional[str],
        case_id: str,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """
        Execute agent without tools (fallback) with smart retry
        
        Args:
            state: Current state
            llm: LLM instance
            memory_context: Memory context
            case_id: Case identifier
            retry_count: Current retry attempt (for prompt simplification)
            
        Returns:
            Agent result
        """
        base_prompt = get_agent_prompt(self.agent_name)
        
        # Simplify prompt on retries
        if retry_count > 0:
            prompt = self._simplify_prompt(base_prompt, retry_count)
        else:
            prompt = base_prompt
        
        user_query = self._create_user_query(case_id, state, retry_count=retry_count)
        
        # Include memory context only if not retry or first retry
        if memory_context and retry_count <= 1:
            full_prompt = f"""{prompt}

Предыдущий контекст:
{memory_context}

Запрос: {user_query}"""
        else:
            full_prompt = f"""{prompt}

Запрос: {user_query}"""
        
        response = llm.invoke([HumanMessage(content=full_prompt)])
        
        return {
            "messages": [response] if response else [],
            "case_id": case_id
        }
    
    def _simplify_prompt(self, base_prompt: str, retry_count: int) -> str:
        """
        Simplify prompt for retries
        
        Args:
            base_prompt: Original prompt
            retry_count: Current retry attempt
            
        Returns:
            Simplified prompt
        """
        # Extract key instructions (first 500 chars usually contain main instructions)
        # Remove detailed examples and verbose explanations on retries
        lines = base_prompt.split('\n')
        simplified_lines = []
        
        # Keep first few lines (usually main instructions)
        # Remove examples and verbose sections
        in_example_section = False
        example_markers = ["Пример:", "Example:", "Примеры:", "Examples:", "```"]
        
        for i, line in enumerate(lines):
            # Keep first 20 lines (main instructions)
            if i < 20:
                simplified_lines.append(line)
            # Skip example sections on retries
            elif any(marker in line for marker in example_markers):
                if retry_count >= 1:
                    in_example_section = True
                    continue
                simplified_lines.append(line)
            elif in_example_section and line.strip() == "":
                in_example_section = False
                simplified_lines.append(line)
            elif not in_example_section:
                # Keep important sections but truncate verbose ones
                if len(line) > 200 and retry_count >= 2:
                    simplified_lines.append(line[:200] + "...")
                else:
                    simplified_lines.append(line)
        
        simplified = '\n'.join(simplified_lines)
        
        # Add retry instruction
        retry_note = f"\n\n[Повторная попытка {retry_count}: Используй упрощенный подход]"
        return simplified + retry_note
    
    @abstractmethod
    def _create_user_query(self, case_id: str, state: AnalysisState, retry_count: int = 0) -> str:
        """
        Create user query for the agent (must be implemented by subclasses)
        
        Args:
            case_id: Case identifier
            state: Current state
            retry_count: Current retry attempt (for query simplification)
            
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


