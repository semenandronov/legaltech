"""RAG (Retrieval Augmented Generation) service"""
from typing import List, Dict, Any, Tuple
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.schema import Document
from langchain_core.exceptions import LangChainException
from openai import APIError, RateLimitError, APITimeoutError
from app.config import config
from app.services.document_processor import DocumentProcessor
from app.services.langchain_retrievers import AdvancedRetrieverService
from app.services.langchain_memory import MemoryService
import logging

logger = logging.getLogger(__name__)


class RAGService:
    """Service for RAG operations"""
    
    def __init__(self, document_processor: DocumentProcessor = None):
        """Initialize RAG service"""
        self.document_processor = document_processor or DocumentProcessor()
        self.retriever_service = AdvancedRetrieverService(self.document_processor)
        self.memory_service = MemoryService()
        
        # Initialize LLM (using OpenRouter)
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,
            max_tokens=2000
        )
    
    def retrieve_context(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: str = "simple"
    ) -> List[Document]:
        """
        Retrieve relevant context for a query
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            retrieval_strategy: Strategy to use ('simple', 'multi_query', 'compression', 'ensemble')
            
        Returns:
            List of relevant Document objects
        """
        if retrieval_strategy == "multi_query":
            return self.retriever_service.retrieve_with_multi_query(case_id, query, k=k)
        elif retrieval_strategy == "compression":
            return self.retriever_service.retrieve_with_compression(case_id, query, k=k*2)  # Get more before compression
        elif retrieval_strategy == "ensemble":
            return self.retriever_service.retrieve_with_ensemble(case_id, query, k=k)
        else:
            # Default: simple retrieval
            return self.document_processor.retrieve_relevant_chunks(
                case_id=case_id,
                query=query,
                k=k
            )
    
    def format_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Format source documents with precise references
        
        Args:
            documents: List of Document objects
            
        Returns:
            List of formatted source dictionaries
        """
        sources = []
        for doc in documents:
            metadata = doc.metadata
            source = {
                "file": metadata.get("source_file", "unknown"),
                "page": metadata.get("source_page"),
                "chunk_index": metadata.get("chunk_index"),
                "start_line": metadata.get("source_start_line"),
                "end_line": metadata.get("source_end_line"),
                "text_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                "similarity_score": metadata.get("similarity_score")
            }
            sources.append(source)
        return sources
    
    def format_sources_for_prompt(self, documents: List[Document], max_context_chars: int = None) -> str:
        """
        Format sources as text for prompt
        
        Args:
            documents: List of Document objects
            max_context_chars: Maximum characters for context (optional)
            
        Returns:
            Formatted string with sources
        """
        if max_context_chars is None:
            max_context_chars = config.MAX_CONTEXT_CHARS
        
        formatted_sources = []
        total_length = 0
        
        for i, doc in enumerate(documents, 1):
            metadata = doc.metadata
            source_file = metadata.get("source_file", "unknown")
            source_page = metadata.get("source_page")
            source_line = metadata.get("source_start_line")
            
            source_ref = f"[Источник {i}: {source_file}"
            if source_page:
                source_ref += f", стр. {source_page}"
            if source_line:
                source_ref += f", строка {source_line}"
            source_ref += "]"
            
            # Truncate document content if needed
            doc_content = doc.page_content
            available_chars = max_context_chars - total_length - len(source_ref) - 10  # Reserve space
            if available_chars < len(doc_content):
                doc_content = doc_content[:available_chars] + "..."
                logger.warning(f"Truncating document content for source {i} to fit context limit")
            
            formatted_source = f"{source_ref}\n{doc_content}"
            formatted_sources.append(formatted_source)
            total_length += len(formatted_source)
            
            # Stop if we've reached the limit
            if total_length >= max_context_chars:
                logger.warning(f"Reached context limit after {i} sources")
                break
        
        return "\n\n".join(formatted_sources)
    
    def generate_with_sources(
        self,
        case_id: str,
        query: str,
        context: str = None,
        k: int = 5
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer with source references
        
        Args:
            case_id: Case identifier
            query: User query
            context: Additional context (optional)
            k: Number of chunks to retrieve
            
        Returns:
            Tuple of (answer, sources)
        """
        # Retrieve relevant chunks
        relevant_docs = self.retrieve_context(case_id, query, k=k)
        
        if not relevant_docs:
            return "Не найдено релевантной информации в документах дела.", []
        
        # Format sources for prompt
        sources_text = self.format_sources_for_prompt(relevant_docs)
        
        # Create prompt
        system_template = """Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе предоставленных документов дела.

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [Документ: filename.pdf, стр. 5, строки 12-15]
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно

Документы дела:
{sources}

{additional_context}
"""
        
        human_template = "{question}"
        
        prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(human_template)
        ])
        
        # Format prompt
        additional_context = context or ""
        formatted_prompt = prompt.format_messages(
            sources=sources_text,
            additional_context=additional_context,
            question=query
        )
        
        # Check context size
        prompt_size = sum(len(str(msg.content)) for msg in formatted_prompt)
        if prompt_size > config.MAX_CONTEXT_CHARS:
            logger.warning(f"Prompt size ({prompt_size}) exceeds MAX_CONTEXT_CHARS ({config.MAX_CONTEXT_CHARS})")
        
        # Generate answer with error handling
        try:
            response = self.llm.invoke(formatted_prompt)
            answer = response.content
        except RateLimitError as e:
            logger.error(f"Rate limit error in RAG service for case {case_id}: {e}")
            raise Exception("Превышен лимит запросов к API. Попробуйте позже.")
        except APITimeoutError as e:
            logger.error(f"Timeout error in RAG service for case {case_id}: {e}")
            raise Exception("Превышено время ожидания ответа от API. Попробуйте упростить запрос.")
        except APIError as e:
            logger.error(f"API error in RAG service for case {case_id}: {e}")
            if "authentication" in str(e).lower() or "api key" in str(e).lower():
                raise Exception("Ошибка аутентификации API. Проверьте API ключ.")
            raise Exception(f"Ошибка API: {str(e)}")
        except LangChainException as e:
            logger.error(f"LangChain error in RAG service for case {case_id}: {e}")
            raise Exception(f"Ошибка при обработке запроса: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in RAG service for case {case_id}: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка: {str(e)}")
        
        # Format sources
        sources = self.format_sources(relevant_docs)
        
        return answer, sources
    
    def generate_answer(
        self,
        case_id: str,
        query: str,
        chat_history: List[Dict[str, str]] = None,
        k: int = 5,
        retrieval_strategy: str = "simple",
        use_memory: bool = True
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer with chat history support
        
        Args:
            case_id: Case identifier
            query: User query
            chat_history: Previous chat messages
            k: Number of chunks to retrieve
            
        Returns:
            Tuple of (answer, sources)
        """
        # Retrieve relevant chunks using specified strategy
        relevant_docs = self.retrieve_context(case_id, query, k=k, retrieval_strategy=retrieval_strategy)
        
        if not relevant_docs:
            return "Не найдено релевантной информации в документах дела.", []
        
        # Format sources with context limit
        sources_text = self.format_sources_for_prompt(relevant_docs)
        
        # Format chat history using memory if enabled
        history_text = ""
        if use_memory and chat_history:
            # Load history into memory
            self.memory_service.load_history_into_memory(case_id, chat_history, memory_type="summary")
            # Get memory variables
            memory_vars = self.memory_service.get_memory_variables(case_id, memory_type="summary")
            history_text = memory_vars.get("chat_history", "")
        elif chat_history:
            # Fallback: simple history formatting
            history_parts = []
            for msg in chat_history[-5:]:  # Last 5 messages
                role = "Пользователь" if msg.get("role") == "user" else "Ассистент"
                history_parts.append(f"{role}: {msg.get('content', '')}")
            history_text = "\n".join(history_parts)
        
        # Create prompt
        system_template = """Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе предоставленных документов дела.

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [Документ: filename.pdf, стр. 5, строки 12-15]
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно

Документы дела:
{sources}

{history}
"""
        
        human_template = "{question}"
        
        prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(human_template)
        ])
        
        # Format prompt
        formatted_prompt = prompt.format_messages(
            sources=sources_text,
            history=history_text,
            question=query
        )
        
        # Check context size
        prompt_size = sum(len(str(msg.content)) for msg in formatted_prompt)
        if prompt_size > config.MAX_CONTEXT_CHARS:
            logger.warning(f"Prompt size ({prompt_size}) exceeds MAX_CONTEXT_CHARS ({config.MAX_CONTEXT_CHARS}) for case {case_id}")
        
        # Generate answer with error handling
        try:
            logger.info(f"Generating answer for case {case_id}, query length: {len(query)}, context size: {prompt_size}")
            response = self.llm.invoke(formatted_prompt)
            answer = response.content
            logger.info(f"Successfully generated answer for case {case_id}, answer length: {len(answer)}")
        except RateLimitError as e:
            logger.error(f"Rate limit error in RAG service for case {case_id}: {e}")
            raise Exception("Превышен лимит запросов к API. Попробуйте позже.")
        except APITimeoutError as e:
            logger.error(f"Timeout error in RAG service for case {case_id}: {e}")
            raise Exception("Превышено время ожидания ответа от API. Попробуйте упростить запрос.")
        except APIError as e:
            logger.error(f"API error in RAG service for case {case_id}: {e}")
            if "authentication" in str(e).lower() or "api key" in str(e).lower():
                raise Exception("Ошибка аутентификации API. Проверьте API ключ.")
            raise Exception(f"Ошибка API: {str(e)}")
        except LangChainException as e:
            logger.error(f"LangChain error in RAG service for case {case_id}: {e}")
            raise Exception(f"Ошибка при обработке запроса: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in RAG service for case {case_id}: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка: {str(e)}")
        
        # Format sources
        sources = self.format_sources(relevant_docs)
        
        return answer, sources

