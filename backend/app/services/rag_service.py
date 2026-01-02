"""RAG (Retrieval Augmented Generation) service"""
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from app.config import config
from app.services.document_processor import DocumentProcessor
# YandexAssistantService imported conditionally - only for yandex vector store
from app.services.langchain_retrievers import AdvancedRetrieverService
from app.services.langchain_memory import MemoryService
import logging

logger = logging.getLogger(__name__)

# Словарь для перевода типов документов на русский язык
DOC_TYPE_LABELS = {
    # Судебные акты
    'court_order': 'Судебный приказ',
    'court_decision': 'Решение',
    'court_ruling': 'Определение',
    'court_resolution': 'Постановление',
    
    # Инициирующие дело
    'statement_of_claim': 'Исковое заявление',
    'order_application': 'Заявление о выдаче судебного приказа',
    'bankruptcy_application': 'Заявление о признании должника банкротом',
    
    # Ответные документы
    'response_to_claim': 'Отзыв на исковое заявление',
    'counterclaim': 'Встречный иск',
    'third_party_application': 'Заявление о вступлении третьего лица в дело',
    'third_party_objection': 'Возражения третьего лица',
    
    # Ходатайства
    'motion': 'Ходатайство',
    'motion_evidence': 'Ходатайство о доказательствах',
    'motion_security': 'Ходатайство об обеспечительных мерах',
    'motion_cancel_security': 'Ходатайство об отмене обеспечения иска',
    'motion_recusation': 'Ходатайство об отводе судьи',
    'motion_reinstatement': 'Ходатайство о восстановлении пропущенного срока',
    
    # Обжалование
    'appeal': 'Апелляционная жалоба',
    'cassation': 'Кассационная жалоба',
    'supervisory_appeal': 'Надзорная жалоба',
    
    # Специальные производства
    'arbitral_annulment': 'Заявление об отмене решения третейского суда',
    'arbitral_enforcement': 'Заявление о выдаче исполнительного листа на решение третейского суда',
    'creditor_registry': 'Заявление о включении требования в реестр требований кредиторов',
    'administrative_challenge': 'Заявление об оспаривании ненормативного правового акта',
    'admin_penalty_challenge': 'Заявление об оспаривании решения административного органа',
    
    # Урегулирование
    'settlement_agreement': 'Мировое соглашение',
    'protocol_remarks': 'Замечания на протокол судебного заседания',
    
    # Досудебные
    'pre_claim': 'Претензия (досудебное требование)',
    'written_explanation': 'Письменное объяснение по делу',
    
    # Приложения
    'power_of_attorney': 'Доверенность',
    'egrul_extract': 'Выписка из ЕГРЮЛ/ЕГРИП',
    'state_duty': 'Документ об уплате государственной пошлины',
    
    # Доказательства - Письменные
    'contract': 'Договор',
    'act': 'Акт',
    'certificate': 'Справка',
    'correspondence': 'Деловая переписка',
    'electronic_document': 'Электронный документ',
    'protocol': 'Протокол',
    'expert_opinion': 'Заключение эксперта',
    'specialist_consultation': 'Консультация специалиста',
    'witness_statement': 'Показания свидетеля',
    
    # Доказательства - Мультимедиа
    'audio_recording': 'Аудиозапись',
    'video_recording': 'Видеозапись',
    'physical_evidence': 'Вещественное доказательство',
    
    # Прочие
    'other': 'Другое'
}


