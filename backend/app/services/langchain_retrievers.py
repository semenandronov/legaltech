"""Advanced LangChain retrievers for Legal AI Vault"""
from typing import List, Optional
import logging
import os

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
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
    
    def _get_base_retriever(self, case_id: str, k: int = 5) -> BaseRetriever:
        """
        Get base retriever for a case
        
        Args:
            case_id: Case identifier
            k: Number of documents to retrieve
            
        Returns:
            Base retriever instance
        """
        # Load vector store if needed
        if case_id not in self.document_processor.vector_stores:
            persist_directory = self.document_processor._get_persist_directory(case_id)
            if os.path.exists(persist_directory):
                try:
                    self.document_processor.load_vector_store(case_id, persist_directory)
                except Exception as e:
                    logger.error(f"Failed to load vector store for case {case_id}: {e}")
                    raise
            else:
                raise ValueError(f"Vector store not found for case {case_id}")
        
        vector_store = self.document_processor.vector_stores[case_id]
        return vector_store.as_retriever(
            search_kwargs={"k": k}
        )
    
    def retrieve_with_multi_query(
        self,
        case_id: str,
        query: str,
        k: int = 5
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
        if MultiQueryRetriever is None:
            logger.warning("MultiQueryRetriever not available, using fallback")
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
        
        try:
            base_retriever = self._get_base_retriever(case_id, k=k)
            
            # Create MultiQueryRetriever
            multi_query_retriever = MultiQueryRetriever.from_llm(
                retriever=base_retriever,
                llm=self.llm
            )
            
            # Retrieve documents
            # Try both old and new API methods with better error handling
            documents = None
            try:
                # New LangChain API (invoke) - preferred method
                if hasattr(multi_query_retriever, 'invoke'):
                    try:
                        documents = multi_query_retriever.invoke(query)
                    except Exception as invoke_error:
                        logger.warning(f"Error with invoke() method for case {case_id}: {invoke_error}")
                        documents = None
                
                # Old LangChain API (get_relevant_documents) - fallback
                if documents is None and hasattr(multi_query_retriever, 'get_relevant_documents'):
                    try:
                        documents = multi_query_retriever.get_relevant_documents(query)
                    except Exception as get_docs_error:
                        logger.warning(f"Error with get_relevant_documents() method for case {case_id}: {get_docs_error}")
                        documents = None
                
                # Try to use as callable - last resort
                if documents is None:
                    try:
                        documents = multi_query_retriever(query)
                    except Exception as callable_error:
                        logger.warning(f"Error calling MultiQueryRetriever as callable for case {case_id}: {callable_error}")
                        documents = None
                
                # If all methods failed, use fallback
                if documents is None:
                    logger.warning(f"All MultiQueryRetriever methods failed for case {case_id}, using fallback")
                    return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
                    
            except Exception as api_error:
                logger.warning(f"Unexpected error calling MultiQueryRetriever API for case {case_id}: {api_error}", exc_info=True)
                # Fallback to simple retrieval
                return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
            
            logger.info(f"MultiQueryRetriever found {len(documents)} documents for case {case_id}")
            return documents
        except Exception as e:
            logger.error(f"Error in MultiQueryRetriever for case {case_id}: {e}", exc_info=True)
            # Fallback to simple retrieval
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
    
    def retrieve_with_compression(
        self,
        case_id: str,
        query: str,
        k: int = 5
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
        if ContextualCompressionRetriever is None or LLMChainExtractor is None:
            logger.warning("ContextualCompressionRetriever not available, using fallback")
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
        
        try:
            base_retriever = self._get_base_retriever(case_id, k=k*2)  # Get more before compression
            
            # Create compressor
            compressor = LLMChainExtractor.from_llm(self.llm)
            
            # Create compression retriever
            compression_retriever = ContextualCompressionRetriever(
                base_compressor=compressor,
                base_retriever=base_retriever
            )
            
            # Retrieve and compress documents
            # Try both old and new API methods
            documents = None
            try:
                if hasattr(compression_retriever, 'invoke'):
                    documents = compression_retriever.invoke(query)
                elif hasattr(compression_retriever, 'get_relevant_documents'):
                    documents = compression_retriever.get_relevant_documents(query)
                else:
                    documents = compression_retriever(query)
            except Exception as api_error:
                logger.warning(f"Error calling ContextualCompressionRetriever API for case {case_id}: {api_error}")
                return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
            
            if documents is None:
                logger.warning(f"ContextualCompressionRetriever returned None for case {case_id}, using fallback")
                return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
            
            logger.info(f"ContextualCompressionRetriever found {len(documents)} documents for case {case_id}")
            return documents
        except Exception as e:
            logger.error(f"Error in ContextualCompressionRetriever for case {case_id}: {e}")
            # Fallback to simple retrieval
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
    
    def retrieve_with_ensemble(
        self,
        case_id: str,
        query: str,
        k: int = 5
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
        if EnsembleRetriever is None:
            logger.warning("EnsembleRetriever not available, using fallback")
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
        
        try:
            # Get base retriever (semantic search)
            semantic_retriever = self._get_base_retriever(case_id, k=k)
            
            # For ensemble, we'd ideally have multiple retrievers
            # For now, we'll use the same retriever with different search params
            # In production, you might add BM25 or keyword-based retriever
            
            # Create ensemble retriever
            ensemble_retriever = EnsembleRetriever(
                retrievers=[semantic_retriever],
                weights=[1.0]  # Equal weight for now
            )
            
            # Retrieve documents
            # Try both old and new API methods
            documents = None
            try:
                if hasattr(ensemble_retriever, 'invoke'):
                    documents = ensemble_retriever.invoke(query)
                elif hasattr(ensemble_retriever, 'get_relevant_documents'):
                    documents = ensemble_retriever.get_relevant_documents(query)
                else:
                    documents = ensemble_retriever(query)
            except Exception as api_error:
                logger.warning(f"Error calling EnsembleRetriever API for case {case_id}: {api_error}")
                return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
            
            if documents is None:
                logger.warning(f"EnsembleRetriever returned None for case {case_id}, using fallback")
                return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
            
            logger.info(f"EnsembleRetriever found {len(documents)} documents for case {case_id}")
            return documents
        except Exception as e:
            logger.error(f"Error in EnsembleRetriever for case {case_id}: {e}")
            # Fallback to simple retrieval
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
    
    def retrieve_hybrid(
        self,
        case_id: str,
        query: str,
        k: int = 5
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
        if LLMChainExtractor is None:
            logger.warning("LLMChainExtractor not available, using fallback")
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
        
        try:
            # Try multi-query first
            multi_query_docs = self.retrieve_with_multi_query(case_id, query, k=k)
            
            # Then apply compression
            if multi_query_docs and LLMChainExtractor is not None:
                compressor = LLMChainExtractor.from_llm(self.llm)
                compressed_docs = []
                for doc in multi_query_docs:
                    try:
                        compressed = compressor.compress_documents([doc], query)
                        compressed_docs.extend(compressed)
                    except:
                        compressed_docs.append(doc)
                
                logger.info(f"Hybrid retrieval found {len(compressed_docs)} documents for case {case_id}")
                return compressed_docs[:k]  # Limit to k documents
            
            return multi_query_docs
        except Exception as e:
            logger.error(f"Error in hybrid retrieval for case {case_id}: {e}")
            # Fallback to simple retrieval
            return self.document_processor.retrieve_relevant_chunks(case_id, query, k=k)
