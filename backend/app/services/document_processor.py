"""Document processor service using LangChain"""
from typing import List, Dict, Any, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from app.config import config
from app.services.yandex_embeddings import YandexEmbeddings
from app.services.yandex_index import YandexIndexService
from sqlalchemy.orm import Session
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
        
        # Initialize embeddings - только Yandex, без fallback
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
            raise ValueError(
                "YANDEX_API_KEY или YANDEX_IAM_TOKEN должны быть настроены. "
                "OpenRouter больше не используется."
            )
        
        if not config.YANDEX_FOLDER_ID:
            raise ValueError(
                "YANDEX_FOLDER_ID должен быть настроен для работы Yandex embeddings."
            )
        
        try:
            self.embeddings = YandexEmbeddings()
            logger.info("✅ Using Yandex embeddings")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex embeddings: {e}")
            raise ValueError(f"Ошибка инициализации Yandex embeddings: {str(e)}")
        
        # Initialize Yandex Index service
        try:
            self.index_service = YandexIndexService()
            logger.info("✅ Using Yandex Index service")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Index service: {e}")
            raise ValueError(f"Ошибка инициализации Yandex Index service: {str(e)}")
    
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
    
    def store_in_vector_db(
        self,
        case_id: str,
        documents: List[Document],
        db: Session
    ) -> str:
        """
        Store documents in Yandex AI Studio Index
        
        Args:
            case_id: Case identifier
            documents: List of Document objects
            db: Database session for saving index_id
            
        Returns:
            index_id: ID of created/updated index
        """
        if not documents:
            logger.warning(f"No documents to store for case {case_id}")
            return None
        
        logger.info(f"Storing {len(documents)} documents in Yandex Index for case {case_id}")
        
        # Check if index already exists for this case
        from app.models.case import Case
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found in database")
        
        index_id = case.yandex_index_id
        
        # Create new index if doesn't exist
        # ВАЖНО: Для Yandex Vector Store нужно передавать документы при создании индекса,
        # потому что create_deferred требует обязательный параметр files
        if not index_id:
            try:
                # Передаем документы в create_index, чтобы они были загружены как файлы
                # и индекс создан с этими файлами
                index_id = self.index_service.create_index(case_id, documents=documents)
                case.yandex_index_id = index_id
                db.commit()
                logger.info(f"✅ Created and saved index {index_id} for case {case_id} with {len(documents)} documents")
                # Документы уже добавлены при создании индекса, не нужно добавлять их еще раз
                return index_id
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create index for case {case_id}: {e}", exc_info=True)
                raise
        
        # Если индекс уже существует, добавляем документы через add_documents
        # (хотя это может не работать, т.к. add_documents еще не полностью реализован)
        try:
            result = self.index_service.add_documents(index_id, documents)
            logger.info(f"✅ Added {len(documents)} documents to existing index {index_id}: {result}")
        except Exception as e:
            logger.warning(f"Failed to add documents to existing index {index_id}: {e}. Index may need to be recreated with documents.")
            # Не бросаем исключение, т.к. индекс уже существует и может быть использован
        
        return index_id
    
    def retrieve_relevant_chunks(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        distance_threshold: float = 1.5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve relevant document chunks using Yandex AI Studio Index search
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of chunks to retrieve
            distance_threshold: Maximum distance threshold (for filtering, not used by Yandex Index API directly)
            db: Optional database session for getting index_id
            
        Returns:
            List of relevant Document objects with scores
        """
        # Get index_id for case
        index_id = self.index_service.get_index_id(case_id, db_session=db)
        
        if not index_id:
            logger.warning(f"No index found for case {case_id}")
            return []
        
        try:
            # Search in Yandex Index
            documents = self.index_service.search(index_id, query, k=k)
            
            # Filter by threshold if needed (Yandex Index returns similarity scores)
            # Yandex Index returns similarity_score in metadata (higher = better)
            if distance_threshold < 1.5:  # Only filter if threshold is meaningful
                filtered_docs = []
                for doc in documents:
                    similarity_score = doc.metadata.get("similarity_score", 1.0)
                    # Convert similarity to distance: distance = 1 - similarity
                    distance_score = 1.0 - similarity_score
                    if distance_score <= distance_threshold:
                        filtered_docs.append(doc)
                documents = filtered_docs
            
            if not documents:
                logger.warning(f"No relevant chunks found for case {case_id} in index {index_id}")
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving chunks for case {case_id}: {e}", exc_info=True)
            return []
    
    def get_index_id(self, case_id: str, db: Optional[Session] = None) -> Optional[str]:
        """
        Get index_id for case from database
        
        Args:
            case_id: Case identifier
            db: Optional database session
            
        Returns:
            index_id if found, None otherwise
        """
        return self.index_service.get_index_id(case_id, db_session=db)

