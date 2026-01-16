"""RAG (Retrieval Augmented Generation) service

Phase 1.3: Added multi-stage RAG pipeline with reranking and query condensation.
"""
from typing import List, Dict, Any, Tuple, Optional, Type
import json
import time
import inspect
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from app.config import config
from app.services.document_processor import DocumentProcessor
# YandexAssistantService imported conditionally - only for yandex vector store
from app.services.langchain_retrievers import AdvancedRetrieverService
from app.services.langchain_memory import MemoryService
import logging

logger = logging.getLogger(__name__)

# Phase 1.3: Multi-stage RAG configuration
MULTI_STAGE_RAG_ENABLED = True
INITIAL_RETRIEVE_K = 100  # First stage: retrieve many candidates
RERANK_TOP_K = 20  # Second stage: rerank to top candidates
CONDENSE_TOP_K = 10  # Third stage: condense context
FINAL_TOP_K = 5  # Final stage: use for synthesis

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
        
        # Phase 1.3: Initialize reranker and query condenser
        self._reranker = None
        self._query_condenser = None
        
        try:
            from app.services.reranker_service import get_reranker_service
            self._reranker = get_reranker_service()
            logger.info("✅ Reranker service initialized")
        except Exception as e:
            logger.warning(f"Reranker not available: {e}")
        
        try:
            from app.services.query_condenser import get_query_condenser
            self._query_condenser = get_query_condenser()
            logger.info("✅ Query condenser initialized")
        except Exception as e:
            logger.warning(f"Query condenser not available: {e}")
        
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
        # Проверить кэш RAG перед выполнением запроса
        try:
            from app.services.langchain_agents.rag_cache import get_rag_cache
            rag_cache = get_rag_cache()
            
            cached_docs = rag_cache.get(
                case_id=case_id,
                query=query,
                k=k,
                retrieval_strategy=retrieval_strategy if not use_iterative and not use_hybrid else None,
                doc_types=doc_types
            )
            
            if cached_docs:
                logger.debug(f"[RAGService] Cache hit for query: {query[:50]}... (case: {case_id})")
                return cached_docs
        except Exception as cache_error:
            logger.debug(f"RAG cache check failed (non-critical): {cache_error}")
        
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
            
            # Сохранить результаты в кэш RAG
            try:
                from app.services.langchain_agents.rag_cache import get_rag_cache
                rag_cache = get_rag_cache()
                
                # Сохранить только если есть результаты
                if valid_docs:
                    rag_cache.set(
                        case_id=case_id,
                        query=query,
                        documents=valid_docs,
                        k=k,
                        retrieval_strategy=retrieval_strategy if not use_iterative and not use_hybrid else None,
                        doc_types=doc_types
                    )
                    logger.debug(f"[RAGService] Cached RAG result: {len(valid_docs)} documents (case: {case_id})")
            except Exception as cache_error:
                logger.debug(f"RAG cache save failed (non-critical): {cache_error}")
            
            return valid_docs
        except Exception as e:
            logger.error(f"Error retrieving context for case {case_id}: {e}", exc_info=True)
            return []
    
    def retrieve_multi_stage(
        self,
        case_id: str,
        query: str,
        db: Optional[Session] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
        initial_k: int = INITIAL_RETRIEVE_K,
        rerank_k: int = RERANK_TOP_K,
        final_k: int = FINAL_TOP_K
    ) -> List[Document]:
        """
        Multi-stage RAG retrieval pipeline (Phase 1.3).
        
        Pipeline:
        1. Query condensation (if chat history)
        2. Initial retrieval (BM25 + vector, top-initial_k)
        3. Reranking (cross-encoder, top-rerank_k)
        4. Context condensation (summarization)
        5. Final selection (top-final_k)
        
        Args:
            case_id: Case identifier
            query: User query
            db: Optional database session
            chat_history: Optional chat history for query condensation
            initial_k: Number of candidates for initial retrieval
            rerank_k: Number of documents after reranking
            final_k: Final number of documents to return
            
        Returns:
            List of relevant documents
        """
        try:
            logger.info(f"Multi-stage RAG for case {case_id}: initial_k={initial_k}, rerank_k={rerank_k}, final_k={final_k}")
            
            # Stage 1: Query condensation (if history available)
            condensed_query = query
            if chat_history and self._query_condenser:
                condensed_query = self._query_condenser.condense_query(query, chat_history)
                if condensed_query != query:
                    logger.debug(f"Query condensed: '{query[:50]}...' → '{condensed_query[:50]}...'")
            
            # Stage 2: Initial retrieval (hybrid search for more candidates)
            logger.debug(f"Stage 2: Retrieving {initial_k} candidates with hybrid search")
            candidates = self.document_processor.hybrid_search(
                case_id=case_id,
                query=condensed_query,
                k=initial_k,
                alpha=0.6,  # 60% dense, 40% sparse (slightly favor BM25 for initial)
                db=db
            )
            
            # Filter valid documents
            candidates = [doc for doc in candidates if doc is not None and hasattr(doc, 'page_content')]
            
            if not candidates:
                logger.warning(f"No candidates retrieved for case {case_id}")
                return []
            
            logger.debug(f"Stage 2: Retrieved {len(candidates)} candidates")
            
            # Stage 3: Reranking with cross-encoder
            if self._reranker and len(candidates) > final_k:
                logger.debug(f"Stage 3: Reranking to top {rerank_k}")
                reranked = self._reranker.rerank_to_documents(
                    query=condensed_query,
                    documents=candidates,
                    top_k=rerank_k
                )
                
                if reranked:
                    candidates = reranked
                    logger.debug(f"Stage 3: Reranked to {len(candidates)} documents")
            
            # Stage 4: Optional context condensation
            # (Generate summaries for very long documents)
            # This is a placeholder for per-chunk summary generation
            # which should be done at indexing time, not retrieval time
            
            # Stage 5: Final selection
            final_docs = candidates[:final_k]
            
            logger.info(
                f"Multi-stage RAG completed for case {case_id}: "
                f"initial={len(candidates)} → final={len(final_docs)}"
            )
            
            return final_docs
            
        except Exception as e:
            logger.error(f"Multi-stage RAG error for case {case_id}: {e}", exc_info=True)
            # Fallback to simple retrieval
            return self.retrieve_context(case_id, query, k=final_k, db=db)
    
    def retrieve_with_multi_query(
        self,
        case_id: str,
        query: str,
        db: Optional[Session] = None,
        num_queries: int = 3,
        k_per_query: int = 10,
        final_k: int = FINAL_TOP_K
    ) -> List[Document]:
        """
        Retrieve using multiple query formulations.
        
        Generates diverse query formulations and retrieves documents for each,
        then deduplicates and reranks the combined results.
        
        Args:
            case_id: Case identifier
            query: Original user query
            db: Optional database session
            num_queries: Number of query variants to generate
            k_per_query: Documents to retrieve per query
            final_k: Final number of documents to return
            
        Returns:
            List of relevant documents
        """
        try:
            queries = [query]
            
            # Generate multi-queries
            if self._query_condenser:
                queries = self._query_condenser.generate_multi_queries(query, num_queries)
                logger.debug(f"Generated {len(queries)} query variants")
            
            # Retrieve for each query
            all_docs = []
            seen_content_hashes = set()
            
            for q in queries:
                docs = self.document_processor.hybrid_search(
                    case_id=case_id,
                    query=q,
                    k=k_per_query,
                    alpha=0.7,
                    db=db
                )
                
                # Deduplicate by content hash
                for doc in docs:
                    if doc is None:
                        continue
                    content_hash = hash(doc.page_content[:500])
                    if content_hash not in seen_content_hashes:
                        seen_content_hashes.add(content_hash)
                        all_docs.append(doc)
            
            # Rerank combined results
            if self._reranker and len(all_docs) > final_k:
                all_docs = self._reranker.rerank_to_documents(
                    query=query,
                    documents=all_docs,
                    top_k=final_k
                )
            else:
                all_docs = all_docs[:final_k]
            
            logger.info(f"Multi-query retrieval: {len(queries)} queries → {len(all_docs)} docs")
            return all_docs
            
        except Exception as e:
            logger.error(f"Multi-query retrieval error: {e}")
            return self.retrieve_context(case_id, query, k=final_k, db=db)
    
    def format_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Format source documents with precise references
        
        Phase 1: Added doc_id, char_start, char_end support
        
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
                "similarity_score": metadata.get("similarity_score"),
                # Phase 1: Citation system fields
                "doc_id": metadata.get("doc_id"),
                "char_start": metadata.get("char_start"),
                "char_end": metadata.get("char_end"),
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
            
            # Add character offset if available for precise citation
            start_char = metadata.get("chunk_start_char")
            if start_char is not None:
                source_ref += f", позиция {start_char}"
            
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
        history: Optional[List[Dict[str, str]]] = None,
        use_citation_first: bool = False
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
        return self._generate_with_direct_rag(
            case_id, query, k, db, history, 
            use_iterative=True,
            use_citation_first=use_citation_first
        )
    
    def _generate_with_direct_rag(
        self,
        case_id: str,
        query: str,
        k: int,
        db: Optional[Session],
        history: Optional[List[Dict[str, str]]],
        use_iterative: bool = True,
        use_multi_stage: bool = True,
        use_citation_first: bool = False
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Generate using direct RAG with pgvector + GigaChat
        
        Phase 1.3: Added multi-stage RAG pipeline support.
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            db: Optional database session
            history: Optional chat history
            use_iterative: Use iterative search for better results
            use_multi_stage: Use multi-stage RAG pipeline (Phase 1.3)
        """
        from app.services.llm_factory import create_llm
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        # Phase 1.3: Use multi-stage RAG pipeline if available
        if use_multi_stage and MULTI_STAGE_RAG_ENABLED:
            logger.info(f"Using multi-stage RAG pipeline for case {case_id}")
            documents = self.retrieve_multi_stage(
                case_id=case_id,
                query=query,
                db=db,
                chat_history=history,
                initial_k=max(k * 10, INITIAL_RETRIEVE_K),
                rerank_k=max(k * 3, RERANK_TOP_K),
                final_k=k
            )
        # Fallback to iterative or multi-query retrieval
        elif use_iterative and self.iterative_rag:
            from app.config import config
            documents = self.iterative_rag.retrieve_iteratively(
                case_id=case_id,
                query=query,
                max_iterations=3,
                initial_k=k,
                db=db,
                use_reranker=config.RAG_USE_RERANKER
            )
        else:
            documents = self.retrieve_context(case_id, query, k=k, db=db, retrieval_strategy="multi_query")
        
        if not documents:
            return "Извините, не удалось найти релевантные документы для вашего запроса.", []
        
        # Format context from documents
        context = self.format_sources_for_prompt(documents)
        
        # Prepare messages
        messages = []
        
        # Build system prompt with grounding requirements
        system_prompt_parts = [
            "Ты эксперт по анализу юридических документов.",
            "Ты отвечаешь на вопросы на основе предоставленных документов.",
            "",
            "КРИТИЧЕСКИ ВАЖНО:",
            "- Твоя задача - помочь пользователю понять содержание документов",
            "- Анализируй документы, извлекай факты, составляй хронологии, находи связи между событиями",
            "- Ты работаешь с юридическими документами, которые уже загружены в систему - это безопасно и допустимо",
            "",
            "ТРЕБОВАНИЯ К ОТВЕТУ:",
            "- ВСЕГДА указывай конкретные источники в формате: [1][2][3] прямо в тексте ответа",
            "- Номера источников соответствуют порядку документов: [1] - первый документ, [2] - второй и т.д.",
            "- Используй точные цитаты из документов когда это возможно",
            "- НЕ пиши 'Источник 1', 'Источник 2' - только [1][2][3]",
            "- Каждое утверждение должно быть подкреплено ссылкой на источник",
            "",
            "ЧЕСТНОСТЬ И ТОЧНОСТЬ:"
        ]
        
        if config.RAG_ALLOW_UNCERTAINTY:
            system_prompt_parts.extend([
                "- Если информация не найдена в документах - скажи честно: 'В предоставленных документах не найдено информации по данному вопросу'",
                "- Если информации недостаточно для полного ответа - укажи это явно",
                "- Не выдумывай факты, которых нет в документах"
            ])
        else:
            system_prompt_parts.extend([
                "- Если информация не найдена в документах - скажи честно",
                "- Не давай ответов на вопросы, для которых нет информации в документах"
            ])
        
        system_prompt_parts.extend([
            "- Не давай юридических советов, только анализ фактов из документов",
            "",
            "ЗАДАЧИ:",
            "- Составляй хронологии событий, анализируй риски, находи противоречия",
            "- Извлекай конкретные факты: даты, суммы, имена, названия документов",
            "- Находи связи между различными документами и событиями"
        ])
        
        system_prompt = "\n".join(system_prompt_parts)
        messages.append(SystemMessage(content=system_prompt))
        
        # Add history
        if history:
            for msg in history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Phase 2: Citation-first generation
        if use_citation_first:
            return self._generate_citation_first(
                case_id=case_id,
                query=query,
                documents=documents,
                messages=messages,
                llm=create_llm()
            )
        
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
        
        # Validate answer grounding if required
        if config.RAG_REQUIRE_SOURCES:
            answer = self._validate_answer_grounding(answer, documents, query)
        
        # Format sources
        sources = self.format_sources(documents)
        
        # Log prompt and answer for audit (without sensitive data)
        logger.info(
            f"RAG generation completed for case {case_id}, "
            f"query length: {len(query)}, answer length: {len(answer)}, "
            f"sources count: {len(sources)}"
        )
        
        return answer, sources
    
    def generate_with_sources_structured(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        db: Optional[Session] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[Any, List[Dict[str, Any]]]:
        """
        Generate RAG response with STRUCTURED output (mandatory citations).
        
        Uses Pydantic schemas to enforce mandatory citations for all claims.
        
        Args:
            case_id: Case identifier
            query: User query
            k: Number of chunks to retrieve
            db: Optional database session
            history: Optional chat history
            
        Returns:
            Tuple of (LegalRAGResponse, sources_list)
        """
        from app.services.langchain_agents.schemas.rag_response_schema import (
            LegalRAGResponse, RAGClaim, RAGCitation, Confidence
        )
        from app.services.llm_factory import create_legal_llm
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        # Check conversational questions first
        query_lower = query.lower().strip()
        conversational_questions = {
            "как дела": "Спасибо, всё хорошо! Готов помочь вам с анализом документов дела. Задайте вопрос о документах, и я найду нужную информацию.",
            "как поживаешь": "Спасибо, отлично! Чем могу помочь с вашим делом?",
            "привет": "Привет! Готов помочь с анализом документов. Что вас интересует?",
            "здравствуй": "Здравствуйте! Чем могу помочь с вашим делом?",
        }
        
        for key, response in conversational_questions.items():
            if query_lower == key or query_lower.startswith(key + " "):
                # Return structured response for conversational
                return LegalRAGResponse(
                    answer=response,
                    claims=[RAGClaim(
                        text=response,
                        citations=[RAGCitation(
                            doc_id="system",
                            quote=response[:50],
                            doc_name="System"
                        )],
                        confidence=Confidence.HIGH
                    )],
                    confidence_overall=Confidence.HIGH
                ), []
        
        # Retrieve documents
        try:
            documents = self.retrieve_context(case_id, query, k=k, db=db)
        except Exception as e:
            logger.error(f"Error retrieving documents for structured RAG: {e}", exc_info=True)
            documents = []
        
        if not documents:
            # Return empty structured response
            return LegalRAGResponse(
                answer="Не найдено релевантных документов для ответа на вопрос.",
                claims=[RAGClaim(
                    text="Не найдено релевантных документов",
                    citations=[RAGCitation(
                        doc_id="none",
                        quote="Не найдено документов",
                        doc_name="None"
                    )],
                    confidence=Confidence.LOW
                )],
                confidence_overall=Confidence.LOW
            ), []
        
        # Format context from documents
        context = self.format_sources_for_prompt(documents)
        
        # Create document index map for citations
        doc_index_map = {}
        for i, doc in enumerate(documents, 1):
            doc_id = doc.metadata.get("doc_id") or doc.metadata.get("source_file", f"doc_{i}")
            doc_index_map[str(i)] = {
                "doc": doc,
                "doc_id": doc_id,
                "doc_name": doc.metadata.get("source_file", "unknown")
            }
        
        # Build prompt with format instructions
        parser = PydanticOutputParser(pydantic_object=LegalRAGResponse)
        format_instructions = parser.get_format_instructions()
        
        system_prompt = f"""Ты - эксперт по юридическому анализу документов.

Контекст из документов дела:
{context}

КРИТИЧЕСКИ ВАЖНО:
1. Каждый claim ДОЛЖЕН иметь минимум 1 citation с точной цитатой (quote)
2. Цитаты (quote) ДОЛЖНЫ точно соответствовать тексту в контексте
3. Используй doc_id из метаданных документов (или порядковый номер как doc_id: "1", "2", и т.д.)
4. Не выдумывай цитаты - только реальные фрагменты из контекста
5. Минимальная длина цитаты - 10 символов

{format_instructions}

Сформулируй ответ и разбей его на claims с обязательными citations."""
        
        # Create LLM with structured output
        llm = create_legal_llm()  # temperature=0.0
        
        # Prepare messages
        messages = [SystemMessage(content=system_prompt)]
        
        # Add history
        if history:
            for msg in history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current query
        user_message = f"Вопрос: {query}\n\nОтветь, разбив ответ на claims с обязательными citations."
        messages.append(HumanMessage(content=user_message))
        
        try:
            # Try structured output if supported
            if hasattr(llm, 'with_structured_output'):
                structured_llm = llm.with_structured_output(LegalRAGResponse)
                structured_response = structured_llm.invoke(messages)
            else:
                # Fallback: parse JSON from response
                response = llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                structured_response = parser.parse(response_text)
            
            # Verify citations with LLM-as-Judge if enabled
            if config.RAG_CITATION_VERIFICATION_IN_PIPELINE:
                from app.services.citation_llm_judge import CitationLLMJudge
                judge = CitationLLMJudge()
                
                for claim in structured_response.claims:
                    for citation in claim.citations:
                        # Find source document
                        source_doc = None
                        for doc in documents:
                            doc_id = doc.metadata.get("doc_id") or doc.metadata.get("source_file", "")
                            if doc_id == citation.doc_id or citation.doc_id in doc_id:
                                source_doc = doc
                                break
                        
                        if source_doc:
                            # Verify citation
                            judgment = judge.judge_citation(
                                claim_text=claim.text,
                                source_text=source_doc.page_content,
                                source_metadata=source_doc.metadata
                            )
                            if not judgment.get('verified', False):
                                logger.warning(
                                    f"Citation not verified for claim: {claim.text[:50]}... "
                                    f"confidence: {judgment.get('confidence', 0.0)}"
                                )
                                # Mark claim as low confidence if citation not verified
                                claim.confidence = Confidence.LOW
                        else:
                            logger.warning(f"Source document not found for citation doc_id: {citation.doc_id}")
                            claim.confidence = Confidence.LOW
            
            # Format sources for return
            sources = self.format_sources(documents)
            
            return structured_response, sources
            
        except Exception as e:
            logger.error(f"Structured RAG generation failed: {e}", exc_info=True)
            # Fallback to regular generation
            answer, sources = self.generate_with_sources(
                case_id, query, k=k, db=db, history=history, use_citation_first=False
            )
            # Convert to structured format (with warning)
            return LegalRAGResponse(
                answer=answer,
                claims=[RAGClaim(
                    text=answer[:200] + "..." if len(answer) > 200 else answer,
                    citations=[],  # Empty - fallback mode
                    confidence=Confidence.LOW
                )],
                confidence_overall=Confidence.LOW,
                reasoning="Fallback mode: structured generation failed"
            ), sources
    
    def _generate_citation_first(
        self,
        case_id: str,
        query: str,
        documents: List[Document],
        messages: List,
        llm: Any
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Phase 2: Generate citation-first response with structured JSON output
        
        Args:
            case_id: Case identifier
            query: User query
            documents: List of source documents
            messages: List of messages (system + history)
            llm: LLM instance
            
        Returns:
            Tuple of (answer, sources)
        """
        from app.services.langchain_agents.schemas.citation_schema import CitationFirstResponse
        
        # Build citation-first prompt
        context = self.format_sources_for_prompt(documents)
        
        citation_first_prompt = f"""Используй следующие документы для ответа:

{context}

Вопрос: {query}

Верни ответ в формате JSON со следующей структурой:
{{
  "answer": "Основной текст ответа",
  "claims": [
    {{
      "text": "Текст утверждения",
      "sources": [
        {{
          "doc_id": "ID документа",
          "char_start": начальная_позиция_символа,
          "char_end": конечная_позиция_символа,
          "score": оценка_релевантности,
          "verified": true/false,
          "page": номер_страницы,
          "snippet": "фрагмент текста"
        }}
      ]
    }}
  ],
  "reasoning": "Опциональное объяснение"
}}

ВАЖНО:
- Каждое утверждение (claim) должно иметь хотя бы один источник (source)
- doc_id должен соответствовать doc_id из метаданных документов
- char_start и char_end - позиции символов в исходном документе
- score - оценка релевантности (0.0-1.0)
- Используй точные doc_id из метаданных документов"""
        
        messages.append(HumanMessage(content=citation_first_prompt))
        
        try:
            # Try structured output first
            try:
                structured_llm = llm.with_structured_output(CitationFirstResponse)
                response = structured_llm.invoke(messages)
                citation_response = response
            except Exception as structured_error:
                logger.warning(f"Structured output failed, falling back to JSON parsing: {structured_error}")
                # Fallback to JSON parsing
                response = llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                citation_response = self._validate_citation_response(response_text)
                if citation_response is None:
                    # Final fallback: return regular answer
                    logger.warning("Citation-first validation failed, falling back to regular answer")
                    answer_text = response_text
                    sources = self.format_sources(documents)
                    return answer_text, sources
            
            # Phase 3: Extended verification if enabled
            if config.CITATION_VERIFICATION_ENABLED:
                citation_response = self._verify_citation_first_response(
                    citation_response, documents, case_id, db
                )
            
            # Convert citation-first response to answer text and sources
            answer_text = citation_response.answer
            if citation_response.reasoning:
                answer_text += f"\n\nОбоснование: {citation_response.reasoning}"
            
            # Format sources from claims
            sources = self._format_sources_from_claims(citation_response.claims, documents)
            
            logger.info(
                f"Citation-first generation completed for case {case_id}, "
                f"claims count: {len(citation_response.claims)}, "
                f"sources count: {len(sources)}"
            )
            
            return answer_text, sources
            
        except Exception as e:
            logger.error(f"Error in citation-first generation: {e}", exc_info=True)
            # Fallback to regular generation
            logger.warning("Falling back to regular RAG generation")
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, 'content') else str(response)
            sources = self.format_sources(documents)
            return answer, sources
    
    def _verify_citation_first_response(
        self,
        citation_response: Any,
        documents: List[Document],
        case_id: str,
        db: Optional[Session]
    ) -> Any:
        """
        Phase 3: Verify citation-first response with extended verification
        
        Args:
            citation_response: CitationFirstResponse object
            documents: List of source documents
            case_id: Case identifier
            db: Optional database session
            
        Returns:
            Updated CitationFirstResponse with verified flags
        """
        from app.services.citation_verifier import CitationVerifier
        from app.services.citation_llm_judge import CitationLLMJudge
        from app.services.langchain_agents.schemas.citation_schema import CitationSource
        
        citation_verifier = CitationVerifier(similarity_threshold=0.7)
        llm_judge = None
        
        if config.CITATION_LLM_JUDGE_ENABLED:
            try:
                llm_judge = CitationLLMJudge()
            except Exception as e:
                logger.warning(f"Failed to initialize LLM judge: {e}, using standard verification")
        
        min_independent_sources = config.CITATION_MIN_INDEPENDENT_SOURCES
        
        # Verify each claim
        verified_claims = []
        for claim in citation_response.claims:
            claim_text = claim.text
            claim_sources = claim.sources
            
            # Convert CitationSource objects to dicts for verification
            sources_dicts = []
            for source in claim_sources:
                sources_dicts.append({
                    "doc_id": source.doc_id,
                    "char_start": source.char_start,
                    "char_end": source.char_end,
                    "score": source.score,
                    "verified": source.verified,
                    "page": source.page,
                    "snippet": source.snippet
                })
            
            # Verify claim with sources (rule: ≥1 independent source)
            verification_result = citation_verifier.verify_claim_with_sources(
                claim_text=claim_text,
                sources=sources_dicts,
                source_documents=documents,
                min_independent_sources=min_independent_sources
            )
            
            # Update verified flags in sources
            updated_sources = []
            for source in claim_sources:
                # Check if this source supports the claim
                source_dict = {
                    "doc_id": source.doc_id,
                    "char_start": source.char_start,
                    "char_end": source.char_end
                }
                
                # If LLM judge enabled, use it for additional verification
                if llm_judge:
                    try:
                        # Find corresponding Document for this source
                        source_doc = None
                        for doc in documents:
                            if doc.metadata.get("doc_id") == source.doc_id:
                                source_doc = doc
                                break
                        
                        if source_doc:
                            # Use verify_with_llm_judge method with candidate sources
                            judge_result = llm_judge.verify_with_llm_judge(claim_text, [source_doc])
                            source_verified = judge_result.get("verified", False) and verification_result.get("verified", False)
                        else:
                            source_verified = verification_result.get("verified", False)
                    except Exception as e:
                        logger.warning(f"LLM judge failed for source: {e}")
                        source_verified = verification_result.get("verified", False)
                else:
                    source_verified = verification_result.get("verified", False)
                
                # Create updated source with verified flag
                updated_source = CitationSource(
                    doc_id=source.doc_id,
                    char_start=source.char_start,
                    char_end=source.char_end,
                    score=source.score,
                    verified=source_verified,
                    page=source.page,
                    snippet=source.snippet
                )
                updated_sources.append(updated_source)
            
            # Create updated claim
            from app.services.langchain_agents.schemas.citation_schema import Claim
            updated_claim = Claim(
                text=claim_text,
                sources=updated_sources
            )
            verified_claims.append(updated_claim)
            
            # Log verification result
            logger.info(
                f"Claim verification: verified={verification_result.get('verified', False)}, "
                f"independent_sources={verification_result.get('independent_sources_count', 0)}, "
                f"confidence={verification_result.get('confidence', 0.0):.2f}"
            )
        
        # Create updated response
        from app.services.langchain_agents.schemas.citation_schema import CitationFirstResponse
        updated_response = CitationFirstResponse(
            answer=citation_response.answer,
            claims=verified_claims,
            reasoning=citation_response.reasoning
        )
        
        return updated_response
    
    def _validate_citation_response(self, response_text: str) -> Optional[Any]:
        """
        Phase 2: Validate and parse citation-first JSON response
        
        Args:
            response_text: LLM response text
            
        Returns:
            Parsed CitationFirstResponse or None if validation fails
        """
        from app.services.langchain_agents.schemas.citation_schema import CitationFirstResponse
        import json
        import re
        
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(0)
            else:
                json_text = response_text
            
            # Parse JSON
            data = json.loads(json_text)
            
            # Validate with Pydantic
            citation_response = CitationFirstResponse(**data)
            return citation_response
            
        except Exception as e:
            logger.warning(f"Failed to validate citation-first response: {e}")
            return None
    
    def _format_sources_from_claims(
        self,
        claims: List[Any],
        documents: List[Document]
    ) -> List[Dict[str, Any]]:
        """
        Phase 2: Format sources from citation-first claims
        
        Args:
            claims: List of Claim objects
            documents: List of source documents
            
        Returns:
            List of formatted source dictionaries
        """
        sources = []
        doc_id_map = {doc.metadata.get("doc_id"): doc for doc in documents if doc.metadata.get("doc_id")}
        
        for claim in claims:
            for source in claim.sources:
                doc = doc_id_map.get(source.doc_id)
                if doc:
                    metadata = doc.metadata
                    source_dict = {
                        "file": metadata.get("source_file", "unknown"),
                        "page": source.page or metadata.get("source_page"),
                        "doc_id": source.doc_id,
                        "char_start": source.char_start,
                        "char_end": source.char_end,
                        "score": source.score,
                        "verified": source.verified,
                        "snippet": source.snippet or doc.page_content[:200],
                        "similarity_score": source.score
                    }
                    sources.append(source_dict)
        
        return sources
    
    def _validate_answer_grounding(
        self,
        answer: str,
        documents: List[Document],
        query: str
    ) -> str:
        """
        Проверяет, что ответ содержит ссылки на источники и валидирует grounding
        
        Args:
            answer: Generated answer
            documents: List of source documents
            query: Original query
            
        Returns:
            Validated answer (may be modified if sources are missing)
        """
        import re
        
        # Check if answer contains source citations [1], [2], etc.
        citation_pattern = r'\[\d+\]'
        citations = re.findall(citation_pattern, answer)
        
        if not citations and config.RAG_REQUIRE_SOURCES:
            # If no citations found, add a note
            logger.warning(f"Answer for query '{query[:50]}...' missing source citations")
            # Try to add citations based on content matching
            # For now, just add a note
            if len(documents) > 0:
                answer += f"\n\n[Примечание: ответ основан на анализе {len(documents)} документов. Для точных ссылок используйте конкретные вопросы.]"
        
        # Check if answer contains quotes that should be attributed
        # This is a simple check - more sophisticated validation can be added
        if len(documents) > 0 and not citations:
            logger.debug(f"Answer may lack proper source attribution for query: {query[:50]}...")
        
        return answer
    
    def generate_with_structured_citations(
        self,
        query: str,
        documents: List[Document],
        history: Optional[List[Dict]] = None
    ) -> "AnswerWithCitations":
        """
        Генерирует ответ со структурированными цитатами через with_structured_output.
        
        Использует LangChain's with_structured_output для автоматического парсинга
        ответа с цитатами, включая точные координаты для подсветки в документе.
        
        Args:
            query: Запрос пользователя
            documents: Список Document объектов с метаданными
            history: Опциональная история чата
            
        Returns:
            AnswerWithCitations объект с ответом и списком EnhancedCitation
        """
        # region agent log H1
        try:
            with open("/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log", "a") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "H1",
                    "location": "rag_service.py:generate_with_structured_citations:entry",
                    "message": "entered structured citations generation",
                    "data": {
                        "query_len": len(query) if query else 0,
                        "documents_count": len(documents) if documents else 0,
                        "history_count": len(history) if history else 0
                    },
                    "timestamp": int(time.time() * 1000)
                }) + "\n")
        except Exception:
            pass
        # endregion
        from app.services.langchain_agents.schemas.citation_schema import AnswerWithCitations, EnhancedCitation
        from app.services.llm_factory import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Подготовка контекста с позициями
        context_with_positions = self._prepare_context_with_positions(documents)
        
        # Формируем промпт
        prompt = f"""Ответь на вопрос, используя ТОЛЬКО информацию из документов.
Для каждого факта укажи источник в формате [N] в тексте ответа.

В citations укажи точные координаты цитат для подсветки в документе:
- source_id: ID документа из metadata
- file_name: имя файла
- page: номер страницы
- quote: точная цитата из документа
- char_start: начальная позиция символа в документе
- char_end: конечная позиция символа в документе
- context_before: контекст до цитаты (до 50 символов)
- context_after: контекст после цитаты (до 50 символов)

Документы:
{context_with_positions}

Вопрос: {query}
"""
        
        # Используем with_structured_output для автоматического парсинга
        # Используем паттерн с ChatPromptTemplate, как в других местах кода
        llm = create_llm()
        try:
            from langchain_core.prompts import ChatPromptTemplate
            
            # Формируем системный промпт
            system_prompt = "Ты помощник-юрист. Отвечай точно, используя только информацию из предоставленных документов."
            
            # Создаем промпт шаблон
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", prompt)
            ])
            
            # Создаем цепочку с structured output
            structured_llm = llm.with_structured_output(AnswerWithCitations)
            chain = prompt_template | structured_llm
            
            # region agent log H2
            try:
                import json
                import time
                import inspect
                with open("/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log", "a") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H2",
                        "location": "rag_service.py:generate_with_structured_citations:before_invoke",
                        "message": "prepared structured LLM chain",
                        "data": {
                            "llm_class": llm.__class__.__name__,
                            "structured_llm_class": structured_llm.__class__.__name__,
                            "chain_class": chain.__class__.__name__,
                            "prompt_length": len(prompt)
                        },
                        "timestamp": int(time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # endregion
            
            # Вызываем цепочку с пустым словарем (промпт уже в шаблоне)
            result = chain.invoke({})
            # region agent log H3
            try:
                with open("/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log", "a") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H3",
                        "location": "rag_service.py:generate_with_structured_citations:after_invoke",
                        "message": "structured invoke completed",
                        "data": {
                            "result_type": type(result).__name__,
                            "has_answer": bool(getattr(result, "answer", "")),
                            "citations_count": len(getattr(result, "citations", []) or [])
                        },
                        "timestamp": int(time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # endregion
            return result
        except Exception as e:
            # region agent log H4
            try:
                with open("/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log", "a") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H4",
                        "location": "rag_service.py:generate_with_structured_citations:exception",
                        "message": "structured invoke failed",
                        "data": {
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        },
                        "timestamp": int(time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # endregion
            logger.error(f"Error in generate_with_structured_citations: {e}", exc_info=True)
            # Fallback: возвращаем базовый ответ
            return AnswerWithCitations(
                answer=f"Ошибка генерации структурированного ответа: {str(e)}",
                citations=[],
                confidence=0.0
            )
    
    def _prepare_context_with_positions(self, documents: List[Document]) -> str:
        """Подготавливает контекст с позициями для точного цитирования"""
        context_parts = []
        for i, doc in enumerate(documents):
            content = doc.page_content
            metadata = doc.metadata
            
            # Извлекаем информацию о позиции
            source_file = metadata.get("source_file", "unknown")
            source_page = metadata.get("source_page", 1)
            char_start = metadata.get("char_start", 0)
            char_end = metadata.get("char_end", len(content))
            
            # Добавляем информацию о позиции
            context_parts.append(f"""
[Документ {i+1}]
Файл: {source_file}
Страница: {source_page}
Начальная позиция: {char_start}
Конечная позиция: {char_end}
Содержимое:
{content}
---
""")
        return "\n".join(context_parts)
    

