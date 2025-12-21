"""Yandex AI Studio Vector Store service for search indexes"""
import json
import logging
import inspect
import tempfile
import os
import requests
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config

logger = logging.getLogger(__name__)

# ВАЖНО: Используйте Vector Store API для создания поисковых индексов
# Документация: https://yandex.cloud/docs/ai-studio/concepts/vector-store
# Примеры использования: https://github.com/yandex-cloud/yandex-cloud-ml-sdk
# Старый Index API (/foundationModels/v1/indexes) устарел и возвращает 404
# Vector Store API работает через:
# 1. Загрузку файлов в Vector Store через sdk.files.upload()
# 2. Создание индекса из загруженных файлов через sdk.search_indexes.create_deferred()
# 3. Использование индекса через Responses API или Realtime API с инструментом file_search
#
# Примеры из репозитория GitHub:
# - search-assistant.py - создание RAG-ассистента с Vector Store
# - assistant-text.py / assistant-hybrid.py - создание ассистентов с разными типами индексов


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
        
        # ВАЖНО: Проверяем, что folder_id соответствует ожидаемому значению
        expected_folder_id = "b1g4samml2s1n1509ptp"
        if self.folder_id != expected_folder_id:
            logger.warning(
                f"⚠️  YANDEX_FOLDER_ID ({self.folder_id}) не соответствует ожидаемому ({expected_folder_id}). "
                f"Убедитесь, что в Render установлена правильная переменная окружения."
            )
        
        # Инициализируем SDK
        try:
            auth = APIKeyAuth(self.api_key) if self.use_api_key else self.iam_token
            self.sdk = YCloudML(folder_id=self.folder_id, auth=auth)
            logger.info(f"✅ Yandex Cloud ML SDK initialized for Vector Store with folder_id: {self.folder_id}")
            logger.info(f"📋 Using folder_id from environment: {self.folder_id}")
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
    
    def _upload_original_files(self, original_files: Dict[str, bytes]) -> List[Any]:
        """
        Upload original files to Vector Store and return file objects
        
        ВАЖНО: Загружаем ОРИГИНАЛЬНЫЕ файлы (PDF, DOCX и т.д.) напрямую в Yandex Vector Store.
        LangChain используется только для обработки на нашей стороне (БД).
        
        Args:
            original_files: Dict[str, bytes] - оригинальные файлы {filename: content}
            
            Returns:
            List of file objects (for passing to create_deferred)
            
        Raises:
            NotImplementedError: If SDK does not support files.upload()
            Exception: If all file uploads fail
        """
        # Проверяем поддержку files.upload() в SDK
        if not hasattr(self.sdk, 'files'):
            logger.error("SDK does not have 'files' attribute")
            raise NotImplementedError(
                "SDK does not support files API. "
                "Cannot upload files to Vector Store. "
                "Check SDK documentation for correct API."
            )
        
        if not hasattr(self.sdk.files, 'upload'):
            logger.error(f"SDK.files does not have 'upload' method. Available methods: {[m for m in dir(self.sdk.files) if not m.startswith('_')]}")
            raise NotImplementedError(
                "SDK does not support files.upload() method. "
                "Cannot upload files to Vector Store. "
                "Available files methods: " + str([m for m in dir(self.sdk.files) if not m.startswith('_')])
            )
        
        file_ids = []
        
        # Определяем MIME типы для разных форматов
        def get_mime_type(filename: str) -> str:
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            mime_types = {
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'doc': 'application/msword',
                'txt': 'text/plain',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'xls': 'application/vnd.ms-excel'
            }
            return mime_types.get(ext, 'application/octet-stream')
        
        for filename, file_content in original_files.items():
            try:
                mime_type = get_mime_type(filename)
                
                # Загружаем ОРИГИНАЛЬНЫЙ файл в Vector Store через SDK
                # Согласно документации: sdk.files.upload("<путь_к_файлу>") принимает путь к файлу как строку
                logger.debug(f"Uploading original file {filename} ({len(file_content)} bytes, {mime_type}) to Vector Store...")
                
                # Сохраняем файл во временный файл, так как SDK требует путь к файлу
                _, ext = os.path.splitext(filename)
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                    tmp_file.write(file_content)
                    tmp_path = tmp_file.name
                
                try:
                    # SDK files.upload() принимает путь к файлу как строку
                    # Согласно документации: file = sdk.files.upload("<путь_к_файлу>", ttl_days=5, expiration_policy="static")
                    # Файлы будут храниться 30 дней (для юридических документов нужно долгое хранение)
                    logger.debug(f"Attempting to upload file to folder_id: {self.folder_id}")
                    uploaded_file = self.sdk.files.upload(
                        tmp_path,
                        ttl_days=30,
                        expiration_policy="static"
                    )
                    
                    # Получаем объект файла (не только ID, а весь объект для передачи в create_deferred)
                    # Согласно документации, create_deferred принимает список файлов (объектов)
                    file_ids.append(uploaded_file)
                    logger.debug(f"✅ Successfully uploaded file {filename} via SDK")
                except Exception as upload_error:
                    error_msg = f"SDK files.upload() failed: {upload_error}"
                    logger.error(error_msg, exc_info=True)
                    raise Exception(f"Ошибка при загрузке файла {filename} через SDK: {error_msg}") from upload_error
                finally:
                    # Удаляем временный файл
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                
            except Exception as e:
                error_msg = f"Failed to upload original file {filename}: {type(e).__name__}: {e}"
                logger.error(error_msg, exc_info=True)
                raise Exception(f"Ошибка при загрузке оригинального файла {filename} в Vector Store: {str(e)}") from e
        
        if not file_ids:
            raise Exception(
                f"Failed to upload any original files to Vector Store. "
                f"Tried to upload {len(original_files)} files, but all failed."
            )
        
        logger.info(f"✅ Uploaded {len(file_ids)}/{len(original_files)} original files to Vector Store")
        return file_ids
    
    def create_index(self, case_id: str, name: str = None, original_files: Optional[Dict[str, bytes]] = None) -> str:
        """
        Create new Vector Store search index for case using ML SDK
        
        ВАЖНО: create_deferred требует обязательный параметр files (список ID файлов).
        Поэтому необходимо сначала загрузить ОРИГИНАЛЬНЫЕ файлы, затем создать индекс с их ID.
        
        LangChain используется ТОЛЬКО для обработки на нашей стороне (извлечение текста, chunks для БД).
        В Yandex Vector Store загружаем оригинальные файлы напрямую.
        
        Документация: https://yandex.cloud/docs/ai-studio/concepts/vector-store
        SDK Reference: https://yandex.cloud/docs/ai-studio/sdk-ref/
        
        Args:
            case_id: Case identifier
            name: Optional index name (defaults to index_prefix_case_id)
            original_files: Dict[str, bytes] - оригинальные файлы {filename: content} для загрузки в Vector Store.
                           Если не предоставлены, попытка создать пустой индекс (может не удаться).
        
        Returns:
            index_id: ID of created Vector Store index
        """
        self._ensure_sdk()
        
        index_name = name or f"{self.index_prefix}_{case_id}"
        file_ids = []
        
        # Если оригинальные файлы переданы, загружаем их напрямую в Vector Store
        if original_files:
            logger.info(f"Uploading {len(original_files)} original files to Vector Store before creating index...")
            file_ids = self._upload_original_files(original_files)
            logger.info(f"✅ Uploaded {len(file_ids)} files, will create index with these files")
        else:
            logger.warning(
                "No documents provided. create_deferred requires files parameter. "
                "Index creation may fail. Consider providing documents."
            )
        
        # Пробуем создать индекс через SDK
        try:
            # Попробуем через search_indexes (если доступно)
            if hasattr(self.sdk, 'search_indexes'):
                logger.info(f"Creating search index '{index_name}' for case {case_id} via SDK")
                search_indexes = self.sdk.search_indexes
                
                # Логируем доступные методы для отладки
                available_methods = [m for m in dir(search_indexes) if not m.startswith('_') and callable(getattr(search_indexes, m, None))]
                logger.info(f"Available methods in search_indexes: {available_methods}")
                
                # Используем create_deferred - это правильный метод для создания индекса в SDK
                # create_deferred требует обязательный параметр files (список ID файлов)
                if hasattr(search_indexes, 'create_deferred'):
                    logger.info(f"Creating index using create_deferred method with {len(file_ids)} files...")
                    
                    # ВАЖНО: create_deferred требует список файлов (объектов), НЕ пустой список
                    # Согласно документации: sdk.search_indexes.create_deferred(files, ...)
                    # где files - это список объектов файлов, полученных из sdk.files.upload()
                    if not file_ids:
                        raise ValueError(
                            "create_deferred requires files parameter (list of file objects). "
                            "Cannot create index without files. Please provide documents when calling create_index."
                        )
                    
                    # Согласно документации, create_deferred принимает файлы первым позиционным параметром
                    # и index_type через именованный параметр
                    # По умолчанию используем VectorSearchIndexType для смыслового поиска
                    try:
                        from yandex_cloud_ml_sdk.search_indexes import (
                            VectorSearchIndexType,
                            StaticIndexChunkingStrategy
                        )
                        
                        # Создаем индекс с векторным поиском (рекомендуется для RAG)
                        operation = self.sdk.search_indexes.create_deferred(
                            file_ids,  # Список объектов файлов (первый позиционный параметр)
                            index_type=VectorSearchIndexType(
                                chunking_strategy=StaticIndexChunkingStrategy(
                                    max_chunk_size_tokens=700,
                                    chunk_overlap_tokens=300,
                                )
                            ),
                            name=index_name,
                            description=f"Index for case {case_id}"
                        )
                        
                        # Дожидаемся создания индекса (операция асинхронная)
                        logger.info(f"Waiting for index creation to complete...")
                        search_index = operation.wait()
                        
                        # Получаем ID индекса
                        index_id = search_index.id if hasattr(search_index, 'id') else str(search_index)
                        logger.info(f"✅ Created search index {index_id} for case {case_id} with {len(file_ids)} files")
                        return index_id
                    except ImportError:
                        # Если импорт не удался, пробуем без типов индексов (простой вариант)
                        logger.warning("Could not import index types, using default index creation")
                        operation = self.sdk.search_indexes.create_deferred(
                            file_ids,
                            name=index_name,
                            description=f"Index for case {case_id}"
                        )
                        search_index = operation.wait()
                        index_id = search_index.id if hasattr(search_index, 'id') else str(search_index)
                        logger.info(f"✅ Created search index {index_id} for case {case_id} with {len(file_ids)} files (default)")
                        return index_id
                else:
                    logger.error(
                        f"search_indexes не содержит метода create_deferred. "
                        f"Доступные методы: {available_methods}. "
                        f"Проверьте документацию SDK: https://yandex.cloud/docs/ai-studio/sdk-ref/"
                    )
                    raise NotImplementedError(
                        f"Метод create_deferred не найден в SDK. "
                        f"Доступные методы search_indexes: {available_methods}. "
                        f"Проверьте документацию SDK для правильного использования."
                    )
            
            # Если search_indexes не доступен
            available_attrs = [attr for attr in dir(self.sdk) if not attr.startswith('_')]
            logger.warning(
                f"SDK не содержит search_indexes. "
                f"Доступные атрибуты SDK: {', '.join(available_attrs[:20])}..."
            )
            raise NotImplementedError(
                "SDK не содержит search_indexes атрибута. "
                "Проверьте документацию SDK и доступные методы. "
                "SDK Reference: https://yandex.cloud/docs/ai-studio/sdk-ref/"
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