class RAGService:
    """Service for RAG operations"""
    
    def __init__(self, document_processor: DocumentProcessor = None):
        """Initialize RAG service"""
        self.document_processor = document_processor or DocumentProcessor()
        self.retriever_service = AdvancedRetrieverService(self.document_processor)
        self.memory_service = MemoryService()
        
        # Initialize iterative RAG service
        try:
            from app.services.iterative_rag_service import IterativeRAGService
            self.iterative_rag = IterativeRAGService(self)
            logger.info("✅ Iterative RAG service initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize IterativeRAGService: {e}")
            self.iterative_rag = None
        
        # Using direct RAG with GigaChat + pgvector
        logger.info("✅ Using direct RAG with GigaChat + pgvector")
    
    def retrieve_context(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: str = "simple",
        db: Optional[Session] = None,
        use_iterative: bool = False,
        use_hybrid: bool = False,
        doc_types: Optional[List[str]] = None
    ) -> List[Document]:
        """
        Retrieve relevant context for a query using Yandex Index
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            retrieval_strategy: Strategy to use ('simple', 'multi_query', 'compression', 'ensemble', 'iterative')
            db: Optional database session
            use_iterative: Use iterative search (overrides retrieval_strategy if True)
            use_hybrid: Use hybrid search
            doc_types: Optional list of document types to filter by (e.g., ['statement_of_claim', 'contract'])
            
        Returns:
            List of relevant Document objects
        """
        try:
            # Use hybrid search if requested or if strategy is 'hybrid'
            if use_hybrid or retrieval_strategy == "hybrid":
                logger.info(f"Using hybrid search for case {case_id}")
                # Get more documents if filtering by type
                search_k = k * 2 if doc_types else k
                docs = self.document_processor.hybrid_search(
                    case_id=case_id,
                    query=query,
                    k=search_k,
                    alpha=0.7,  # 70% dense, 30% sparse
                    db=db
                )
                # Filter out None or invalid documents
                valid_docs = [doc for doc in docs if doc is not None and hasattr(doc, 'page_content')]
                
                # Filter by document type if specified
                if doc_types:
                    filtered = [
                        doc for doc in valid_docs
                        if doc.metadata.get("doc_type") in doc_types
                    ]
                    valid_docs = filtered[:k] if filtered else valid_docs[:k]
                    logger.info(f"Filtered to {len(valid_docs)} documents of types {doc_types} for case {case_id}")
                
                if not valid_docs:
                    logger.warning(f"No valid documents from hybrid search for case {case_id}")
                return valid_docs
            
            # Use iterative RAG if requested or if strategy is 'iterative'
            if use_iterative or retrieval_strategy == "iterative":
                if self.iterative_rag:
                    # Get more documents if filtering by type
                    search_k = k * 2 if doc_types else k
                    docs = self.iterative_rag.retrieve_iteratively(
                        case_id=case_id,
                        query=query,
                        max_iterations=3,
                        initial_k=search_k,
                        db=db
                    )
                    # Filter by document type if specified
                    if doc_types:
                        filtered = [
                            doc for doc in docs
                            if doc.metadata.get("doc_type") in doc_types
                        ]
                        docs = filtered[:k] if filtered else docs[:k]
                        logger.info(f"Filtered to {len(docs)} documents of types {doc_types} for case {case_id}")
                    return docs
                else:
                    logger.warning("Iterative RAG not available, falling back to multi_query")
                    retrieval_strategy = "multi_query"
            
            # Get more documents if filtering by type
            search_k = k * 2 if doc_types else k
            
            if retrieval_strategy == "multi_query":
                docs = self.retriever_service.retrieve_with_multi_query(case_id, query, k=search_k, db=db)
            elif retrieval_strategy == "compression":
                docs = self.retriever_service.retrieve_with_compression(case_id, query, k=search_k*2, db=db)  # Get more before compression
            elif retrieval_strategy == "ensemble":
                docs = self.retriever_service.retrieve_with_ensemble(case_id, query, k=search_k, db=db)
            else:
                # Default: simple retrieval using Yandex Index
                docs = self.document_processor.retrieve_relevant_chunks(
                    case_id=case_id,
                    query=query,
                    k=search_k,
                    db=db
                )
            
            # Ensure we return a list, even if empty
            if docs is None:
                logger.warning(f"Retrieval returned None for case {case_id}, returning empty list")
                return []
            
            # Filter out None or invalid documents
            valid_docs = [doc for doc in docs if doc is not None and hasattr(doc, 'page_content')]
            
            # Filter by document type if specified
            if doc_types:
                filtered = [
                    doc for doc in valid_docs
                    if doc.metadata.get("doc_type") in doc_types
                ]
                valid_docs = filtered[:k] if filtered else valid_docs[:k]
                logger.info(f"Filtered to {len(valid_docs)} documents of types {doc_types} for case {case_id}")
            
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
            
            # Добавляем информацию о классификации
            doc_type = metadata.get("doc_type")
            classification_info = ""
            if doc_type:
                doc_type_label = DOC_TYPE_LABELS.get(doc_type, doc_type)
                confidence = metadata.get("classification_confidence", 0.0)
                classification_info = f" [Тип: {doc_type_label}"
                if confidence:
                    # Преобразуем confidence в проценты
                    confidence_percent = int(float(confidence) * 100) if isinstance(confidence, (int, float, str)) else 0
                    if confidence_percent > 0:
                        classification_info += f", уверенность: {confidence_percent}%"
                classification_info += "]"
            
            source_ref = f"[Источник {i}: {source_file}{classification_info}"
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
        Generate answer with source references
        
        Uses direct RAG with pgvector + GigaChat (no Assistant API).
        
        Args:
            case_id: Case identifier
            query: User query
            context: Additional context (optional)
            k: Number of chunks to retrieve
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
        
        # Use direct RAG with pgvector + GigaChat
        # Use iterative search for better results
        return self._generate_with_direct_rag(case_id, query, k, db, history, use_iterative=True)
    
    def _generate_with_direct_rag(
        self,
        case_id: str,
        query: str,
        k: int,
        db: Optional[Session],
        history: Optional[List[Dict[str, str]]],
        use_iterative: bool = True
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Generate using direct RAG with pgvector + GigaChat
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            db: Optional database session
            history: Optional chat history
            use_iterative: Use iterative search for better results
        """
        from app.services.llm_factory import create_llm
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        # Retrieve relevant documents (use iterative search by default)
        if use_iterative and self.iterative_rag:
            documents = self.iterative_rag.retrieve_iteratively(
                case_id=case_id,
                query=query,
                max_iterations=3,
                initial_k=k,
                db=db
            )
        else:
            documents = self.retrieve_context(case_id, query, k=k, db=db, retrieval_strategy="multi_query")
        
        if not documents:
            return "Извините, не удалось найти релевантные документы для вашего запроса.", []
        
        # Format context from documents
        context = self.format_sources_for_prompt(documents)
        
        # Prepare messages
        messages = []
        messages.append(SystemMessage(content="""Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе предоставленных документов.

КРИТИЧЕСКИ ВАЖНО:
- Ты ДОЛЖЕН отвечать на ВСЕ вопросы пользователя о документах дела
- НЕ отказывайся отвечать, даже если вопрос кажется сложным или требует анализа
- Твоя задача - помочь пользователю понять содержание документов
- Анализируй документы, извлекай факты, составляй хронологии, находи связи между событиями
- Ты работаешь с юридическими документами, которые уже загружены в систему - это безопасно и допустимо

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [1][2][3] прямо в тексте ответа
- Номера источников соответствуют порядку документов: [1] - первый документ, [2] - второй и т.д.
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно
- НЕ пиши "Источник 1", "Источник 2" - только [1][2][3]
- Составляй хронологии событий, анализируй риски, находи противоречия - это твоя работа"""))
        
        # Add history
        if history:
            for msg in history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current query with context
        user_message = f"""Используй следующие документы для ответа:

{context}

Вопрос: {query}

Ответ (обязательно укажи источники):"""
        messages.append(HumanMessage(content=user_message))
        
        # Generate answer using GigaChat
        llm = create_llm()
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, 'content') else str(response)
        
        # Format sources
        sources = self.format_sources(documents)
        
        return answer, sources
    

