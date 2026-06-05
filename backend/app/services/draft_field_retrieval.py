"""RAG для Draft Mode: общий контекст по делу и точечный дожим по полям."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.case_context_pipeline import (
    assemble_rag_output,
    final_k_for_budget,
    pipeline_enabled,
    recall_k_for_budget,
    rerank_and_resolve_documents,
    run_hybrid_recall,
)
from app.services.chat.retrieval_router import RetrievalTask, create_case_retrieval_router
from app.services.draft_template_schemas import TemplateFieldSpec
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


@contextmanager
def _worker_db_session(parent_db: Optional[Session]) -> Iterator[Optional[Session]]:
    """Отдельная SQLAlchemy-сессия на поток (не шарить request-scoped db)."""
    if parent_db is None:
        yield None
        return
    from app.utils.database import SessionLocal

    child = SessionLocal()
    try:
        yield child
    finally:
        child.close()


def _draft_field_budget_profile() -> Dict[str, Any]:
    final_k = int(getattr(config, "DRAFT_FIELD_FINAL_K", 5) or 5)
    recall_k = min(int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100), 40)
    return {
        "final_k": max(1, final_k),
        "recall_k": max(10, recall_k),
        "max_context_chars": 6000,
        "max_sources": final_k,
    }


def retrieve_for_template_field(
    *,
    rag_service: RAGService,
    case_id: str,
    field: TemplateFieldSpec,
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
    corpus_size: int = 0,
    query_cache: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    RAG для одного поля шаблона.

    Returns:
        (rag_context_text, serialized_docs, meta)
    """
    meta: Dict[str, Any] = {"field_id": field.field_id, "pipeline": pipeline_enabled()}
    query = (field.retrieval_query or field.what_to_find or field.semantic_label or field.marker).strip()
    if not query:
        return "", [], {**meta, "status": "empty_query"}

    if query_cache is not None and query in query_cache:
        return query_cache[query], [], {**meta, "status": "cache_hit", "cached": True}

    budget = _draft_field_budget_profile()
    final_k = final_k_for_budget(budget)

    retrieval_task: Optional[RetrievalTask] = None
    if db and pipeline_enabled():
        try:
            router = create_case_retrieval_router()
            retrieval_task = router.route(
                question=query,
                case_id=str(case_id),
                db=db,
                attached_file_ids=attached_file_ids,
                corpus_size=corpus_size,
            )
            meta["scope_mode"] = retrieval_task.scope_mode
            meta["router_confidence"] = retrieval_task.confidence
        except Exception as e:
            logger.warning("[draft_field_retrieval] router failed field=%s: %s", field.field_id, e)

    search_query = (retrieval_task.search_query if retrieval_task else None) or query

    if pipeline_enabled() and db:
        docs, recall_meta = run_hybrid_recall(
            rag_service=rag_service,
            case_id=case_id,
            question=search_query,
            db=db,
            retrieval_task=retrieval_task,
            attached_file_ids=attached_file_ids,
            budget_profile=budget,
        )
        meta.update(recall_meta)
        docs, _resolve_meta = rerank_and_resolve_documents(
            question=search_query,
            docs=docs,
            final_k=final_k,
            case_id=str(case_id),
            rag_service=rag_service,
            budget_profile=budget,
        )
        meta.update(_resolve_meta or {})
        out = assemble_rag_output(
            rag_service=rag_service,
            docs=docs,
            case_id=case_id,
            db=db,
            budget_profile=budget,
        )
        ctx = str(out.get("rag_context") or "")
        if query_cache is not None:
            query_cache[query] = ctx
        meta["docs"] = len(docs)
        return ctx, list(out.get("rag_documents") or []), meta

    # Fallback: прямой retrieve без pipeline
    k = max(3, final_k)
    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=search_query,
        k=k,
        retrieval_strategy="hybrid",
        db=db,
        use_hybrid=True,
        file_ids=list(attached_file_ids) if attached_file_ids else None,
    )
    snippets = [d.page_content[:1800] for d in (docs or []) if getattr(d, "page_content", "").strip()]
    ctx = "\n\n".join(snippets)[:6000]
    if query_cache is not None:
        query_cache[query] = ctx
    meta["docs"] = len(docs or [])
    meta["status"] = "direct_retrieve"
    return ctx, [], meta


