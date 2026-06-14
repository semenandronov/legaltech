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

_EDITOR_RAG_FILE_PREFIXES = ("editor_doc_", "editor_")


def is_editor_rag_file_id(file_id: str) -> bool:
    """Виртуальные file_id из текстового редактора — не материалы загруженного дела."""
    fid = str(file_id or "").strip()
    return any(fid.startswith(p) for p in _EDITOR_RAG_FILE_PREFIXES)


def resolve_bulk_case_file_ids(
    db: Optional[Session],
    case_id: str,
    attached_file_ids: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """
    ID только загруженных файлов дела (таблица files), без черновиков редактора.

    Если attached_file_ids заданы — отбрасываем editor_doc_*; иначе берём все files по case_id.
    """
    if attached_file_ids:
        ids = [
            str(x).strip()
            for x in attached_file_ids
            if x and str(x).strip() and not is_editor_rag_file_id(str(x))
        ]
        return ids or None

    if not db or not case_id:
        return None

    from app.models.case import File as CaseFile
    from app.utils.database import ensure_db_session_live

    try:
        ensure_db_session_live(db)
        rows = (
            db.query(CaseFile.id)
            .filter(CaseFile.case_id == case_id)
            .order_by(CaseFile.created_at.asc())
            .all()
        )
        ids = [str(r[0]) for r in rows if r and r[0]]
        return ids or None
    except Exception as e:
        logger.warning(
            "[draft_field_retrieval] resolve_bulk_case_file_ids case=%s: %s", case_id, e
        )
        return None


def filter_case_material_docs(docs: List[Any]) -> List[Any]:
    """Убирает чанки из текстового редактора (editor_doc_*), если они попали в recall."""
    out: List[Any] = []
    for doc in docs or []:
        meta = getattr(doc, "metadata", None) or {}
        fid = str(meta.get("file_id") or "")
        if is_editor_rag_file_id(fid):
            continue
        out.append(doc)
    return out


def _bulk_context_max_chars() -> int:
    return max(4000, int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 7000) or 7000))


def _bulk_snippet_max_chars() -> int:
    # ~900 символов на чанк при k=8 укладывается в лимит 6–8k.
    return 900


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

    top_k = k if k is not None else int(getattr(config, "DRAFT_BULK_RAG_K", 8) or 8)
    top_k = max(4, min(top_k, 12))
    max_chars = _bulk_context_max_chars()
    snippet_max = _bulk_snippet_max_chars()
    strategy = str(getattr(config, "DRAFT_BULK_RAG_STRATEGY", "hybrid") or "hybrid").strip() or "hybrid"

    if db is not None:
        try:
            from app.utils.database import ensure_db_session_live

            ensure_db_session_live(db)
        except Exception as e:
            logger.warning("[draft_field_retrieval] bulk ensure_db_session_live: %s", e)

    file_ids = resolve_bulk_case_file_ids(db, case_id, attached_file_ids)
    meta["scoped_file_ids"] = file_ids
    meta["exclude_editor_docs"] = True
    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=q,
        k=top_k,
        db=db,
        file_ids=file_ids,
        retrieval_strategy=strategy,
        use_hybrid=True,
    )
    docs = filter_case_material_docs(docs or [])
    meta["strategy"] = strategy
    snippets = [
        d.page_content[:snippet_max]
        for d in docs
        if getattr(d, "page_content", "").strip()
    ]
    ctx = "\n\n".join(snippets)[:max_chars]
    meta["docs"] = len(docs)
    meta["k"] = top_k
    meta["max_chars"] = max_chars
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

    file_ids = resolve_bulk_case_file_ids(db, case_id, attached_file_ids)
    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=query,
        k=k,
        db=db,
        file_ids=file_ids,
        retrieval_strategy="hybrid",
        use_hybrid=True,
    )
    docs = filter_case_material_docs(docs or [])
    snippet_max = min(_bulk_snippet_max_chars(), 800)
    max_chars = min(_bulk_context_max_chars(), 4000)
    snippets = [d.page_content[:snippet_max] for d in docs if getattr(d, "page_content", "").strip()]
    ctx = "\n\n".join(snippets)[:max_chars]
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
