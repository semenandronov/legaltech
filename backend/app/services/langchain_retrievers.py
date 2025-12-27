"""Advanced LangChain retrievers for Legal AI Vault"""
from typing import List, Optional
from sqlalchemy.orm import Session
import logging

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from app.config import config
from app.services.document_processor import DocumentProcessor
# Removed YandexGPT import - using GigaChat via llm_factory

logger = logging.getLogger(__name__)

# Legal multi-query prompt for generating query variations
LEGAL_MULTI_QUERY_PROMPT = PromptTemplate(
    input_variables=["question"],
    template="""Ты эксперт по юридическим документам. Разбей следующий запрос на 4 варианта для точного поиска:

Оригинальный запрос: {question}

Создай 4 варианта запроса:
1. Прямой запрос (точная формулировка)
2. Синонимы юридических терминов (используй профессиональную терминологию)
3. Расширенный контекст (добавь связанные понятия)
4. Обратный запрос (что НЕ относится к теме, для исключения нерелевантных результатов)

Верни только 4 варианта запросов, каждый с новой строки, без нумерации и пояснений.
""",
)

# Try to import advanced retrievers with multiple fallback strategies
MultiQueryRetriever = None
ContextualCompressionRetriever = None
EnsembleRetriever = None
LLMChainExtractor = None

try:
    # LangChain 1.x - try langchain_classic first for MultiQueryRetriever
    from langchain_classic.retrievers import MultiQueryRetriever
    logger.debug("MultiQueryRetriever imported from langchain_classic")
except ImportError:
    try:
        from langchain.retrievers.multi_query import MultiQueryRetriever
        logger.debug("MultiQueryRetriever imported from langchain.retrievers.multi_query")
    except ImportError:
        logger.warning("MultiQueryRetriever not available")

try:
    # Try langchain_core.retrievers for compression retriever
    from langchain_core.retrievers import ContextualCompressionRetriever
    logger.debug("ContextualCompressionRetriever imported from langchain_core")
except ImportError:
    try:
        from langchain.retrievers import ContextualCompressionRetriever
        logger.debug("ContextualCompressionRetriever imported from langchain.retrievers")
    except ImportError:
        logger.warning("ContextualCompressionRetriever not available")

try:
    # Try langchain_core.retrievers for ensemble retriever
    from langchain_core.retrievers import EnsembleRetriever
    logger.debug("EnsembleRetriever imported from langchain_core")
except ImportError:
    try:
        from langchain.retrievers import EnsembleRetriever
        logger.debug("EnsembleRetriever imported from langchain.retrievers")
    except ImportError:
        logger.warning("EnsembleRetriever not available")

try:
    # Try to import LLMChainExtractor
    from langchain_core.retrievers.document_compressors import LLMChainExtractor
    logger.debug("LLMChainExtractor imported from langchain_core")
except ImportError:
    try:
        from langchain.retrievers.document_compressors import LLMChainExtractor
        logger.debug("LLMChainExtractor imported from langchain.retrievers")
    except ImportError:
        logger.warning("LLMChainExtractor not available")

if not all([MultiQueryRetriever, ContextualCompressionRetriever, EnsembleRetriever, LLMChainExtractor]):
    logger.info("Some advanced retrievers are not available, fallback methods will be used")


