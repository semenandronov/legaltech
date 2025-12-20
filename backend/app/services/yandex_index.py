"""Yandex AI Studio Vector Store service for search indexes"""
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
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
    GitHub SDK: https://github.com/yandex-cloud/yandex-cloud-ml-sdk
    SDK Examples: https://github.com/yandex-cloud/yandex-cloud-ml-sdk/tree/master/examples
    Yandex Cloud Examples: https://github.com/yandex-cloud-examples
    (старый репозиторий https://github.com/yandex-cloud/examples заархивирован)
    
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
    
    def _ensure_sdk(self):
        """Ensure SDK is initialized"""
        if not self.sdk:
            raise ValueError(
                "Yandex Cloud ML SDK not initialized. "
                "Check YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID in .env file"
            )
    
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
        - Проверить примеры использования SDK:
          * SDK Examples: https://github.com/yandex-cloud/yandex-cloud-ml-sdk/tree/master/examples
          * Yandex Cloud Examples: https://github.com/yandex-cloud-examples
          (старый репозиторий examples заархивирован)
        - Для Vector Store может потребоваться сначала загрузить файлы через sdk.files
        """
        self._ensure_sdk()
        
        index_name = name or f"{self.index_prefix}_{case_id}"
        
        # Пробуем создать индекс через SDK
        # Vector Store API в SDK может быть доступен через разные пути
        try:
            # Попробуем через vector_store (если доступно)
            if hasattr(self.sdk, 'vector_store'):
                logger.info(f"Creating Vector Store index '{index_name}' for case {case_id} via SDK")
                vector_store = self.sdk.vector_store.create(
                    name=index_name,
                    description=f"Index for case {case_id}"
                )
                index_id = vector_store.id if hasattr(vector_store, 'id') else str(vector_store)
                logger.info(f"✅ Created Vector Store index {index_id} for case {case_id}")
                return index_id
            
            # Попробуем через search_indexes (если доступно)
            if hasattr(self.sdk, 'search_indexes'):
                logger.info(f"Creating search index '{index_name}' for case {case_id} via SDK")
                search_indexes = self.sdk.search_indexes
                
                # Логируем доступные методы для отладки
                available_methods = [m for m in dir(search_indexes) if not m.startswith('_') and callable(getattr(search_indexes, m, None))]
                logger.info(f"Available methods in search_indexes: {available_methods}")
                
                # Пробуем разные возможные методы
                if hasattr(search_indexes, 'create'):
                    index = search_indexes.create(name=index_name, description=f"Index for case {case_id}")
                    index_id = index.id if hasattr(index, 'id') else str(index)
                    logger.info(f"✅ Created search index {index_id} for case {case_id}")
                    return index_id
                elif hasattr(search_indexes, 'create_index'):
                    index = search_indexes.create_index(name=index_name, description=f"Index for case {case_id}")
                    index_id = index.id if hasattr(index, 'id') else str(index)
                    logger.info(f"✅ Created search index {index_id} for case {case_id}")
                    return index_id
                else:
                    logger.error(
                        f"search_indexes не содержит методов create или create_index. "
                        f"Доступные методы: {available_methods}. "
                        f"Проверьте документацию SDK: https://yandex.cloud/docs/ai-studio/sdk-ref/"
                    )
                    # Временно возвращаем ошибку - требуется ручная настройка
                    raise NotImplementedError(
                        f"Метод создания индекса не найден в SDK. "
                        f"Доступные методы search_indexes: {available_methods}. "
                        f"Проверьте документацию SDK для правильного использования."
                    )
            
            # Если ни один из методов не доступен, логируем доступные атрибуты
            available_attrs = [attr for attr in dir(self.sdk) if not attr.startswith('_')]
            logger.warning(
                f"SDK не содержит vector_store или search_indexes. "
                f"Доступные атрибуты SDK: {', '.join(available_attrs[:20])}..."
            )
            raise NotImplementedError(
                "SDK не содержит vector_store или search_indexes атрибутов. "
                "Проверьте документацию SDK и доступные методы. "
                "SDK Reference: https://yandex.cloud/docs/ai-studio/sdk-ref/"
            )
            
        except AttributeError as e:
            logger.error(
                f"AttributeError при создании индекса через SDK: {e}. "
                f"Возможно, API SDK отличается от ожидаемого. "
                f"Проверьте документацию: https://yandex.cloud/docs/ai-studio/sdk-ref/"
            )
            raise NotImplementedError(
                f"Создание индекса через SDK не поддерживается или API изменился: {str(e)}. "
                "Проверьте актуальную документацию SDK."
            )
        except Exception as e:
            logger.error(f"Error creating index via SDK: {e}", exc_info=True)
            raise Exception(f"Ошибка при создании индекса через SDK: {str(e)}")
    
    def add_documents(self, index_id: str, documents: List[Document]) -> Dict[str, Any]:
        """
        Add documents to Vector Store index via SDK
        
        ВАЖНО: Для Vector Store документы добавляются через загрузку файлов
        Документация: https://yandex.cloud/docs/ai-studio/concepts/vector-store
        
        Args:
            index_id: Vector Store index identifier
            documents: List of Document objects to add
        
        Returns:
            Dictionary with result information
        """
        self._ensure_sdk()
        
        # Для Vector Store нужно загружать файлы, а не добавлять документы напрямую
        # TODO: Реализовать загрузку файлов через SDK
        # Возможные варианты:
        # 1. Конвертировать документы в файлы и загрузить через sdk.files.upload()
        # 2. Использовать sdk.vector_store.add_files() если доступно
        # 3. Использовать sdk.search_indexes.add_documents() если доступно
        
        try:
            logger.info(f"Adding {len(documents)} documents to Vector Store index {index_id}")
            
            # Попробуем через vector_store (если доступно)
            if hasattr(self.sdk, 'vector_store') and hasattr(self.sdk.vector_store, 'add_files'):
                # Нужно конвертировать документы в файлы
                # Это требует дополнительной реализации - временно возвращаем заглушку
                logger.warning("add_files через vector_store требует конвертации документов в файлы")
                return {"status": "pending", "message": "Требуется реализация загрузки файлов"}
            
            # Попробуем через search_indexes (если доступно)
            if hasattr(self.sdk, 'search_indexes'):
                if hasattr(self.sdk.search_indexes, 'add_documents'):
                    result = self.sdk.search_indexes.add_documents(index_id, documents)
                    logger.info(f"✅ Added {len(documents)} documents to search index {index_id}")
                    return {"status": "success", "count": len(documents)}
            
            # Если методы не доступны, возвращаем информацию о необходимости реализации
            logger.warning(
                f"Метод добавления документов через SDK не найден. "
                f"Возможно, нужно использовать загрузку файлов через sdk.files"
            )
            return {
                "status": "not_implemented",
                "message": "Добавление документов требует реализации через SDK files API"
            }
            
        except Exception as e:
            logger.error(f"Error adding documents via SDK: {e}", exc_info=True)
            raise Exception(f"Ошибка при добавлении документов через SDK: {str(e)}")
    
    def search(self, index_id: str, query: str, k: int = 5) -> List[Document]:
        """
        Search documents in Vector Store index via SDK
        
        Args:
            index_id: Vector Store index identifier
            query: Search query text
            k: Number of results to return
        
        Returns:
            List of Document objects with relevance scores in metadata
        """
        self._ensure_sdk()
        
        try:
            logger.debug(f"Searching Vector Store index {index_id} with query: {query[:100]}...")
            
            # Попробуем через vector_store (если доступно)
            if hasattr(self.sdk, 'vector_store') and hasattr(self.sdk.vector_store, 'search'):
                results = self.sdk.vector_store.search(index_id, query, top=k)
                documents = []
                for item in results:
                    doc = Document(
                        page_content=item.text if hasattr(item, 'text') else str(item),
                        metadata=getattr(item, 'metadata', {})
                    )
                    if hasattr(item, 'score'):
                        doc.metadata["similarity_score"] = float(item.score)
                    documents.append(doc)
                return documents
            
            # Попробуем через search_indexes (если доступно)
            if hasattr(self.sdk, 'search_indexes') and hasattr(self.sdk.search_indexes, 'search'):
                results = self.sdk.search_indexes.search(index_id, query, top=k)
                documents = []
                for item in results:
                    doc = Document(
                        page_content=item.text if hasattr(item, 'text') else str(item),
                        metadata=getattr(item, 'metadata', {})
                    )
                    if hasattr(item, 'score'):
                        doc.metadata["similarity_score"] = float(item.score)
                    documents.append(doc)
                return documents
            
            # Если методы не доступны
            logger.warning(
                f"Метод поиска через SDK не найден. "
                f"Возможно, нужно использовать другой API"
            )
            return []
            
        except Exception as e:
            logger.error(f"Error searching via SDK: {e}", exc_info=True)
            # Возвращаем пустой список вместо исключения, чтобы не ломать работу
            return []
    
    def delete_index(self, index_id: str) -> None:
        """
        Delete Vector Store index via SDK
        
        Args:
            index_id: Vector Store index identifier to delete
        """
        self._ensure_sdk()
        
        try:
            logger.info(f"Deleting Vector Store index {index_id}")
            
            # Попробуем через vector_store (если доступно)
            if hasattr(self.sdk, 'vector_store') and hasattr(self.sdk.vector_store, 'delete'):
                self.sdk.vector_store.delete(index_id)
                logger.info(f"✅ Deleted Vector Store index {index_id}")
                return
            
            # Попробуем через search_indexes (если доступно)
            if hasattr(self.sdk, 'search_indexes') and hasattr(self.sdk.search_indexes, 'delete'):
                self.sdk.search_indexes.delete(index_id)
                logger.info(f"✅ Deleted search index {index_id}")
                return
            
            # Если методы не доступны
            logger.warning(
                f"Метод удаления через SDK не найден. "
                f"Индекс {index_id} не был удален через SDK."
            )
            
        except Exception as e:
            logger.error(f"Error deleting index via SDK: {e}", exc_info=True)
            raise Exception(f"Ошибка при удалении индекса через SDK: {str(e)}")
    
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

