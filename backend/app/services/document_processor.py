"""Document processor service using LangChain"""
from typing import List, Dict, Any, Optional
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.schema import Document
from app.config import config
import os
import logging

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Service for processing documents with LangChain"""
    
    def __init__(self):
        """Initialize document processor"""
        # Text splitter configuration
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Initialize embeddings (using OpenRouter-compatible API)
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            model="text-embedding-ada-002"  # Можно использовать другую модель через OpenRouter
        )
        
        # Vector store will be created per case
        self.vector_stores: Dict[str, Chroma] = {}
    
    def split_documents(
        self,
        text: str,
        filename: str,
        metadata: Dict[str, Any] = None
    ) -> List[Document]:
        """
        Split document text into chunks
        
        Args:
            text: Document text
            filename: Source filename
            metadata: Additional metadata
            
        Returns:
            List of Document objects with metadata
        """
        # Create base metadata
        doc_metadata = {
            "source_file": filename,
            **(metadata or {})
        }
        
        # Split text
        chunks = self.text_splitter.split_text(text)
        
        # Create Document objects with metadata
        documents = []
        for i, chunk_text in enumerate(chunks):
            chunk_metadata = {
                **doc_metadata,
                "chunk_index": i,
                "source_start_line": None,  # Will be calculated if possible
                "source_end_line": None,
                "source_page": None
            }
            documents.append(Document(page_content=chunk_text, metadata=chunk_metadata))
        
        return documents
    
    def create_embeddings(self, documents: List[Document]) -> List[List[float]]:
        """
        Create embeddings for documents
        
        Args:
            documents: List of Document objects
            
        Returns:
            List of embedding vectors
        """
        texts = [doc.page_content for doc in documents]
        embeddings = self.embeddings.embed_documents(texts)
        return embeddings
    
    def _get_persist_directory(self, case_id: str) -> str:
        """
        Get persistent directory for vector store
        
        Args:
            case_id: Case identifier
            
        Returns:
            Path to persistent directory
        """
        # Use persistent directory instead of temp
        base_dir = os.getenv("VECTOR_DB_DIR", os.path.join(os.getcwd(), "vector_db"))
        os.makedirs(base_dir, exist_ok=True)
        return os.path.join(base_dir, f"chroma_{case_id}")
    
    def store_in_vector_db(
        self,
        case_id: str,
        documents: List[Document],
        persist_directory: str = None
    ) -> Chroma:
        """
        Store documents in vector database
        
        Args:
            case_id: Case identifier
            documents: List of Document objects
            persist_directory: Directory to persist vector store (optional)
            
        Returns:
            Chroma vector store instance
        """
        # Use persistent directory if not specified
        if persist_directory is None:
            persist_directory = self._get_persist_directory(case_id)
        
        logger.info(f"Storing vector DB for case {case_id} in {persist_directory}")
        
        # Create or load vector store
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=persist_directory
        )
        
        # Store reference
        self.vector_stores[case_id] = vector_store
        
        return vector_store
    
    def retrieve_relevant_chunks(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        distance_threshold: float = 1.5
    ) -> List[Document]:
        """
        Retrieve relevant document chunks using semantic search
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of chunks to retrieve
            distance_threshold: Maximum distance (ChromaDB returns distance, lower is better)
            
        Returns:
            List of relevant Document objects with scores
        """
        # Try to load vector store if not in memory
        if case_id not in self.vector_stores:
            persist_directory = self._get_persist_directory(case_id)
            if os.path.exists(persist_directory):
                try:
                    logger.info(f"Loading vector DB for case {case_id} from {persist_directory}")
                    self.load_vector_store(case_id, persist_directory)
                except Exception as e:
                    logger.warning(f"Failed to load vector store for case {case_id}: {e}")
                    return []
            else:
                logger.warning(f"Vector store not found for case {case_id} at {persist_directory}")
                return []
        
        vector_store = self.vector_stores[case_id]
        
        try:
            # Perform similarity search with scores
            # ChromaDB returns distance scores (lower = better, typically 0-2 range)
            results = vector_store.similarity_search_with_score(query, k=k)
            
            # Filter by threshold and return documents
            # Since score is distance, we want scores <= threshold (lower distance = better match)
            relevant_docs = []
            for doc, score in results:
                # Convert distance to similarity-like score for metadata (inverse: lower distance = higher similarity)
                similarity_like = 1.0 / (1.0 + float(score)) if score > 0 else 1.0
                
                if score <= distance_threshold:
                    # Add both distance and similarity-like score to metadata
                    doc.metadata["distance_score"] = float(score)
                    doc.metadata["similarity_score"] = similarity_like
                    relevant_docs.append(doc)
            
            if not relevant_docs:
                logger.warning(f"No relevant chunks found for case {case_id} with distance threshold {distance_threshold}")
            
            return relevant_docs
        except Exception as e:
            logger.error(f"Error retrieving chunks for case {case_id}: {e}")
            return []
    
    def load_vector_store(self, case_id: str, persist_directory: Optional[str] = None) -> Chroma:
        """
        Load existing vector store from disk
        
        Args:
            case_id: Case identifier
            persist_directory: Directory where vector store is persisted (optional)
            
        Returns:
            Chroma vector store instance
            
        Raises:
            ValueError: If persist_directory doesn't exist
        """
        if persist_directory is None:
            persist_directory = self._get_persist_directory(case_id)
        
        if not os.path.exists(persist_directory):
            raise ValueError(f"Vector store directory not found: {persist_directory}")
        
        vector_store = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embeddings
        )
        self.vector_stores[case_id] = vector_store
        logger.info(f"Loaded vector store for case {case_id} from {persist_directory}")
        return vector_store