class AdvancedRetrieverService:
    """Service for advanced retrieval strategies"""
    
    def __init__(self, document_processor: DocumentProcessor):
        """Initialize retriever service"""
        self.document_processor = document_processor
        # Use GigaChat via factory
        from app.services.llm_factory import create_llm
        self.llm = create_llm(temperature=0.7)
    
    def _get_base_documents(self, case_id: str, query: str, k: int = 5, db: Optional[Session] = None) -> List[Document]:
        """
        Get base documents for a case using Yandex Index
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of documents to retrieve
            db: Optional database session
            
        Returns:
            List of documents
        """
        return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k, db=db)
    
    def retrieve_with_multi_query(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve documents using MultiQueryRetriever approach
        
        Generates multiple query variations to improve retrieval quality.
        Uses legal-specific prompt for query expansion.
        
        If MultiQueryRetriever from LangChain is available, uses it directly.
        Otherwise, implements manual multi-query logic.
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve per query (total will be deduplicated)
            db: Optional database session
            
        Returns:
            List of relevant documents (deduplicated)
        """
        # Try to use LangChain MultiQueryRetriever if available
        if MultiQueryRetriever is not None:
            try:
                # Get base retriever from document processor
                base_retriever = self.document_processor.vector_store.get_retriever(case_id, k=k)
                
                # Create MultiQueryRetriever with legal prompt
                multi_retriever = MultiQueryRetriever.from_llm(
                    llm=self.llm,
                    retriever=base_retriever,
                    prompt=LEGAL_MULTI_QUERY_PROMPT
                )
                
                # Retrieve documents
                docs = multi_retriever.get_relevant_documents(query)
                logger.info(f"MultiQueryRetriever: {len(docs)} documents for case {case_id}")
                return docs
                
            except Exception as e:
                logger.warning(f"Error using LangChain MultiQueryRetriever: {e}. Using manual implementation.", exc_info=True)
        
        # Manual implementation: generate queries and retrieve
        try:
            # Generate query variations using LLM with legal prompt
            from langchain_core.messages import HumanMessage
            messages = [HumanMessage(content=LEGAL_MULTI_QUERY_PROMPT.format(question=query))]
            response = self.llm.invoke(messages)
            
            # Parse response to get query variations
            query_text = response.content if hasattr(response, 'content') else str(response)
            # Split by newlines and filter empty lines
            queries = [q.strip() for q in query_text.split('\n') if q.strip() and len(q.strip()) > 10]
            
            # Add original query as first variation (if not already included)
            if query not in queries:
                queries = [query] + queries[:3]  # Original + up to 3 variations
            else:
                queries = queries[:4]  # Use first 4 queries
            
            logger.debug(f"Generated {len(queries)} query variations for case {case_id}: {queries[:2]}...")
            
            # Retrieve documents for each query variation
            all_documents = []
            seen_content = set()
            
            for query_variation in queries:
                docs = self._get_base_documents(case_id, query_variation, k=k, db=db)
                for doc in docs:
                    # Use first 100 chars of content as unique identifier for deduplication
                    content_hash = doc.page_content[:100]
                    if content_hash not in seen_content:
                        seen_content.add(content_hash)
                        all_documents.append(doc)
                        if len(all_documents) >= k * 2:  # Limit total documents
                            break
                if len(all_documents) >= k * 2:
                    break
            
            logger.info(f"Multi-query retrieval: {len(queries)} queries → {len(all_documents)} unique documents for case {case_id}")
            return all_documents[:k * 2]  # Return more documents, compression will filter if needed
            
        except Exception as e:
            logger.warning(f"Error in multi-query retrieval for case {case_id}: {e}. Falling back to simple retrieval.", exc_info=True)
            return self._get_base_documents(case_id, query, k=k, db=db)
    
    def retrieve_with_compression(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve documents using ContextualCompressionRetriever
        
        This compresses retrieved documents to only relevant parts using LLM.
        Uses GigaChat for compression to save tokens and improve relevance.
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve (before compression)
            
        Returns:
            List of compressed relevant documents
        """
        # Try to use LangChain ContextualCompressionRetriever if available
        if ContextualCompressionRetriever is not None and LLMChainExtractor is not None:
            try:
                # Get base retriever from document processor
                base_retriever = self.document_processor.vector_store.get_retriever(case_id, k=k*2)
                
                # Create compressor with GigaChat
                compressor = LLMChainExtractor.from_llm(self.llm)
                
                # Create compression retriever
                compression_retriever = ContextualCompressionRetriever(
                    base_compressor=compressor,
                    base_retriever=base_retriever
                )
                
                # Retrieve and compress documents
                docs = compression_retriever.get_relevant_documents(query)
                logger.info(f"CompressionRetriever: {len(docs)} compressed documents for case {case_id}")
                return docs[:k]
                
            except Exception as e:
                logger.warning(f"Error using LangChain ContextualCompressionRetriever: {e}. Using manual compression.", exc_info=True)
        
        # Manual implementation: get more documents and compress
        # Get more documents initially for compression
        documents = self._get_base_documents(case_id, query, k=k*2, db=db)
        
        # Apply compression if LLMChainExtractor is available
        if LLMChainExtractor is not None and documents:
            try:
                compressor = LLMChainExtractor.from_llm(self.llm)
                compressed_docs = compressor.compress_documents(documents, query)
                logger.info(f"Compressed {len(documents)} to {len(compressed_docs)} documents for case {case_id}")
                return compressed_docs[:k]
            except Exception as e:
                logger.warning(f"Error applying compression for case {case_id}: {e}", exc_info=True)
                return documents[:k]
        
        return documents[:k]
    
    def retrieve_with_ensemble(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve documents using EnsembleRetriever
        
        This combines multiple retrieval strategies
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve
            
        Returns:
            List of relevant documents from ensemble
        """
        # Note: EnsembleRetriever requires LangChain retrievers, which we don't have with Yandex Index API
        # For now, we use direct search (Yandex Index already does optimized semantic search)
        # Future: Could combine multiple search strategies manually if needed
        logger.debug(f"Using direct Yandex Index search for ensemble (case {case_id})")
        return self._get_base_documents(case_id, query, k=k, db=db)
    
    def retrieve_hybrid(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Hybrid retrieval combining multiple strategies
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve
            
        Returns:
            List of relevant documents
        """
        # Use multi-query approach (which now uses direct search) and apply compression
        try:
            # Get documents using multi-query (direct search)
            documents = self.retrieve_with_multi_query(case_id, query, k=k*2, db=db)
            
            # Apply compression if available
            if documents and LLMChainExtractor is not None:
                compressor = LLMChainExtractor.from_llm(self.llm)
                try:
                    compressed_docs = compressor.compress_documents(documents, query)
                    logger.info(f"Hybrid retrieval compressed {len(documents)} to {len(compressed_docs)} documents for case {case_id}")
                    return compressed_docs[:k]
                except Exception as e:
                    logger.warning(f"Error applying compression in hybrid retrieval for case {case_id}: {e}")
                    return documents[:k]
            
            return documents[:k]
        except Exception as e:
            logger.error(f"Error in hybrid retrieval for case {case_id}: {e}")
            # Fallback to simple retrieval
            return self._get_base_documents(case_id, query, k=k, db=db)
