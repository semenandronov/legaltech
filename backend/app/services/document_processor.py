"""Document processor service using LangChain."""
from typing import List, Dict, Any, Optional, Literal
import threading
from langchain_core.documents import Document
from app.config import config
from app.services.yandex_embeddings import get_yandex_embeddings
from app.services.chunk_ids import generate_chunk_id
from app.services.bm25_retriever import BM25Retriever
from app.services.file_char_basis import (
    CHAR_BASIS_DOCLING_DIRECT,
    attach_char_basis,
    docling_direct_char_basis,
    peel_char_basis,
)
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

_document_processor_singleton: Optional["DocumentProcessor"] = None
_document_processor_lock = threading.Lock()


class DocumentProcessor:
    """Service for processing documents with LangChain"""
    
    def __init__(self):
        """Initialize document processor"""
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
            self.embeddings = get_yandex_embeddings()
            logger.info("✅ Using Yandex embeddings (shared instance)")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex embeddings: {e}")
            raise ValueError(f"Ошибка инициализации Yandex embeddings: {str(e)}")
        
        # Initialize PGVector store (only vector store supported)
        try:
            from app.services.pgvector_store import CaseVectorStore
            self.vector_store = CaseVectorStore(embeddings=self.embeddings)
            logger.info("✅ Using PGVector store (production-ready, multi-tenant)")
        except Exception as e:
            logger.error(f"Failed to initialize PGVector store: {e}", exc_info=True)
            raise ValueError(f"Ошибка инициализации PGVector store: {str(e)}")
        
        # Initialize BM25 retriever for hybrid search
        self.bm25_retriever = BM25Retriever()
    
    def split_documents(
        self,
        text: str,
        filename: str,
        metadata: Dict[str, Any] = None,
        file_id: Optional[str] = None,
        langchain_docs: Optional[List[Document]] = None,
        content_bytes: Optional[bytes] = None,
        prepared_pdf_text: Optional[str] = None,
    ) -> List[Document]:
        """
        Build vector-ready chunks directly from Docling/LangChain loader output.

        Modes:
            * `LEGAL_CHUNKING_DUAL_ENABLED=True` (по умолчанию): сначала пытаемся
              разрезать документ через `LegalChunkerV2` (Docling AST → macro/micro,
              контракт v2.1). При любой ошибке — fallback на strict docling-direct-v1
              из `langchain_docs`.
            * Иначе: strict mode из `langchain_docs` (контракт docling-direct-v1).

        Returns:
            List of Document objects with deterministic chunk ids and character offsets.
        """
        import uuid

        # Create base metadata
        doc_metadata = {
            "source_file": filename,
            **(metadata or {})
        }

        doc_id = file_id if file_id else str(uuid.uuid4())
        doc_metadata["doc_id"] = doc_id

        if file_id:
            doc_metadata["file_id"] = file_id

        documents: List[Document] = []
        pending_char_basis: Optional[tuple[str, Optional[str]]] = None

        dual_enabled = bool(getattr(config, "LEGAL_CHUNKING_DUAL_ENABLED", True))
        if dual_enabled:
            try:
                from app.services.document_indexing import build_index_chunks

                # Скан → loader OCR (Yandex): skip Docling, chunk OCR markdown/text.
                # Native PDF text (PyPDF) → Docling AST with do_ocr=False (structure only).
                loader_did_ocr = False
                loader_native_text = False
                if langchain_docs:
                    for ld in langchain_docs:
                        try:
                            md = getattr(ld, "metadata", None) or {}
                            if md.get("ocr") is True or str(md.get("ocr_engine") or "").strip():
                                loader_did_ocr = True
                                loader_native_text = False
                                break
                            if md.get("docling_scan_preflight") is True:
                                # Legacy ingest path: OCR text without re-running Docling in chunker.
                                loader_did_ocr = True
                                loader_native_text = False
                                break
                            if str(md.get("extraction_source") or "").strip() == "native_text":
                                loader_native_text = True
                        except Exception:
                            continue

                fallback_for_chunker = text
                if loader_did_ocr and langchain_docs:
                    md_parts = []
                    for ld in langchain_docs:
                        meta = getattr(ld, "metadata", None) or {}
                        piece = meta.get("yandex_markdown") or ld.page_content or ""
                        if str(piece).strip():
                            md_parts.append(str(piece).strip())
                    if md_parts:
                        fallback_for_chunker = "\n\n".join(md_parts)

                case_id_val = str(doc_metadata.get("case_id") or "").strip()
                use_norm_corpus = (
                    case_id_val == "GLOBAL_LEGAL_CORPUS"
                    and bool(getattr(config, "LEGAL_CORPUS_NORM_CHUNKING_ENABLED", True))
                )
                v2_documents = build_index_chunks(
                    content_bytes=content_bytes,
                    filename=filename,
                    base_metadata=doc_metadata,
                    doc_type=str(doc_metadata.get("doc_type") or "").strip(),
                    case_id=case_id_val or None,
                    fallback_text=fallback_for_chunker,
                    loader_did_ocr=loader_did_ocr,
                    loader_native_text=loader_native_text and not loader_did_ocr,
                    loader_documents=langchain_docs if loader_did_ocr else None,
                    use_norm_corpus=use_norm_corpus,
                    prepared_pdf_text=prepared_pdf_text,
                )
                if v2_documents:
                    # Carrier holds citation full-text; exclude from chunk budget.
                    v2_documents, basis_text, basis_name = peel_char_basis(v2_documents)
                    if use_norm_corpus:
                        norm_n = sum(
                            1 for d in v2_documents if d.metadata.get("chunk_level") == "norm"
                        )
                        logger.info(
                            "[LegalChunkerV2] %s: produced %s norm chunks (profile=%s, preseg=%s)",
                            filename,
                            norm_n,
                            v2_documents[0].metadata.get("chunk_profile") if v2_documents else "?",
                            v2_documents[0].metadata.get("preseg_strategy") if v2_documents else "?",
                        )
                    else:
                        macro_n = sum(1 for d in v2_documents if d.metadata.get("chunk_level") == "macro")
                        micro_n = sum(1 for d in v2_documents if d.metadata.get("chunk_level") == "micro")
                        preamble_n = sum(
                            1 for d in v2_documents if d.metadata.get("chunk_level") == "preamble"
                        )
                        row_n = sum(1 for d in v2_documents if d.metadata.get("chunk_level") == "row")
                        profile_label = (
                            v2_documents[0].metadata.get("index_profile")
                            or v2_documents[0].metadata.get("chunk_profile")
                            if v2_documents
                            else "?"
                        )
                        logger.info(
                            "[document_indexing] %s: produced %s chunks "
                            "(macro=%s, micro=%s, preamble=%s, row=%s, profile=%s, preseg=%s)",
                            filename,
                            len(v2_documents),
                            macro_n,
                            micro_n,
                            preamble_n,
                            row_n,
                            profile_label,
                            v2_documents[0].metadata.get("preseg_strategy") if v2_documents else "?",
                        )
                    documents = v2_documents
                    if basis_text:
                        pending_char_basis = (basis_text, basis_name)
            except Exception as e:
                logger.warning(
                    "[LegalChunkerV2] failed for %s: %s — fallback to docling-direct-v1",
                    filename,
                    e,
                    exc_info=True,
                )
                pending_char_basis = None

        if not documents:
            if not langchain_docs:
                raise ValueError(
                    "Direct Docling ingestion requires loader chunks; plain-text re-chunking is disabled."
                )
            offset = 0
            sep_len = 2  # "\n\n" joiner used by ingestion text reconstruction

            for idx, src_doc in enumerate(langchain_docs):
                chunk_text = str((src_doc.page_content or "")).strip()
                if not chunk_text:
                    continue
                source_meta = dict(src_doc.metadata or {})
                char_start = offset
                char_end = char_start + len(chunk_text)
                chunk_id = generate_chunk_id(str(doc_id), idx, char_start)

                chunk_meta: Dict[str, Any] = {
                    **doc_metadata,
                    **source_meta,
                    "source_file": filename,
                    "chunk_id": chunk_id,
                    "chunk_index": idx,
                    "char_start": char_start,
                    "char_end": char_end,
                    "chunk_level": "docling",
                    "chunking_contract_version": "docling-direct-v1",
                    "char_basis": CHAR_BASIS_DOCLING_DIRECT,
                }

                documents.append(Document(page_content=chunk_text, metadata=chunk_meta))
                offset = char_end + sep_len

            pending_char_basis = (
                docling_direct_char_basis(langchain_docs),
                CHAR_BASIS_DOCLING_DIRECT,
            )

        if not documents:
            raise ValueError(
                "Docling returned no non-empty chunks for indexing; strict ingestion aborted."
            )

        # Chunk budget: regular cases vs GLOBAL_LEGAL_CORPUS (legal reference library).
        budget = int(config.LEGAL_CHUNKING_BUDGET_MAX_TOTAL_CHUNKS)
        try:
            case_id = (doc_metadata or {}).get("case_id")  # type: ignore[name-defined]
        except Exception:
            case_id = None
        if case_id == "GLOBAL_LEGAL_CORPUS":
            budget = int(getattr(config, "LEGAL_CORPUS_BUDGET_MAX_TOTAL_CHUNKS", budget))

        # budget <= 0 means "no truncation"
        if budget > 0:
            max_chunks = int(budget)
            if len(documents) > max_chunks:
                logger.warning(
                    "Chunk budget exceeded for %s: %s > %s, truncating",
                    filename,
                    len(documents),
                    max_chunks,
                )
                documents = documents[:max_chunks]

        warn_threshold = int(getattr(config, "LEGAL_CHUNK_COUNT_WARN_THRESHOLD", 2000) or 2000)
        if warn_threshold > 0 and len(documents) > warn_threshold:
            logger.warning(
                "Anomalous chunk count for %s: %s chunks (threshold=%s). "
                "Check parser output or sharding.",
                filename,
                len(documents),
                warn_threshold,
            )

        if pending_char_basis:
            basis_text, basis_name = pending_char_basis
            if basis_text:
                documents = attach_char_basis(
                    documents, basis_text, basis_name or CHAR_BASIS_DOCLING_DIRECT
                )

        try:
            from app.services.document_zones import annotate_documents_with_zones

            doc_chars = len(text) if isinstance(text, str) and text.strip() else None
            if doc_chars is None and pending_char_basis and pending_char_basis[0]:
                doc_chars = len(pending_char_basis[0])
            annotate_documents_with_zones(documents, document_chars=doc_chars)
        except Exception as zone_exc:
            logger.warning(
                "Zone annotation skipped for %s: %s",
                filename,
                zone_exc,
                exc_info=True,
            )

        return documents

    def create_embeddings(self, documents: List[Document], batch_size: int = 100) -> List[List[float]]:
        """
        Create embeddings for documents with batch processing
        
        Args:
            documents: List of Document objects
            batch_size: Number of documents to process in each batch (default: 100)
            
        Returns:
            List of embedding vectors
        """
        texts: List[str] = []
        for doc in documents:
            md = doc.metadata or {}
            et = md.get("embedding_text")
            if isinstance(et, str) and et.strip():
                texts.append(et.strip())
            else:
                texts.append(doc.page_content or "")

        # Process in batches to avoid memory issues and rate limits
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self.embeddings.embed_documents(batch_texts)
            all_embeddings.extend(batch_embeddings)
            logger.debug(f"Processed embeddings batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")
        
        return all_embeddings
    
    def store_in_vector_db(
        self,
        case_id: str,
        documents: List[Document],
        db: Session,
        original_files: Dict[str, bytes] = None,
        *,
        bm25_after_store: Literal["schedule", "invalidate_only"] = "schedule",
    ) -> str:
        """
        Store documents in PGVector database
        
        Args:
            case_id: Case identifier
            documents: List of Document objects
            db: Database session (not used, kept for API compatibility)
            original_files: Ignored (kept for API compatibility)
            
        Returns:
            collection_name
        """
        if not documents:
            raise ValueError(f"No documents provided for case {case_id}. Cannot store in PGVector without documents.")

        # Never persist ingest-only char-basis carriers.
        documents, _basis_text, _basis_name = peel_char_basis(documents)
        if not documents:
            raise ValueError(
                f"No indexable documents for case {case_id} after peeling char-basis carrier."
            )
        
        logger.info(f"Storing {len(documents)} document chunks in PGVector for case {case_id}")
        
        try:
            # Add case_id to all document metadata for multi-tenant filtering
            for doc in documents:
                doc.metadata["case_id"] = case_id

            # Re-index same file_id: remove previous vectors so partial retries do not duplicate rows.
            file_ids = {str(d.metadata.get("file_id") or "") for d in documents if d.metadata.get("file_id")}
            for fid in file_ids:
                if fid:
                    self.vector_store.delete_file_vectors(fid)

            # Store documents in PGVector
            ids = self.vector_store.add_documents(documents, case_id=case_id)
            logger.info(f"✅ Stored {len(ids)} documents in PGVector for case {case_id}")

            # Structured-table rows → SQL for deterministic transaction queries (optional).
            try:
                from app.config import config as app_config
                if getattr(app_config, "CASE_FILE_TRANSACTIONS_ENABLED", False):
                    from app.services.case_file_transaction_service import (
                        CaseFileTransactionService,
                        feature_enabled,
                    )

                    if feature_enabled():
                        by_file: Dict[str, List[Document]] = {}
                        names: Dict[str, str] = {}
                        for doc in documents:
                            fid = str(doc.metadata.get("file_id") or "")
                            if not fid:
                                continue
                            by_file.setdefault(fid, []).append(doc)
                            names[fid] = str(
                                doc.metadata.get("source_file")
                                or doc.metadata.get("filename")
                                or fid
                            )
                        for fid, file_docs in by_file.items():
                            CaseFileTransactionService.sync_from_documents(
                                db,
                                case_id=case_id,
                                file_id=fid,
                                filename=names.get(fid, fid),
                                documents=file_docs,
                            )
            except Exception as tx_exc:
                logger.warning(
                    "Case file transaction sync failed case=%s: %s",
                    case_id,
                    tx_exc,
                    exc_info=True,
                )

            if getattr(config, "CASE_BM25_PREWARM_ENABLED", True):
                try:
                    from app.services.bm25_case_prewarm import invalidate_bm25_index, schedule_bm25_prewarm

                    invalidate_bm25_index(case_id, self)
                    if bm25_after_store == "schedule":
                        schedule_bm25_prewarm(case_id, force_rebuild=True)
                except Exception as bm25_exc:
                    logger.warning(
                        "BM25 after store failed case=%s mode=%s: %s",
                        case_id,
                        bm25_after_store,
                        bm25_exc,
                    )
            
            # Return collection name as identifier
            return self.vector_store.collection_name
        except Exception as e:
            logger.error(f"Failed to store documents in PGVector for case {case_id}: {e}", exc_info=True)
            raise

    def prewarm_bm25_index(
        self,
        case_id: str,
        *,
        documents: Optional[List[Document]] = None,
        force_rebuild: bool = False,
    ) -> bool:
        """
        Pre-build BM25 index proactively to avoid first-query latency spike.

        Args:
            case_id: Case identifier
            documents: Optional chunk list. When provided it MUST be the complete
                case corpus already — a partial batch silently replaces the whole
                in-memory index. Prefer ``prewarm_bm25_from_store`` /
                ``finalize_case_bm25_after_ingestion`` after file ingest.
            force_rebuild: Rebuild index even if one already exists

        Returns:
            True if index is available after call, else False
        """
        if not self.bm25_retriever.available:
            logger.info("BM25 prewarm skipped: retriever unavailable")
            return False

        if self.bm25_retriever.has_index(case_id) and not force_rebuild:
            return True

        docs_for_index = documents or []
        if not docs_for_index:
            return self.prewarm_bm25_from_store(case_id, force_rebuild=force_rebuild)

        try:
            if force_rebuild and self.bm25_retriever.has_index(case_id):
                self.bm25_retriever.remove_index(case_id)
            ok = self.bm25_retriever.build_index(case_id, docs_for_index)
            if ok:
                logger.info(
                    "✅ BM25 prewarm complete for case %s (%s docs)",
                    case_id,
                    len(docs_for_index),
                )
            return ok
        except Exception as e:
            logger.warning("BM25 prewarm failed for case %s: %s", case_id, e, exc_info=True)
            return False

    def prewarm_bm25_from_store(
        self,
        case_id: str,
        *,
        force_rebuild: bool = False,
        chunk_levels: Optional[List[str]] = None,
    ) -> bool:
        """Построить BM25 из чанков PGVector (источник истины для дела)."""
        if not self.bm25_retriever.available:
            return False
        if self.bm25_retriever.has_index(case_id) and not force_rebuild:
            return True
        max_chunks = max(100, int(getattr(config, "CASE_BM25_MAX_CHUNKS", 2500) or 2500))
        docs = self.vector_store.list_case_chunks(
            case_id,
            limit=max_chunks,
            chunk_levels=chunk_levels,
        )
        if not docs:
            logger.info("BM25 prewarm: no PGVector chunks for case %s", case_id)
            return False
        return self.prewarm_bm25_index(
            case_id,
            documents=docs,
            force_rebuild=force_rebuild,
        )
    
    def retrieve_relevant_chunks(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        distance_threshold: float = 1.5,
        db: Optional[Session] = None,
        chunk_levels: Optional[List[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> List[Document]:
        """
        Retrieve relevant document chunks using PGVector search
        
        Args:
            case_id: Case identifier
            query: Search query
            k: Number of chunks to retrieve
            distance_threshold: Maximum distance threshold (for filtering)
            db: Optional database session (not used, kept for API compatibility)
            
        Returns:
            List of relevant Document objects with scores
        """
        try:
            # Search in PGVector with case_id filter (multi-tenant isolation)
            filter_payload = self._build_search_filter(chunk_levels=chunk_levels, metadata_filter=metadata_filter)
            documents = self.vector_store.similarity_search(
                query=query,
                case_id=case_id,
                k=k,
                filter=filter_payload,
                query_embedding=query_embedding,
            )
            
            # Filter by distance threshold if provided
            if distance_threshold < 1.5:  # Only filter if threshold is meaningful
                # Get documents with scores
                docs_with_scores = self.vector_store.similarity_search_with_score(
                    query=query,
                    case_id=case_id,
                    k=k * 2,  # Get more to filter
                    filter=filter_payload,
                    query_embedding=query_embedding,
                )
                # Filter by distance threshold
                filtered_docs = []
                for doc, score in docs_with_scores:
                    # Score is distance (lower = better)
                    if score <= distance_threshold:
                        filtered_docs.append(doc)
                        if len(filtered_docs) >= k:
                            break
                documents = filtered_docs
            
            if not documents:
                logger.warning(f"No relevant chunks found for case {case_id} in PGVector")
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving chunks from PGVector for case {case_id}: {e}", exc_info=True)
            raise
    
    def hybrid_search(
        self,
        case_id: str,
        query: str,
        k: int = 10,
        alpha: float = 0.7,
        db: Optional[Session] = None,
        chunk_levels: Optional[List[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        bm25_sync: Optional[bool] = None,
        query_embedding: Optional[List[float]] = None,
        exact_query: Optional[str] = None,
    ) -> List[Document]:
        """
        Hybrid search: объединяет dense search (semantic) и sparse search (BM25)
        
        Args:
            case_id: Case identifier
            query: Semantic search query (dense / FTS / BM25)
            k: Number of documents to retrieve
            alpha: Weight for dense search (0.0-1.0), sparse weight = 1.0 - alpha
                  alpha=0.7 означает 70% weight для dense, 30% для sparse
            db: Optional database session (not used, kept for API compatibility)
            exact_query: Optional clause anchor for boundary-exact recall (e.g. "1.4")
            
        Returns:
            List of relevant Document objects with combined scores
        """
        try:
            from app.services.bm25_case_prewarm import ensure_bm25_index, schedule_bm25_prewarm
            from app.services.observability.case_assistant_langfuse_tracing import (
                case_assistant_detailed_tracing_enabled,
                case_assistant_span,
                summarize_metadata_filter,
            )

            _trace_hybrid = case_assistant_detailed_tracing_enabled()
            _chunk_label = (
                ",".join(str(x) for x in (chunk_levels or [])) if chunk_levels else "default"
            )
            _hybrid_meta = {
                "case_id": case_id,
                "chunk_levels": _chunk_label,
                "alpha": alpha,
                "k": k,
            }

            if self.bm25_retriever.available:
                sync_bm25 = (
                    bm25_sync
                    if bm25_sync is not None
                    else bool(getattr(config, "CASE_BM25_SYNC_ON_HYBRID_SEARCH", True))
                )
                if sync_bm25:
                    ensure_bm25_index(self, case_id)
                elif not self.bm25_retriever.has_index(case_id):
                    schedule_bm25_prewarm(case_id)

            filter_payload = self._build_search_filter(
                chunk_levels=chunk_levels, metadata_filter=metadata_filter
            )
            _scope = summarize_metadata_filter(metadata_filter)

            def _hybrid_step(step: str):
                if not _trace_hybrid:
                    from contextlib import nullcontext

                    return nullcontext()
                return case_assistant_span(
                    f"hybrid_search.{step}",
                    metadata={**_hybrid_meta, "scope": _scope},
                )

            # 1. Dense search (semantic search via PGVector)
            with _hybrid_step("dense") as dense_out:
                dense_docs = self.retrieve_relevant_chunks(
                    case_id=case_id,
                    query=query,
                    k=k * 2,
                    db=db,
                    chunk_levels=chunk_levels,
                    metadata_filter=metadata_filter,
                    query_embedding=query_embedding,
                )
                if isinstance(dense_out, dict):
                    dense_out["docs_count"] = len(dense_docs or [])

            # 2. Sparse search: prefer native PostgreSQL FTS (persistent), fallback to BM25.
            with _hybrid_step("fts") as fts_out:
                sparse_docs = self.vector_store.keyword_search(
                    query=query,
                    case_id=case_id,
                    k=k * 2,
                    filter=filter_payload,
                )
                if isinstance(fts_out, dict):
                    fts_out["docs_count"] = len(sparse_docs or [])

            # Product requirement: address/anchor queries (e.g. "пункт 6.8") must have
            # deterministic clause-boundary recall (not ILIKE %1.4% false positives).
            anchor_docs: List[Document] = []
            if hasattr(self.vector_store, "anchor_substring_search"):
                try:
                    with _hybrid_step("anchor") as anchor_out:
                        anchor_docs = self.vector_store.anchor_substring_search(
                            query=query,
                            case_id=case_id,
                            k=k * 2,
                            filter=filter_payload,
                            exact_query=exact_query,
                        )
                        if isinstance(anchor_out, dict):
                            anchor_out["docs_count"] = len(anchor_docs or [])
                            if exact_query:
                                anchor_out["exact_query"] = str(exact_query)[:64]
                    if anchor_docs:
                        logger.info(
                            "Anchor clause-boundary search hit for case %s "
                            "(returned %s docs, exact_query=%r)",
                            case_id,
                            len(anchor_docs),
                            exact_query,
                        )
                except Exception as e:
                    logger.warning(
                        "Anchor substring search failed for case %s: %s", case_id, e, exc_info=True
                    )

            if anchor_docs:
                merged_sparse: List[Document] = []
                seen_ids = set()
                for doc in anchor_docs + (sparse_docs or []):
                    try:
                        did = self._get_doc_id(doc)
                    except Exception:
                        did = None
                    key = did or str(id(doc))
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    merged_sparse.append(doc)
                sparse_docs = merged_sparse

            if not sparse_docs and self.bm25_retriever.has_index(case_id):
                with _hybrid_step("bm25_fallback") as bm25_out:
                    sparse_docs = self.bm25_retriever.retrieve(case_id, query, k=k * 2)
                    if isinstance(bm25_out, dict):
                        bm25_out["docs_count"] = len(sparse_docs or [])
                        bm25_out["unscoped_index"] = True

            with _hybrid_step("rrf") as rrf_out:
                rrf_scores: Dict[str, float] = {}
                rrf_docs: Dict[str, Document] = {}

                for rank, doc in enumerate(dense_docs, start=1):
                    doc_id = self._get_doc_id(doc)
                    rrf_score = alpha * (1.0 / (60 + rank))
                    if doc_id not in rrf_scores:
                        rrf_scores[doc_id] = 0.0
                        rrf_docs[doc_id] = doc
                    rrf_scores[doc_id] += rrf_score
                    if hasattr(doc, "metadata") and "similarity_score" not in doc.metadata:
                        doc.metadata["similarity_score"] = 1.0 - (
                            rank / max(len(dense_docs), 1)
                        )

                for rank, doc in enumerate(sparse_docs, start=1):
                    doc_id = self._get_doc_id(doc)
                    rrf_score = (1.0 - alpha) * (1.0 / (60 + rank))
                    if doc_id not in rrf_scores:
                        rrf_scores[doc_id] = 0.0
                        rrf_docs[doc_id] = doc
                    rrf_scores[doc_id] += rrf_score
                    if hasattr(doc, "metadata") and "bm25_score" not in doc.metadata:
                        doc.metadata["bm25_score"] = 0.0

                sorted_docs = sorted(
                    rrf_docs.items(),
                    key=lambda x: rrf_scores[x[0]],
                    reverse=True,
                )
                # Clause-boundary hits must surface first: RRF with alpha=0.7 otherwise
                # lets dense similarity bury the correct пункт behind related sections.
                result_docs: List[Document] = []
                seen_result: set = set()
                if anchor_docs:
                    for doc in anchor_docs:
                        try:
                            did = self._get_doc_id(doc)
                        except Exception:
                            did = None
                        key = did or str(id(doc))
                        if key in seen_result:
                            continue
                        seen_result.add(key)
                        if hasattr(doc, "metadata"):
                            doc.metadata["combined_score"] = max(
                                float(doc.metadata.get("combined_score") or 0.0),
                                1.0,
                            )
                        result_docs.append(doc)
                        if len(result_docs) >= k:
                            break
                for doc_id, doc in sorted_docs:
                    if len(result_docs) >= k:
                        break
                    if doc_id in seen_result:
                        continue
                    seen_result.add(doc_id)
                    if hasattr(doc, "metadata"):
                        doc.metadata["combined_score"] = float(rrf_scores[doc_id])
                    else:
                        doc.metadata = {"combined_score": float(rrf_scores[doc_id])}
                    result_docs.append(doc)
                if isinstance(rrf_out, dict):
                    rrf_out["dense_in"] = len(dense_docs or [])
                    rrf_out["sparse_in"] = len(sparse_docs or [])
                    rrf_out["anchor_boosted"] = len(anchor_docs or [])
                    rrf_out["docs_out"] = len(result_docs)

            logger.info(
                "Hybrid search for case %s returned %s documents (alpha=%s)",
                case_id,
                len(result_docs),
                alpha,
            )
            return result_docs
            
        except Exception as e:
            logger.error(f"Error in hybrid search for case {case_id}: {e}", exc_info=True)
            # Fallback to dense search only
            logger.warning("Falling back to dense search only")
            return self.retrieve_relevant_chunks(
                case_id,
                query,
                k=k,
                db=db,
                chunk_levels=chunk_levels,
                metadata_filter=metadata_filter,
            )

    @staticmethod
    def _expand_chunk_levels(levels: List[str]) -> List[str]:
        """Map narrative levels to structured-table equivalents for hybrid search."""
        expanded: List[str] = []
        seen: set[str] = set()
        for level in levels:
            normalized = str(level).strip().lower()
            if not normalized:
                continue
            aliases: List[str]
            if normalized == "macro":
                aliases = ["macro", "preamble"]
            elif normalized == "micro":
                aliases = ["micro", "row"]
            else:
                aliases = [normalized]
            for alias in aliases:
                if alias not in seen:
                    seen.add(alias)
                    expanded.append(alias)
        return expanded

    @staticmethod
    def _build_search_filter(
        chunk_levels: Optional[List[str]],
        metadata_filter: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        result: Dict[str, Any] = dict(metadata_filter or {})
        if not chunk_levels:
            return result or None
        normalized = DocumentProcessor._expand_chunk_levels(
            [str(level).strip().lower() for level in chunk_levels if str(level).strip()]
        )
        if not normalized:
            return result or None
        if len(normalized) == 1:
            result["chunk_level"] = normalized[0]
        else:
            result["chunk_level"] = normalized
        return result or None
    
    def _get_doc_id(self, doc: Document) -> str:
        """
        Генерирует уникальный ID для документа для использования в RRF
        
        Args:
            doc: Document object
            
        Returns:
            String ID for the document
        """
        # Используем комбинацию source_file и chunk_index если доступно
        if hasattr(doc, 'metadata'):
            source = doc.metadata.get('source_file', 'unknown')
            chunk_idx = doc.metadata.get('chunk_index', 0)
            return f"{source}:{chunk_idx}"
        else:
            # Fallback: используем hash от содержимого
            return str(hash(doc.page_content[:100]))
    
    def get_index_id(self, case_id: str, db: Optional[Session] = None) -> Optional[str]:
        """
        Get collection identifier for case (PGVector)
        
        Args:
            case_id: Case identifier
            db: Optional database session (not used, kept for API compatibility)
            
        Returns:
            collection_name (all cases share collection, filtered by metadata)
        """
        # For PGVector, return collection name (all cases share collection, filtered by metadata)
        return self.vector_store.collection_name


def get_document_processor() -> DocumentProcessor:
    """Return process-wide DocumentProcessor singleton."""
    global _document_processor_singleton
    if _document_processor_singleton is None:
        with _document_processor_lock:
            if _document_processor_singleton is None:
                _document_processor_singleton = DocumentProcessor()
    return _document_processor_singleton

