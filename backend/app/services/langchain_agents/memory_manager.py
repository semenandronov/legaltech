"""LangChain Memory Manager for agent context between requests"""
from typing import Dict, Any, Optional
from app.services.llm_factory import create_llm
import json
import logging

logger = logging.getLogger(__name__)


class AgentMemoryManager:
    """
    Управление памятью для агентов между запросами
    
    Использует LangChain Memory системы для сохранения контекста
    предыдущих взаимодействий каждого типа агента.
    """
    
    def __init__(self, case_id: str, llm=None):
        """
        Initialize memory manager
        
        Args:
            case_id: Case identifier for memory isolation
            llm: LLM instance for summarization (optional, will create if not provided)
        """
        self.case_id = case_id
        self.llm = llm or create_llm()
        
        # Dictionary to store memory for each agent type
        self.memories: Dict[str, Any] = {}
        
        # Memory configuration
        self.max_token_limit = 2000  # Maximum tokens per memory
        self.return_messages = True  # Return messages format
        
        logger.debug(f"AgentMemoryManager initialized for case {case_id}")
    
    def _get_memory_for_agent(self, agent_type: str):
        """
        Get or create memory instance for agent type
        
        Args:
            agent_type: Type of agent (timeline, key_facts, etc.)
            
        Returns:
            Memory instance
        """
        if agent_type not in self.memories:
            try:
                # Try ConversationSummaryBufferMemory first (summarizes old messages)
                from langchain.memory import ConversationSummaryBufferMemory
                
                memory = ConversationSummaryBufferMemory(
                    llm=self.llm,
                    max_token_limit=self.max_token_limit,
                    return_messages=self.return_messages,
                    memory_key="history"
                )
                self.memories[agent_type] = memory
                logger.debug(f"Created ConversationSummaryBufferMemory for {agent_type}")
            except ImportError:
                # Fallback to ConversationBufferWindowMemory
                try:
                    from langchain.memory import ConversationBufferWindowMemory
                    
                    memory = ConversationBufferWindowMemory(
                        k=10,  # Keep last 10 interactions
                        return_messages=self.return_messages,
                        memory_key="history"
                    )
                    self.memories[agent_type] = memory
                    logger.debug(f"Created ConversationBufferWindowMemory for {agent_type}")
                except ImportError:
                    logger.warning("LangChain memory classes not available, using no-op memory")
                    # Create a no-op memory
                    self.memories[agent_type] = None
        
        return self.memories.get(agent_type)
    
    def get_context_for_agent(self, agent_type: str, query: str) -> str:
        """
        Получить контекст из памяти агента
        
        Использует:
        - ConversationSummaryMemory для кратких сводок
        - FactStore для структурированных фактов (semantic search)
        
        Args:
            agent_type: Type of agent
            query: Current query (for context)
            
        Returns:
            Context string from memory or empty string
        """
        context_parts = []
        
        # Загрузить структурированные факты из FactStore
        structured_fact_types = ["entity_extraction", "key_facts", "timeline"]
        
        if agent_type in structured_fact_types:
            try:
                from app.services.langchain_agents.fact_store import get_fact_store
                fact_store = get_fact_store(self.case_id)
                
                # Поиск релевантных фактов
                relevant_facts = fact_store.search_facts(
                    fact_type=agent_type,
                    query=query,
                    limit=5
                )
                
                if relevant_facts:
                    facts_text = "\n".join([
                        json.dumps(fact, ensure_ascii=False) for fact in relevant_facts[:3]
                    ])
                    context_parts.append(f"Relevant {agent_type} facts:\n{facts_text}")
                    logger.debug(f"Loaded {len(relevant_facts)} relevant facts from FactStore for {agent_type}")
            except Exception as fact_error:
                logger.debug(f"FactStore load failed (non-critical): {fact_error}")
        
        # Загрузить краткие сводки из ConversationSummaryMemory
        memory = self._get_memory_for_agent(agent_type)
        
        if memory is not None:
            try:
                # Load memory variables
                memory_vars = memory.load_memory_variables({})
                
                # Extract history
                history = memory_vars.get("history", "")
                
                if isinstance(history, list):
                    # Convert messages to string
                    history_str = "\n".join([
                        f"{msg.type}: {msg.content}" if hasattr(msg, 'type') and hasattr(msg, 'content')
                        else str(msg)
                        for msg in history
                    ])
                    if history_str:
                        context_parts.append(f"Previous interactions:\n{history_str}")
                elif isinstance(history, str) and history:
                    context_parts.append(f"Previous interactions:\n{history}")
                    
            except Exception as e:
                logger.warning(f"Error loading memory for {agent_type}: {e}")
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def save_to_memory(self, agent_type: str, input_text: str, output_text: str):
        """
        Сохранить взаимодействие в память
        
        Использует:
        - ConversationSummaryMemory для кратких сводок (<500 токенов)
        - FactStore для структурированных фактов (entities, key_facts, timeline events)
        
        Args:
            agent_type: Type of agent
            input_text: Input/query text
            output_text: Output/result text
        """
        # Для структурированных фактов использовать FactStore
        structured_fact_types = ["entity_extraction", "key_facts", "timeline"]
        
        if agent_type in structured_fact_types:
            try:
                from app.services.langchain_agents.fact_store import get_fact_store
                fact_store = get_fact_store(self.case_id)
                
                # Попытаться извлечь структурированные факты из output_text
                # (в production можно парсить JSON или использовать structured output)
                # Пока сохраняем как текст, но в будущем можно улучшить
                facts = [{"text": output_text, "source": input_text}]
                fact_store.save_facts(
                    fact_type=agent_type,
                    facts=facts,
                    metadata={"input": input_text[:200]}
                )
                logger.debug(f"Saved structured facts to FactStore for {agent_type}")
            except Exception as fact_error:
                logger.debug(f"FactStore save failed (non-critical): {fact_error}")
        
        # Для кратких сводок использовать ConversationSummaryMemory
        memory = self._get_memory_for_agent(agent_type)
        
        if memory is None:
            return
        
        try:
            # Сохранить только если output_text короткий (<500 токенов)
            # Для длинных результатов используем только FactStore
            output_length = len(output_text.split())
            if output_length < 500:  # Приблизительно <500 токенов
                memory.save_context(
                    {"input": input_text},
                    {"output": output_text}
                )
                logger.debug(f"Saved interaction to ConversationSummaryMemory for {agent_type}")
        except Exception as e:
            logger.warning(f"Error saving memory for {agent_type}: {e}")
    
    def clear_memory(self, agent_type: Optional[str] = None):
        """
        Очистить память для агента или всех агентов
        
        Args:
            agent_type: Type of agent to clear (None = clear all)
        """
        if agent_type:
            if agent_type in self.memories:
                memory = self.memories[agent_type]
                if memory and hasattr(memory, 'clear'):
                    memory.clear()
                    logger.debug(f"Cleared memory for {agent_type}")
                del self.memories[agent_type]
        else:
            # Clear all memories
            for agent_type_key, memory in self.memories.items():
                if memory and hasattr(memory, 'clear'):
                    memory.clear()
            self.memories.clear()
            logger.debug("Cleared all memories")
    
    def get_memory_summary(self, agent_type: str) -> Optional[str]:
        """
        Получить суммаризованную версию памяти (если используется SummaryBufferMemory)
        
        Args:
            agent_type: Type of agent
            
        Returns:
            Summary string or None
        """
        memory = self._get_memory_for_agent(agent_type)
        
        if memory is None:
            return None
        
        try:
            # For ConversationSummaryBufferMemory, get the summary
            if hasattr(memory, 'moving_summary_buffer'):
                return memory.moving_summary_buffer
            elif hasattr(memory, 'get_summary'):
                return memory.get_summary()
            else:
                return None
        except Exception as e:
            logger.warning(f"Error getting memory summary for {agent_type}: {e}")
            return None

