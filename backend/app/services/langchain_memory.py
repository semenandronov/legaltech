"""LangChain memory components for Legal AI Vault"""
from typing import List, Dict, Any, Optional
import logging

from langchain_openai import ChatOpenAI
from langchain_core.memory import BaseMemory
from app.config import config

logger = logging.getLogger(__name__)

# Try to import memory classes with fallback strategies
ConversationBufferMemory = None
ConversationSummaryMemory = None
ConversationBufferWindowMemory = None
ConversationKGMemory = None
EntityMemory = None

try:
    # LangChain 1.x - try langchain_community first
    from langchain_community.memory import (
        ConversationBufferMemory,
        ConversationSummaryMemory,
        ConversationBufferWindowMemory,
        ConversationKGMemory,
        EntityMemory,
    )
    logger.debug("Memory classes imported from langchain_community")
except ImportError:
    try:
        # Fallback to langchain.memory
        from langchain.memory import (
            ConversationBufferMemory,
            ConversationSummaryMemory,
            ConversationBufferWindowMemory,
            ConversationKGMemory,
            EntityMemory,
        )
        logger.debug("Memory classes imported from langchain.memory")
    except ImportError:
        # If memory classes are not available, set to None
        logger.warning("Memory classes not available, using fallback methods")


class MemoryService:
    """Service for managing conversation memory"""
    
    def __init__(self):
        """Initialize memory service"""
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,
            max_tokens=1000
        )
        
        # Store memory instances per case
        self.memories: Dict[str, Dict[str, BaseMemory]] = {}
    
    def get_memory(
        self,
        case_id: str,
        memory_type: str = "summary"
    ) -> BaseMemory:
        """
        Get or create memory instance for a case
        
        Args:
            case_id: Case identifier
            memory_type: Type of memory ('buffer', 'summary', 'window', 'kg', 'entity')
            
        Returns:
            Memory instance
        """
        if case_id not in self.memories:
            self.memories[case_id] = {}
        
        if memory_type not in self.memories[case_id]:
            if ConversationBufferMemory is None:
                raise ImportError(
                    "Memory classes are not available. Please ensure langchain-community or langchain is installed."
                )
            
            if memory_type == "buffer":
                if ConversationBufferMemory is None:
                    raise ValueError("ConversationBufferMemory is not available")
                memory = ConversationBufferMemory(
                    return_messages=True,
                    memory_key="chat_history"
                )
            elif memory_type == "summary":
                if ConversationSummaryMemory is None:
                    raise ValueError("ConversationSummaryMemory is not available")
                memory = ConversationSummaryMemory(
                    llm=self.llm,
                    return_messages=True,
                    memory_key="chat_history"
                )
            elif memory_type == "window":
                if ConversationBufferWindowMemory is None:
                    raise ValueError("ConversationBufferWindowMemory is not available")
                memory = ConversationBufferWindowMemory(
                    k=10,  # Last 10 messages
                    return_messages=True,
                    memory_key="chat_history"
                )
            elif memory_type == "kg":
                if ConversationKGMemory is None:
                    raise ValueError("ConversationKGMemory is not available")
                memory = ConversationKGMemory(
                    llm=self.llm,
                    return_messages=True,
                    memory_key="chat_history"
                )
            elif memory_type == "entity":
                if EntityMemory is None:
                    raise ValueError("EntityMemory is not available")
                memory = EntityMemory(
                    llm=self.llm,
                    return_messages=True,
                    memory_key="chat_history"
                )
            else:
                raise ValueError(f"Unknown memory type: {memory_type}")
            
            self.memories[case_id][memory_type] = memory
            logger.info(f"Created {memory_type} memory for case {case_id}")
        
        return self.memories[case_id][memory_type]
    
    def load_history_into_memory(
        self,
        case_id: str,
        chat_history: List[Dict[str, str]],
        memory_type: str = "summary"
    ):
        """
        Load chat history into memory
        
        Args:
            case_id: Case identifier
            chat_history: List of messages with 'role' and 'content'
            memory_type: Type of memory to use
        """
        memory = self.get_memory(case_id, memory_type)
        
        # Clear existing memory
        memory.clear()
        
        # Load history
        for msg in chat_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                memory.chat_memory.add_user_message(content)
            elif role == "assistant":
                memory.chat_memory.add_ai_message(content)
        
        logger.info(f"Loaded {len(chat_history)} messages into {memory_type} memory for case {case_id}")
    
    def get_memory_variables(
        self,
        case_id: str,
        memory_type: str = "summary"
    ) -> Dict[str, Any]:
        """
        Get memory variables for prompt
        
        Args:
            case_id: Case identifier
            memory_type: Type of memory to use
            
        Returns:
            Dictionary with memory variables
        """
        memory = self.get_memory(case_id, memory_type)
        return memory.load_memory_variables({})
    
    def save_context(
        self,
        case_id: str,
        user_input: str,
        ai_output: str,
        memory_type: str = "summary"
    ):
        """
        Save conversation context to memory
        
        Args:
            case_id: Case identifier
            user_input: User message
            ai_output: AI response
            memory_type: Type of memory to use
        """
        memory = self.get_memory(case_id, memory_type)
        memory.save_context({"input": user_input}, {"output": ai_output})
    
    def clear_memory(self, case_id: str, memory_type: Optional[str] = None):
        """
        Clear memory for a case
        
        Args:
            case_id: Case identifier
            memory_type: Type of memory to clear (None = all types)
        """
        if case_id in self.memories:
            if memory_type:
                if memory_type in self.memories[case_id]:
                    self.memories[case_id][memory_type].clear()
                    logger.info(f"Cleared {memory_type} memory for case {case_id}")
            else:
                for mem in self.memories[case_id].values():
                    mem.clear()
                logger.info(f"Cleared all memory for case {case_id}")
