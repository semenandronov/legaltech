"""Advanced LangChain retrievers for Legal AI Vault"""
from typing import List, Optional
from sqlalchemy.orm import Session
import logging

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from app.config import config
from app.services.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

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
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,
            max_tokens=500
        )
    
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
        Retrieve documents using MultiQueryRetriever
        
        This generates multiple query variations to improve retrieval
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve
            
        Returns:
            List of relevant documents
        """
        # Note: MultiQueryRetriever requires a LangChain retriever, which we don't have with Yandex Index API
        # For now, we use direct search which is already optimized
        # Future: Could implement multi-query logic manually if needed
        logger.debug(f"Using direct Yandex Index search for multi-query (case {case_id})")
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
        
        This compresses retrieved documents to only relevant parts
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of documents to retrieve (before compression)
            
        Returns:
            List of compressed relevant documents
        """
        # Note: ContextualCompressionRetriever requires a LangChain retriever, which we don't have with Yandex Index API
        # Get more documents and apply compression manually if needed
        # For now, we use direct search (Yandex Index already does semantic search)
        logger.debug(f"Using direct Yandex Index search for compression (case {case_id})")
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
                logger.warning(f"Error applying compression for case {case_id}: {e}")
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
