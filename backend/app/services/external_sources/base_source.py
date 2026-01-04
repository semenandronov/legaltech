"""Base class for external data sources"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class SourceResult:
    """Result from an external source search"""
    content: str  # Main text content
    title: str  # Title of the result
    source_name: str  # Name of the source (e.g., "web", "garant", "consultant")
    url: Optional[str] = None  # URL if available
    relevance_score: float = 0.0  # Relevance score (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "content": self.content,
            "title": self.title,
            "source_name": self.source_name,
            "url": self.url,
            "relevance_score": self.relevance_score,
            "metadata": self.metadata,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


class BaseSource(ABC):
    """Abstract base class for all external data sources"""
    
    def __init__(self, name: str, enabled: bool = True):
        """
        Initialize the source
        
        Args:
            name: Unique identifier for this source
            enabled: Whether this source is enabled
        """
        self.name = name
        self.enabled = enabled
        self._initialized = False
    
    @abstractmethod
    async def initialize(self) -> bool:
        """
        Initialize the source (API connections, auth, etc.)
        
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> List[SourceResult]:
        """
        Search the source for relevant content
        
        Args:
            query: Search query
            max_results: Maximum number of results to return
            filters: Optional filters (e.g., date range, document type)
            
        Returns:
            List of SourceResult objects
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the source is healthy and accessible
        
        Returns:
            True if healthy
        """
        pass
    
    @property
    def is_initialized(self) -> bool:
        """Check if source is initialized"""
        return self._initialized
    
    async def ensure_initialized(self) -> bool:
        """Ensure the source is initialized"""
        if not self._initialized:
            self._initialized = await self.initialize()
        return self._initialized
    
    def get_info(self) -> Dict[str, Any]:
        """Get source information"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "initialized": self._initialized,
        }


class VaultSource(BaseSource):
    """
    Source for searching within case documents (Vault).
    This wraps the existing RAG functionality.
    """
    
    def __init__(self, rag_service=None):
        super().__init__(name="vault", enabled=True)
        self.rag_service = rag_service
    
    async def initialize(self) -> bool:
        """Initialize vault source"""
        # Vault is always available if RAG service is configured
        self._initialized = self.rag_service is not None
        return self._initialized
    
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SourceResult]:
        """
        Search documents in the vault (case documents)
        
        Args:
            query: Search query
            max_results: Maximum results
            filters: Must contain 'case_id' for vault search
            
        Returns:
            List of SourceResult from case documents
        """
        if not self.rag_service:
            logger.warning("Vault source: RAG service not configured")
            return []
        
        case_id = filters.get("case_id") if filters else None
        if not case_id:
            logger.warning("Vault source: case_id not provided in filters")
            return []
        
        db = filters.get("db") if filters else None
        
        try:
            # Use existing RAG retrieval
            documents = self.rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=max_results,
                db=db
            )
            
            results = []
            for doc in documents:
                result = SourceResult(
                    content=doc.page_content,
                    title=doc.metadata.get("source_file", "Document"),
                    source_name="vault",
                    relevance_score=doc.metadata.get("similarity_score", 0.0),
                    metadata={
                        "source_file": doc.metadata.get("source_file"),
                        "source_page": doc.metadata.get("source_page"),
                        "chunk_index": doc.metadata.get("chunk_index"),
                        "case_id": case_id,
                    }
                )
                results.append(result)
            
            logger.info(f"Vault source: found {len(results)} results for query")
            return results
            
        except Exception as e:
            logger.error(f"Vault source search error: {e}", exc_info=True)
            return []
    
    async def health_check(self) -> bool:
        """Check vault health"""
        return self.rag_service is not None