def retrieve_bulk_document_context(
    *,
    rag_service: RAGService,
    case_id: str,
    query: str,
    db: Optional[Session] = None,
    attached_file_ids: Optional[List[str]] = None,
    k: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Один поиск по делу для заполнения всего шаблона (multi_query + hybrid).

    Returns:
        (rag_context_text, meta)
    """
    meta: Dict[str, Any] = {"mode": "bulk", "pipeline": pipeline_enabled()}
    q = (query or "").strip()
    if not q:
        return "", {**meta, "status": "empty_query"}

    top_k = k if k is not None else int(getattr(config, "DRAFT_BULK_RAG_K", 14) or 14)
    top_k = max(4, min(top_k, 20))
    max_chars = int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 20000) or 20000)
    strategy = str(getattr(config, "DRAFT_BULK_RAG_STRATEGY", "hybrid") or "hybrid").strip() or "hybrid"

    if db is not None:
        try:
            from app.utils.database import ensure_db_session_live

            ensure_db_session_live(db)
        except Exception as e:
            logger.warning("[draft_field_retrieval] bulk ensure_db_session_live: %s", e)

    file_ids = list(attached_file_ids) if attached_file_ids else None
    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=q,
        k=top_k,
        db=db,
        file_ids=file_ids,
        retrieval_strategy=strategy,
        use_hybrid=True,
    )
    meta["strategy"] = strategy
    snippets = [
        d.page_content[:1200]
        for d in (docs or [])
        if getattr(d, "page_content", "").strip()
    ]
    ctx = "\n\n".join(snippets)[:max_chars]
    meta["docs"] = len(docs or [])
    meta["k"] = top_k
    meta["status"] = "ok" if ctx else "no_snippets"
    return ctx, meta


def retrieve_fields_parallel(
    *,
    rag_service: RAGService,
    case_id: str,
    fields: List[TemplateFieldSpec],
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
    corpus_size: int = 0,
) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Параллельный RAG по полям. Returns field_id -> (context, meta)."""
    if not fields:
        return {}
    max_workers = max(1, int(getattr(config, "DRAFT_FIELD_RAG_MAX_PARALLEL", 4) or 4))
    query_cache: Dict[str, str] = {}
    results: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def _one(f: TemplateFieldSpec) -> Tuple[str, str, Dict[str, Any]]:
        with _worker_db_session(db) as worker_db:
            ctx, _docs, meta = retrieve_for_template_field(
                rag_service=rag_service,
                case_id=case_id,
                field=f,
                db=worker_db,
                attached_file_ids=attached_file_ids,
                corpus_size=corpus_size,
                query_cache=query_cache,
            )
        return f.field_id, ctx, meta

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_one, f): f.field_id for f in fields}
        for fut in as_completed(futures):
            fid = futures[fut]
            try:
                field_id, ctx, meta = fut.result()
                results[field_id] = (ctx, meta)
            except Exception as e:
                logger.warning("[draft_field_retrieval] field %s failed: %s", fid, e)
                results[fid] = ("", {"error": str(e)})
    return results


def retrieve_field_context_lightweight(
    *,
    rag_service: RAGService,
    case_id: str,
    field: TemplateFieldSpec,
    db: Optional[Session] = None,
    attached_file_ids: Optional[List[str]] = None,
    query_cache: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Узкий поиск для дожима: один hybrid без router/pipeline/rerank/multi_query.
    """
    meta: Dict[str, Any] = {"mode": "lightweight", "field_id": field.field_id}
    query = (field.retrieval_query or field.what_to_find or field.semantic_label or field.marker).strip()
    if not query:
        return "", {**meta, "status": "empty_query"}
    if query_cache is not None and query in query_cache:
        return query_cache[query], {**meta, "status": "cache_hit", "cached": True}

    k = max(3, int(getattr(config, "DRAFT_BULK_RETRY_RAG_K", 5) or 5))
    if db is not None:
        try:
            from app.utils.database import ensure_db_session_live

            ensure_db_session_live(db)
        except Exception as e:
            logger.warning("[draft_field_retrieval] light ensure_db_session_live: %s", e)

    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=query,
        k=k,
        db=db,
        file_ids=list(attached_file_ids) if attached_file_ids else None,
        retrieval_strategy="hybrid",
        use_hybrid=True,
    )
    snippets = [d.page_content[:1200] for d in (docs or []) if getattr(d, "page_content", "").strip()]
    ctx = "\n\n".join(snippets)[:4000]
    if query_cache is not None:
        query_cache[query] = ctx
    meta["docs"] = len(docs or [])
    meta["status"] = "ok" if ctx else "no_snippets"
    return ctx, meta


def retrieve_fields_retry_lightweight(
    *,
    rag_service: RAGService,
    case_id: str,
    fields: List[TemplateFieldSpec],
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Лёгкий параллельный дожим только если shared bulk-контекста не хватило."""
    if not fields:
        return {}
    max_workers = max(1, min(3, int(getattr(config, "DRAFT_FIELD_RAG_MAX_PARALLEL", 4) or 4)))
    query_cache: Dict[str, str] = {}
    out: Dict[str, str] = {}

    def _one(f: TemplateFieldSpec) -> Tuple[str, str]:
        with _worker_db_session(db) as worker_db:
            ctx, _meta = retrieve_field_context_lightweight(
                rag_service=rag_service,
                case_id=case_id,
                field=f,
                db=worker_db,
                attached_file_ids=attached_file_ids,
                query_cache=query_cache,
            )
        return f.field_id, ctx

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_one, f): f.field_id for f in fields}
        for fut in as_completed(futures):
            fid = futures[fut]
            try:
                field_id, ctx = fut.result()
                out[field_id] = ctx
            except Exception as e:
                logger.warning("[draft_field_retrieval] light retry field %s: %s", fid, e)
                out[fid] = ""
    return out
