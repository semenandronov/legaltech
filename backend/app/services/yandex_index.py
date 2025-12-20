"""Yandex AI Studio Index service for vector store / search index"""
import requests
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from app.config import config

logger = logging.getLogger(__name__)


class YandexIndexService:
    """Service for Yandex AI Studio Vector Store / Search Index"""
    
    def __init__(self):
        """Initialize Yandex Index service"""
        self.api_key = config.YANDEX_API_KEY
        self.iam_token = config.YANDEX_IAM_TOKEN
        self.folder_id = config.YANDEX_FOLDER_ID
        self.index_prefix = getattr(config, 'YANDEX_INDEX_PREFIX', 'legal_ai_vault')
        
        # Используем API ключ если есть, иначе IAM токен
        self.auth_token = self.api_key or self.iam_token
        self.use_api_key = bool(self.api_key)
        
        if not self.auth_token:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "Yandex Index service will not work."
            )
        
        if not self.folder_id:
            logger.warning(
                "YANDEX_FOLDER_ID not set. "
                "Yandex Index service requires folder_id."
            )
        
        # Base URL for Yandex AI Studio API
        self.base_url = "https://llm.api.cloud.yandex.net"
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API requests"""
        if self.use_api_key:
            auth_header = f"Api-Key {self.api_key}"
        else:
            auth_header = f"Bearer {self.iam_token}"
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        
        if self.folder_id:
            headers["x-folder-id"] = self.folder_id
        
        return headers
    
    def create_index(self, case_id: str, name: str = None) -> str:
        """
        Create new search index for case
        
        Args:
            case_id: Case identifier
            name: Optional index name (defaults to index_prefix_case_id)
        
        Returns:
            index_id: ID of created index
        
        Note: This is a placeholder implementation. Actual API endpoint
        should be verified with Yandex AI Studio documentation.
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        index_name = name or f"{self.index_prefix}_{case_id}"
        
        # TODO: Verify actual API endpoint with Yandex AI Studio documentation
        # This is a placeholder based on typical index API patterns
        url = f"{self.base_url}/foundationModels/v1/indexes"
        
        payload = {
            "name": index_name,
            "description": f"Index for case {case_id}",
            "folder_id": self.folder_id
        }
        
        try:
            logger.info(f"Creating index '{index_name}' for case {case_id}")
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract index_id from response
            # Actual response format should be verified with documentation
            index_id = result.get("id") or result.get("index_id") or result.get("indexId")
            
            if not index_id:
                logger.error(f"Unexpected response format from Yandex Index API: {result}")
                raise ValueError("Failed to extract index_id from API response")
            
            logger.info(f"✅ Created index {index_id} for case {case_id}")
            return index_id
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating index via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при создании индекса через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error creating index: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при создании индекса: {str(e)}")
    
    def add_documents(self, index_id: str, documents: List[Document]) -> Dict[str, Any]:
        """
        Add documents to index
        
        Args:
            index_id: Index identifier
            documents: List of Document objects to add
        
        Returns:
            Dictionary with result information
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint and document format
        # This is a placeholder based on typical index API patterns
        url = f"{self.base_url}/foundationModels/v1/indexes/{index_id}/documents"
        
        # Convert LangChain Documents to API format
        documents_data = []
        for doc in documents:
            doc_data = {
                "text": doc.page_content,
                "metadata": doc.metadata
            }
            documents_data.append(doc_data)
        
        payload = {
            "documents": documents_data
        }
        
        try:
            logger.info(f"Adding {len(documents)} documents to index {index_id}")
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"✅ Added {len(documents)} documents to index {index_id}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error adding documents via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при добавлении документов через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error adding documents: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при добавлении документов: {str(e)}")
    
    def search(self, index_id: str, query: str, k: int = 5) -> List[Document]:
        """
        Search documents in index
        
        Args:
            index_id: Index identifier
            query: Search query text
            k: Number of results to return
        
        Returns:
            List of Document objects with relevance scores in metadata
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint and response format
        # This is a placeholder based on typical search API patterns
        url = f"{self.base_url}/foundationModels/v1/indexes/{index_id}/search"
        
        payload = {
            "query": query,
            "top": k
        }
        
        try:
            logger.debug(f"Searching index {index_id} with query: {query[:100]}...")
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Convert API response to LangChain Documents
            documents = []
            
            # Actual response format should be verified with documentation
            # Expected format: {"results": [{"text": "...", "metadata": {...}, "score": 0.95}, ...]}
            results = result.get("results") or result.get("items") or result.get("documents") or []
            
            for item in results:
                text = item.get("text") or item.get("content") or ""
                metadata = item.get("metadata") or {}
                score = item.get("score") or item.get("relevance") or 0.0
                
                # Add score to metadata
                metadata["similarity_score"] = float(score)
                metadata["distance_score"] = 1.0 - float(score)  # Convert similarity to distance-like
                
                documents.append(Document(page_content=text, metadata=metadata))
            
            logger.debug(f"Found {len(documents)} documents for query in index {index_id}")
            return documents
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching index via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при поиске в индексе через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error searching index: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при поиске в индексе: {str(e)}")
    
    def delete_index(self, index_id: str) -> None:
        """
        Delete index
        
        Args:
            index_id: Index identifier to delete
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint
        url = f"{self.base_url}/foundationModels/v1/indexes/{index_id}"
        
        try:
            logger.info(f"Deleting index {index_id}")
            response = requests.delete(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Deleted index {index_id}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error deleting index via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при удалении индекса через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error deleting index: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при удалении индекса: {str(e)}")
    
    def get_index_id(self, case_id: str, db_session=None) -> Optional[str]:
        """
        Get index_id for case from database
        
        Args:
            case_id: Case identifier
            db_session: Database session (optional, if not provided will try to get from context)
        
        Returns:
            index_id if found, None otherwise
        """
        if not db_session:
            # Try to get from database if session not provided
            # This is a fallback - ideally db_session should be passed
            try:
                from app.utils.database import SessionLocal
                db = SessionLocal()
                try:
                    from app.models.case import Case
                    case = db.query(Case).filter(Case.id == case_id).first()
                    return case.yandex_index_id if case else None
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Could not get index_id from database: {e}")
                return None
        
        try:
            from app.models.case import Case
            case = db_session.query(Case).filter(Case.id == case_id).first()
            return case.yandex_index_id if case else None
        except Exception as e:
            logger.warning(f"Could not get index_id from database: {e}")
            return None
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли сервис индексов"""
        return bool(self.auth_token and self.folder_id)


class YandexIndexRetriever(BaseRetriever):
    """LangChain retriever for Yandex AI Studio Index"""
    
    index_service: YandexIndexService
    index_id: str
    k: int = 5
    db_session: Optional[Any] = None
    
    def __init__(self, index_service: YandexIndexService, index_id: str, k: int = 5, db_session: Optional[Any] = None):
        """Initialize retriever"""
        super().__init__()
        self.index_service = index_service
        self.index_id = index_id
        self.k = k
        self.db_session = db_session
    
    def _get_relevant_documents(self, query: str) -> List[Document]:
        """Get relevant documents for query"""
        return self.index_service.search(self.index_id, query, k=self.k)
    
    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        """Async get relevant documents (uses sync implementation)"""
        return self._get_relevant_documents(query)

