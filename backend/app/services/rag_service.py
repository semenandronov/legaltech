"""RAG (Retrieval Augmented Generation) service"""
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from app.config import config
from app.services.document_processor import DocumentProcessor
from app.services.yandex_assistant import YandexAssistantService
from app.services.langchain_retrievers import AdvancedRetrieverService
from app.services.langchain_memory import MemoryService
import logging

logger = logging.getLogger(__name__)


class RAGService:
    """Service for RAG operations"""
    
    def __init__(self, document_processor: DocumentProcessor = None):
        """Initialize RAG service"""
        self.document_processor = document_processor or DocumentProcessor()
        self.retriever_service = AdvancedRetrieverService(self.document_processor)
        self.memory_service = MemoryService()
        
        # Initialize Yandex Assistant service
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
            raise ValueError(
                "YANDEX_API_KEY или YANDEX_IAM_TOKEN должны быть настроены. "
                "OpenRouter больше не используется."
            )
        
        if not config.YANDEX_FOLDER_ID:
            raise ValueError(
                "YANDEX_FOLDER_ID должен быть настроен для работы Yandex Assistant."
            )
        
        try:
            self.assistant_service = YandexAssistantService()
            logger.info("✅ Using Yandex Assistant API for RAG")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Assistant service: {e}")
            raise ValueError(f"Ошибка инициализации Yandex Assistant service: {str(e)}")
    
    def retrieve_context(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: str = "simple",
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Retrieve relevant context for a query using Yandex Index
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            retrieval_strategy: Strategy to use ('simple', 'multi_query', 'compression', 'ensemble')
            db: Optional database session
            
        Returns:
            List of relevant Document objects
        """
        try:
            if retrieval_strategy == "multi_query":
                docs = self.retriever_service.retrieve_with_multi_query(case_id, query, k=k, db=db)
            elif retrieval_strategy == "compression":
                docs = self.retriever_service.retrieve_with_compression(case_id, query, k=k*2, db=db)  # Get more before compression
            elif retrieval_strategy == "ensemble":
                docs = self.retriever_service.retrieve_with_ensemble(case_id, query, k=k, db=db)
            else:
                # Default: simple retrieval using Yandex Index
                docs = self.document_processor.retrieve_relevant_chunks(
                    case_id=case_id,
                    query=query,
                    k=k,
                    db=db
                )
            
            # Ensure we return a list, even if empty
            if docs is None:
                logger.warning(f"Retrieval returned None for case {case_id}, returning empty list")
                return []
            
            # Filter out None or invalid documents
            valid_docs = [doc for doc in docs if doc is not None and hasattr(doc, 'page_content')]
            
            if not valid_docs:
                logger.warning(f"No valid documents retrieved for case {case_id} with query: {query[:100]}")
            
            return valid_docs
        except Exception as e:
            logger.error(f"Error retrieving context for case {case_id}: {e}", exc_info=True)
            return []
    
    def format_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Format source documents with precise references
        
        Args:
            documents: List of Document objects
            
        Returns:
            List of formatted source dictionaries
        """
        sources = []
        for doc in documents:
            metadata = doc.metadata
            source = {
                "file": metadata.get("source_file", "unknown"),
                "page": metadata.get("source_page"),
                "chunk_index": metadata.get("chunk_index"),
                "start_line": metadata.get("source_start_line"),
                "end_line": metadata.get("source_end_line"),
                "text_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                "similarity_score": metadata.get("similarity_score")
            }
            sources.append(source)
        return sources
    
    def format_sources_for_prompt(self, documents: List[Document], max_context_chars: int = None) -> str:
        """
        Format sources as text for prompt
        
        Args:
            documents: List of Document objects
            max_context_chars: Maximum characters for context (optional)
            
        Returns:
            Formatted string with sources
        """
        if max_context_chars is None:
            max_context_chars = config.MAX_CONTEXT_CHARS
        
        formatted_sources = []
        total_length = 0
        
        for i, doc in enumerate(documents, 1):
            metadata = doc.metadata
            source_file = metadata.get("source_file", "unknown")
            source_page = metadata.get("source_page")
            source_line = metadata.get("source_start_line")
            
            source_ref = f"[Источник {i}: {source_file}"
            if source_page:
                source_ref += f", стр. {source_page}"
            if source_line:
                source_ref += f", строка {source_line}"
            source_ref += "]"
            
            # Truncate document content if needed
            doc_content = doc.page_content
            available_chars = max_context_chars - total_length - len(source_ref) - 10  # Reserve space
            if available_chars < len(doc_content):
                doc_content = doc_content[:available_chars] + "..."
                logger.warning(f"Truncating document content for source {i} to fit context limit")
            
            formatted_source = f"{source_ref}\n{doc_content}"
            formatted_sources.append(formatted_source)
            total_length += len(formatted_source)
            
            # Stop if we've reached the limit
            if total_length >= max_context_chars:
                logger.warning(f"Reached context limit after {i} sources")
                break
        
        return "\n\n".join(formatted_sources)
    
    def generate_with_sources(
        self,
        case_id: str,
        query: str,
        context: str = None,
        k: int = 5,
        db: Optional[Session] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer with source references using Yandex Assistant API
        
        Args:
            case_id: Case identifier
            query: User query
            context: Additional context (optional, currently not used with Assistant API)
            k: Number of chunks to retrieve (used as hint for Assistant)
            db: Optional database session
            history: Optional chat history in format [{"role": "user|assistant", "content": "..."}, ...]
            
        Returns:
            Tuple of (answer, sources)
        """
        # Проверка на разговорные вопросы - даем дружелюбный ответ
        query_lower = query.lower().strip()
        conversational_questions = {
            "как дела": "Спасибо, всё хорошо! Готов помочь вам с анализом документов дела. Задайте вопрос о документах, и я найду нужную информацию.",
            "как поживаешь": "Спасибо, отлично! Чем могу помочь с вашим делом?",
            "привет": "Привет! Готов помочь с анализом документов. Что вас интересует?",
            "здравствуй": "Здравствуйте! Чем могу помочь с вашим делом?",
            "hello": "Hello! I'm ready to help you analyze your case documents. What would you like to know?",
            "hi": "Hi! How can I help you with your case?",
        }
        
        for key, response in conversational_questions.items():
            if query_lower == key or query_lower.startswith(key + " "):
                return response, []
        
        # Get or create assistant for case
        assistant_id = self.assistant_service.get_assistant_id(case_id, db_session=db)
        
        if not assistant_id:
            # Create assistant if doesn't exist
            try:
                index_id = self.document_processor.get_index_id(case_id, db)
                if not index_id:
                    # Check if case has files (documents were uploaded but index creation failed)
                    if db:
                        from app.models.case import Case, File as FileModel
                        case = db.query(Case).filter(Case.id == case_id).first()
                        file_count = db.query(FileModel).filter(FileModel.case_id == case_id).count()
                        
                        if case and file_count > 0:
                            # Case has files but no index - это ошибка, индекс должен был быть создан при загрузке
                            logger.error(f"Case {case_id} has {file_count} files but no index. Index should have been created during file upload.")
                            return "Извините, для этого дела документы были загружены, но индекс не был создан. Пожалуйста, загрузите документы заново или обратитесь в поддержку.", []
                        else:
                            logger.warning(f"No files found for case {case_id}, cannot create assistant")
                            return "Извините, для этого дела еще не загружены документы. Пожалуйста, загрузите документы сначала.", []
                    else:
                        logger.warning(f"No index found for case {case_id} and no db session, cannot create assistant")
                        return "Извините, для этого дела еще не загружены документы. Пожалуйста, загрузите документы сначала.", []
                
                assistant_id = self.assistant_service.create_assistant(case_id, index_id)
                
                # Save assistant_id to database
                if db:
                    from app.models.case import Case
                    case = db.query(Case).filter(Case.id == case_id).first()
                    if case:
                        case.yandex_assistant_id = assistant_id
                        db.commit()
                        logger.info(f"Saved assistant_id {assistant_id} for case {case_id}")
            except Exception as e:
                logger.error(f"Failed to create assistant for case {case_id}: {e}", exc_info=True)
                raise Exception(f"Не удалось создать ассистента для дела. Ошибка: {str(e)}")
        
        # Send message to assistant
        response = self.assistant_service.send_message(assistant_id, query, history=history)
        
        answer = response.get("answer", "")
        sources_raw = response.get("sources", [])
        
        # Format sources to match expected format
        sources = []
        for source in sources_raw:
            formatted_source = {
                "file": source.get("file", "unknown"),
                "page": source.get("page"),
                "start_line": source.get("start_line"),
                "end_line": source.get("end_line"),
                "text_preview": source.get("content", "")[:200] + "..." if len(source.get("content", "")) > 200 else source.get("content", "")
            }
            sources.append(formatted_source)
        
        return answer, sources
    

