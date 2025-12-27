"""RAG (Retrieval Augmented Generation) service"""
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from app.config import config
from app.services.document_processor import DocumentProcessor
# YandexAssistantService imported conditionally - only for yandex vector store
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
        
        # Using direct RAG with YandexGPT + pgvector
        logger.info("✅ Using direct RAG with YandexGPT + pgvector")
    
    def retrieve_context(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: str = "simple",
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve relevant context for a query using Yandex Index
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            retrieval_strategy: Strategy to use ('simple', 'multi_query', 'compression', 'ensemble')
            db: Optional database session
            
        Returns:
            List of relevant Document objects
        """
        try:
            if retrieval_strategy == "multi_query":
                docs = self.retriever_service.retrieve_with_multi_query(case_id, query, k=k, db=db)
            elif retrieval_strategy == "compression":
                docs = self.retriever_service.retrieve_with_compression(case_id, query, k=k*2, db=db)  # Get more before compression
            elif retrieval_strategy == "ensemble":
                docs = self.retriever_service.retrieve_with_ensemble(case_id, query, k=k, db=db)
            else:
                # Default: simple retrieval using Yandex Index
                docs = self.document_processor.retrieve_relevant_chunks(
                    case_id=case_id,
                    query=query,
                    k=k,
                    db=db
                )
            
            # Ensure we return a list, even if empty
            if docs is None:
                logger.warning(f"Retrieval returned None for case {case_id}, returning empty list")
                return []
            
            # Filter out None or invalid documents
            valid_docs = [doc for doc in docs if doc is not None and hasattr(doc, 'page_content')]
            
            if not valid_docs:
                logger.warning(f"No valid documents retrieved for case {case_id} with query: {query[:100]}")
            
            return valid_docs
        except Exception as e:
            logger.error(f"Error retrieving context for case {case_id}: {e}", exc_info=True)
            return []
    
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
        k: int = 5,
        db: Optional[Session] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer with source references
        
        Uses direct RAG with pgvector + YandexGPT (no Assistant API).
        
        Args:
            case_id: Case identifier
            query: User query
            context: Additional context (optional)
            k: Number of chunks to retrieve
            db: Optional database session
            history: Optional chat history in format [{"role": "user|assistant", "content": "..."}, ...]
            
        Returns:
            Tuple of (answer, sources)
        """
        # Проверка на разговорные вопросы - даем дружелюбный ответ
        query_lower = query.lower().strip()
        conversational_questions = {
            "как дела": "Спасибо, всё хорошо! Готов помочь вам с анализом документов дела. Задайте вопрос о документах, и я найду нужную информацию.",
            "как поживаешь": "Спасибо, отлично! Чем могу помочь с вашим делом?",
            "привет": "Привет! Готов помочь с анализом документов. Что вас интересует?",
            "здравствуй": "Здравствуйте! Чем могу помочь с вашим делом?",
            "hello": "Hello! I'm ready to help you analyze your case documents. What would you like to know?",
            "hi": "Hi! How can I help you with your case?",
        }
        
        for key, response in conversational_questions.items():
            if query_lower == key or query_lower.startswith(key + " "):
                return response, []
        
        # Use direct RAG with pgvector + YandexGPT
        return self._generate_with_direct_rag(case_id, query, k, db, history)
    
    def _generate_with_direct_rag(
        self,
        case_id: str,
        query: str,
        k: int,
        db: Optional[Session],
        history: Optional[List[Dict[str, str]]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Generate using direct RAG with pgvector + YandexGPT"""
        from app.services.yandex_llm import ChatYandexGPT
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        # Retrieve relevant documents
        documents = self.retrieve_context(case_id, query, k=k, db=db)
        
        if not documents:
            return "Извините, не удалось найти релевантные документы для вашего запроса.", []
        
        # Format context from documents
        context = self.format_sources_for_prompt(documents)
        
        # Prepare messages
        messages = []
        messages.append(SystemMessage(content="""Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе предоставленных документов.

КРИТИЧЕСКИ ВАЖНО:
- Ты ДОЛЖЕН отвечать на ВСЕ вопросы пользователя о документах дела
- НЕ отказывайся отвечать, даже если вопрос кажется сложным или требует анализа
- Твоя задача - помочь пользователю понять содержание документов
- Анализируй документы, извлекай факты, составляй хронологии, находи связи между событиями
- Ты работаешь с юридическими документами, которые уже загружены в систему - это безопасно и допустимо

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [1][2][3] прямо в тексте ответа
- Номера источников соответствуют порядку документов: [1] - первый документ, [2] - второй и т.д.
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно
- НЕ пиши "Источник 1", "Источник 2" - только [1][2][3]
- Составляй хронологии событий, анализируй риски, находи противоречия - это твоя работа"""))
        
        # Add history
        if history:
            for msg in history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current query with context
        user_message = f"""Используй следующие документы для ответа:

{context}

Вопрос: {query}

Ответ (обязательно укажи источники):"""
        messages.append(HumanMessage(content=user_message))
        
        # Generate answer using YandexGPT
        llm = ChatYandexGPT()
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, 'content') else str(response)
        
        # Format sources
        sources = self.format_sources(documents)
        
        return answer, sources
    

