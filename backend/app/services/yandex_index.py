"""Yandex AI Studio Vector Store service for search indexes"""
import requests
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from app.config import config

logger = logging.getLogger(__name__)

# ВАЖНО: Используйте Vector Store API для создания поисковых индексов
# Документация: https://yandex.cloud/docs/ai-studio/concepts/vector-store
# Старый Index API (/foundationModels/v1/indexes) устарел и возвращает 404
# Vector Store API работает через:
# 1. Загрузку файлов в Vector Store
# 2. Создание индекса из загруженных файлов
# 3. Использование индекса через Responses API или Realtime API с инструментом file_search


class YandexIndexService:
    """
    Service for Yandex AI Studio Vector Store (Search Index) using ML SDK
    
    ВАЖНО: Используйте Yandex Cloud ML SDK для работы с Search Indexes
    SDK Reference: https://yandex.cloud/docs/ai-studio/sdk-ref/
    GitHub: https://github.com/yandex-cloud/yandex-cloud-ml-sdk
    
    SDK поддерживает:
    - sdk.search_indexes - работа с search indexes
    - sdk.files - загрузка файлов для Vector Store
    - sdk.assistants - создание ассистентов с инструментом file_search
    
    Документация Vector Store: https://yandex.cloud/docs/ai-studio/concepts/vector-store
    """
    
    def __init__(self):
        """Initialize Yandex Vector Store service using ML SDK"""
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
                "Yandex Vector Store service will not work."
            )
            self.sdk = None
            return
        
        if not self.folder_id:
            logger.warning(
                "YANDEX_FOLDER_ID not set. "
                "Yandex Vector Store service requires folder_id."
            )
            self.sdk = None
            return
        
        # Инициализируем SDK
        try:
            auth = APIKeyAuth(self.api_key) if self.use_api_key else self.iam_token
            self.sdk = YCloudML(folder_id=self.folder_id, auth=auth)
            logger.info("✅ Yandex Cloud ML SDK initialized for Vector Store")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML SDK: {e}", exc_info=True)
            self.sdk = None
    
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
        Create new Vector Store search index for case using ML SDK
        
        ВАЖНО: Используйте Yandex Cloud ML SDK для работы с Search Indexes
        SDK Reference: https://yandex.cloud/docs/ai-studio/sdk-ref/
        SDK поддерживает: sdk.search_indexes для работы с индексами
        
        Документация Vector Store: https://yandex.cloud/docs/ai-studio/concepts/vector-store
        
        Args:
            case_id: Case identifier
            name: Optional index name (defaults to index_prefix_case_id)
        
        Returns:
            index_id: ID of created Vector Store index
        
        TODO: Реализовать через SDK:
        - Использовать sdk.search_indexes.create() или sdk.vector_store для создания индекса
        - Проверить примеры использования SDK в репозитории:
          https://github.com/yandex-cloud/yandex-cloud-ml-sdk/tree/master/examples
        - Для Vector Store может потребоваться сначала загрузить файлы через sdk.files
        """
        self._ensure_sdk()
        
        index_name = name or f"{self.index_prefix}_{case_id}"
        
        # TODO: Реализовать через SDK
        # Временная заглушка - старый метод возвращает 404
        # Нужно обновить на использование SDK:
        # try:
        #     # Вариант 1: Если SDK поддерживает search_indexes напрямую
        #     index = self.sdk.search_indexes.create(
        #         name=index_name,
        #         description=f"Index for case {case_id}"
        #     )
        #     index_id = index.id
        #     
        #     # Вариант 2: Если нужно использовать vector_store
        #     # vector_store = self.sdk.vector_store.create(...)
        #     
        #     logger.info(f"✅ Created index {index_id} for case {case_id}")
        #     return index_id
        # except Exception as e:
        #     logger.error(f"Error creating index via SDK: {e}", exc_info=True)
        #     raise
        
        # Временная реализация - возвращает ошибку
        logger.error(
            "Index creation через SDK не реализован. "
            "Старый метод через REST API возвращает 404. "
            "Пожалуйста, реализуйте через SDK согласно документации."
        )
        raise NotImplementedError(
            "Создание индекса требует реализации через Yandex Cloud ML SDK. "
            "Проверьте документацию SDK: https://yandex.cloud/docs/ai-studio/sdk-ref/"
        )
    
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

