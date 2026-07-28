"""
Case assistant context pipeline helpers: recall pool + rerank + prompt assembly.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.config import config
from app.models.case import File as CaseFile
from app.services.chat.citation_file_identity import CaseCitationFileIndex
from app.services.chat.citation_payload import (
    build_retrieval_citations,
    fetch_originals_for_citation_docs,
)
from app.services.chat.rag_passage_utils import passage_for_rerank
from app.services.chat.retrieval_router import RetrievalTask, build_metadata_filter, resolve_scoped_file_ids
from app.services.chat.scoped_file_expand import (
    expand_docs_within_scoped_files,
    scoped_file_expand_enabled,
    scoped_file_expand_max_files,
)
from app.services.chat.tabular_citation_policy import filter_docs_for_tabular_citations
from app.services.observability.case_assistant_langfuse_tracing import (
    case_assistant_span,
    summarize_case_documents,
    summarize_metadata_filter,
)

logger = logging.getLogger(__name__)


def _doc_recall_score(doc: Document) -> Optional[float]:
    md = doc.metadata or {}
    # within_file_lexical_score first: BM25-in-file is authoritative under narrow scope.
    for key in (
        "within_file_lexical_score",
        "combined_score",
        "similarity_score",
        "bm25_score",
        "score",
        "rerank_score",
    ):
        v = md.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _sort_docs_by_recall_score(docs: List[Document]) -> List[Document]:
    scored = [(d, _doc_recall_score(d)) for d in docs]
    if not any(s is not None for _, s in scored):
        return list(docs)
    return [
        d
        for d, _ in sorted(
            scored,
            key=lambda pair: pair[1] if pair[1] is not None else -1.0,
            reverse=True,
        )
    ]


def _rank_scores_for_pool(docs: List[Document]) -> List[float]:
    """Monotonic scores for rank-gap analysis (uses recall scores or rank proxy)."""
    raw = [_doc_recall_score(d) for d in docs]
    if any(s is not None for s in raw):
        return [float(s) if s is not None else 0.0 for s in raw]
    n = len(docs)
    if n <= 0:
        return []
    return [1.0 - (i / max(n, 1)) for i in range(n)]


def _recall_rank_gap_sufficient(docs: List[Document], final_k: int) -> bool:
    """
    Skip rerank when top of pool separates clearly from the tail (knee / rank-gap).

    Uses rank-gap between top-1 and position final_k (and optional knee in top pool).
    """
    if not bool(getattr(config, "CASE_ASSISTANT_SKIP_RERANK_WHEN_SUFFICIENT", True)):
        return False
    target_k = max(1, int(final_k or 1))
    if len(docs) <= target_k:
        return True

    sorted_docs = _sort_docs_by_recall_score(docs)
    scores = _rank_scores_for_pool(sorted_docs)
    if len(scores) < target_k + 1:
        return False

    min_gap = float(
        getattr(config, "CASE_ASSISTANT_SKIP_RERANK_MIN_RANK_GAP", 0.12) or 0.12
    )
    top = scores[0]
    at_k = scores[min(target_k, len(scores) - 1)]
    head_gap = top - at_k
    if head_gap >= min_gap:
        return True

    # Knee: largest drop in consecutive scores within top pool.
    window = scores[: min(len(scores), target_k + 4)]
    if len(window) < 3:
        return False
    gaps = [window[i] - window[i + 1] for i in range(len(window) - 1)]
    knee_idx = max(range(len(gaps)), key=lambda i: gaps[i])
    knee_gap = gaps[knee_idx]
    knee_pos = knee_idx + 1
    return knee_gap >= min_gap and knee_pos <= target_k


def _rerank_pool_cap(budget_profile: Optional[Dict[str, Any]], pool_size: int) -> int:
    if isinstance(budget_profile, dict):
        cap = budget_profile.get("rerank_pool_cap")
        if isinstance(cap, int) and cap > 0:
            return min(pool_size, cap)
    default_cap = int(getattr(config, "CASE_ASSISTANT_RERANK_POOL_CAP", 24) or 24)
    return min(pool_size, max(8, default_cap))


def _parent_context_for_budget(budget_profile: Optional[Dict[str, Any]]) -> bool:
    if isinstance(budget_profile, dict) and "parent_context_enabled" in budget_profile:
        return bool(budget_profile.get("parent_context_enabled"))
    return bool(getattr(config, "CASE_ASSISTANT_PARENT_CONTEXT_ENABLED", True))


def pipeline_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED", True))


def recall_k_for_budget(budget_profile: Optional[Dict[str, Any]]) -> int:
    if isinstance(budget_profile, dict):
        rk = budget_profile.get("recall_k")
        if isinstance(rk, int) and rk > 0:
            base = rk
        else:
            base = int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100)
    else:
        base = int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100)

    if isinstance(budget_profile, dict) and budget_profile.get("skip_micro_recall_cap"):
        return max(1, base)

    from app.services.chat.context_resolution import micro_only_recall_enabled, micro_recall_k

    if pipeline_enabled() and micro_only_recall_enabled():
        return min(base, micro_recall_k()) if base > 0 else micro_recall_k()
    return base


def final_k_for_budget(budget_profile: Optional[Dict[str, Any]]) -> int:
    if isinstance(budget_profile, dict):
        fk = budget_profile.get("final_k")
        if isinstance(fk, int) and fk > 0:
            return fk
        ms = budget_profile.get("max_sources")
        if isinstance(ms, int) and ms > 0:
            return ms
    return int(getattr(config, "CASE_ASSISTANT_FINAL_K", 15) or 15)


def max_assemble_context_chars(budget_profile: Optional[Dict[str, Any]]) -> int:
    """Cap prompt context assembly by budget profile and global env ceiling."""
    ceiling = int(getattr(config, "CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING", 48_000) or 48_000)
    ceiling = max(1200, ceiling)
    budget_max_ctx = int((budget_profile or {}).get("max_context_chars") or 0)
    if budget_max_ctx > 0:
        return max(1200, min(ceiling, budget_max_ctx))
    return min(ceiling, 4000)


def run_hybrid_recall(
    *,
    rag_service,
    case_id: str,
    question: str,
    db: Optional[Session],
    retrieval_task: Optional[RetrievalTask],
    attached_file_ids: Optional[List[str]],
    budget_profile: Optional[Dict[str, Any]],
    query_embedding: Optional[List[float]] = None,
    exact_query: Optional[str] = None,
    section_root_ids: Optional[List[str]] = None,
) -> Tuple[List[Document], Dict[str, Any]]:
    """Stage 2: hybrid retrieval over scoped case chunks."""
    meta: Dict[str, Any] = {"strategy": "hybrid", "pipeline": True}
    search_query = (retrieval_task.search_query if retrieval_task else None) or question
    exact_q = (exact_query or "").strip() or None
    if exact_q:
        meta["exact_query"] = exact_q[:64]
    k = recall_k_for_budget(budget_profile)
    if k <= 0:
        meta["recall_k"] = 0
        meta["recall_docs"] = 0
        meta["skipped"] = "tier_no_retrieval"
        return [], meta

    file_ids: Optional[List[str]] = None
    metadata_filter: Optional[Dict[str, Any]] = None

    doc_types: Optional[List[str]] = None
    if retrieval_task:
        file_ids = resolve_scoped_file_ids(retrieval_task)
        metadata_filter = build_metadata_filter(retrieval_task)
        meta["scope_mode"] = retrieval_task.scope_mode
        meta["router_confidence"] = retrieval_task.confidence
        if not file_ids and retrieval_task.doc_type:
            doc_types = [str(retrieval_task.doc_type).strip()]
    elif attached_file_ids:
        file_ids = [str(x) for x in attached_file_ids if str(x).strip()]
        meta["scope_mode"] = "attached"

    section_ids = [str(x).strip() for x in (section_root_ids or []) if str(x).strip()]
    if section_ids:
        from app.services.chat.retrieval_router import merge_metadata_filters

        section_filter: Dict[str, Any] = {
            "section_root_id": section_ids[0] if len(section_ids) == 1 else section_ids
        }
        metadata_filter = merge_metadata_filters(metadata_filter, section_filter)
        meta["section_root_filter"] = section_ids[:12]

    scope_meta = summarize_metadata_filter(metadata_filter, file_ids=file_ids)
    meta["metadata_filter"] = scope_meta

    with case_assistant_span(
        "hybrid_recall",
        input_payload={
            "question": (search_query or "")[:800],
            "exact_query": exact_q,
            "recall_k": k,
            "scope": scope_meta,
            "doc_types": doc_types,
        },
        metadata={
            "case_id": case_id,
            "scope_mode": meta.get("scope_mode"),
            "router_confidence": meta.get("router_confidence"),
        },
    ) as span_out:
        docs = rag_service.retrieve_context(
            case_id=case_id,
            query=search_query,
            k=k,
            retrieval_strategy="hybrid",
            db=db,
            use_hybrid=True,
            file_ids=file_ids,
            metadata_filter=metadata_filter,
            doc_types=doc_types,
            pipeline_micro_only=True,
            query_embedding=query_embedding,
            exact_query=exact_q,
        )
        docs = [d for d in (docs or []) if d is not None and hasattr(d, "page_content")]

        # Narrow scope → always run within-file BM25 channel (production path).
        scoped_n = len(file_ids or [])
        want_expand = bool(
            file_ids
            and scoped_file_expand_enabled()
            and scoped_n <= scoped_file_expand_max_files()
        )
        if want_expand:
            try:
                vector_store = getattr(
                    getattr(rag_service, "document_processor", None),
                    "vector_store",
                    None,
                )
                file_texts: Dict[str, str] = {}
                if db is not None and file_ids:
                    try:
                        rows = (
                            db.query(CaseFile)
                            .filter(
                                CaseFile.case_id == str(case_id),
                                CaseFile.id.in_([str(x) for x in file_ids]),
                            )
                            .all()
                        )
                        for row in rows:
                            body = (
                                (getattr(row, "original_text", None) or "")
                                or (getattr(row, "structured_text", None) or "")
                            )
                            if str(body).strip():
                                file_texts[str(row.id)] = str(body)
                    except Exception as text_exc:
                        logger.debug("within_file original_text load skipped: %s", text_exc)

                docs, expand_meta = expand_docs_within_scoped_files(
                    case_id=str(case_id),
                    file_ids=file_ids,
                    question=search_query or question,
                    hybrid_docs=docs,
                    vector_store=vector_store,
                    force=True,
                    file_texts=file_texts or None,
                )
                meta["within_file_expand"] = expand_meta
            except Exception as expand_exc:
                logger.debug("within_file_expand skipped: %s", expand_exc)

        span_out.update(summarize_case_documents(docs))

    meta["recall_k"] = k
    meta["recall_docs"] = len(docs)
    meta["scoped_files_count"] = len(file_ids or [])
    return docs, meta


def documents_from_state_serializable(items: Optional[List[Dict[str, Any]]]) -> List[Document]:
    out: List[Document] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        out.append(
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return out


def serialize_documents(docs: List[Document]) -> List[Dict[str, Any]]:
    return [
        {"page_content": d.page_content, "metadata": dict(d.metadata or {})}
        for d in docs
    ]


def rerank_case_documents(
    *,
    question: str,
    docs: List[Document],
    final_k: int,
    budget_profile: Optional[Dict[str, Any]] = None,
) -> List[Document]:
    """Stage 3: cross-encoder rerank to final_k."""
    if not docs:
        return []
    bp = budget_profile if isinstance(budget_profile, dict) else {}
    rerank_on = bp.get("rerank_enabled")
    if rerank_on is False:
        with case_assistant_span(
            "rerank",
            input_payload={"pool_size": len(docs), "final_k": final_k},
            metadata={"rerank_skipped": True, "reason": "tier_disabled"},
        ) as span_out:
            trimmed = docs[: max(1, final_k)]
            span_out.update(summarize_case_documents(trimmed))
            return trimmed
    if rerank_on is None and not bool(getattr(config, "CASE_ASSISTANT_RERANK_ENABLED", True)):
        with case_assistant_span(
            "rerank",
            input_payload={"pool_size": len(docs), "final_k": final_k},
            metadata={"rerank_skipped": True, "reason": "config_disabled"},
        ) as span_out:
            trimmed = docs[: max(1, final_k)]
            span_out.update(summarize_case_documents(trimmed))
            return trimmed

    target_k = max(1, final_k)
    if len(docs) <= target_k:
        with case_assistant_span(
            "rerank",
            input_payload={"pool_size": len(docs), "final_k": final_k},
            metadata={"rerank_skipped": True, "reason": "pool_le_final_k"},
        ) as span_out:
            out: List[Document] = []
            for idx, doc in enumerate(docs[:target_k]):
                md2 = dict(doc.metadata or {})
                md2["rerank_score"] = 1.0 - (idx / 100.0)
                doc.metadata = md2
                out.append(doc)
            span_out.update(summarize_case_documents(out))
            span_out["pool_in"] = len(docs)
            span_out["pool_out"] = len(out)
            return out

    capped_docs = _sort_docs_by_recall_score(docs)
    capped_docs = capped_docs[: _rerank_pool_cap(budget_profile, len(capped_docs))]

    if _recall_rank_gap_sufficient(capped_docs, target_k):
        with case_assistant_span(
            "rerank",
            input_payload={"pool_size": len(capped_docs), "final_k": final_k},
            metadata={"rerank_skipped": True, "reason": "rank_gap_sufficient"},
        ) as span_out:
            trimmed = capped_docs[:target_k]
            for idx, doc in enumerate(trimmed):
                md2 = dict(doc.metadata or {})
                if "rerank_score" not in md2:
                    score = _doc_recall_score(doc)
                    md2["rerank_score"] = float(score) if score is not None else 1.0 - (idx / 100.0)
                doc.metadata = md2
            span_out.update(summarize_case_documents(trimmed))
            span_out["pool_in"] = len(docs)
            span_out["pool_out"] = len(trimmed)
            return trimmed

    max_chars = int(getattr(config, "CASE_ASSISTANT_RERANK_MAX_CHARS", 2400) or 2400)
    rerank_tier = "light"
    if isinstance(budget_profile, dict):
        rerank_tier = str(budget_profile.get("rerank_tier") or "light")
        if rerank_tier == "light":
            max_chars = int(
                getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS", 900) or 900
            )
    try:
        from app.services.reranker_service import get_reranker_for_tier

        svc = get_reranker_for_tier(rerank_tier)
    except Exception as exc:
        logger.warning("Case reranker unavailable: %s", exc)
        with case_assistant_span(
            "rerank",
            input_payload={"pool_size": len(docs), "final_k": final_k},
            metadata={"rerank_skipped": True, "reason": "reranker_unavailable"},
        ) as span_out:
            trimmed = docs[: max(1, final_k)]
            span_out["error"] = str(exc)[:300]
            span_out.update(summarize_case_documents(trimmed))
            return trimmed

    with case_assistant_span(
        "rerank",
        input_payload={
            "question": (question or "")[:800],
            "pool_size": len(docs),
            "final_k": final_k,
        },
        metadata={"rerank_skipped": False, "rerank_tier": rerank_tier},
    ) as span_out:
        proxies: List[Document] = []
        for i, d in enumerate(capped_docs):
            md = dict(d.metadata or {})
            md["_rerank_ix"] = i
            proxies.append(
                Document(
                    page_content=passage_for_rerank(d, max_chars),
                    metadata=md,
                )
            )

        try:
            ranked = svc.rerank(
                question.strip(), proxies, top_k=max(1, min(final_k, len(proxies)))
            )
        except Exception as exc:
            logger.warning("Case rerank failed: %s", exc, exc_info=True)
            span_out["error"] = str(exc)[:300]
            span_out["fallback"] = "truncate_pool"
            return capped_docs[: max(1, final_k)]

        out: List[Document] = []
        for pdoc, score in ranked:
            ix = (pdoc.metadata or {}).get("_rerank_ix")
            if not isinstance(ix, int) or ix < 0 or ix >= len(capped_docs):
                continue
            orig = capped_docs[ix]
            md2 = dict(orig.metadata or {})
            md2["rerank_score"] = float(score)
            orig.metadata = md2
            out.append(orig)
        result = out if out else capped_docs[: max(1, final_k)]
        span_out.update(summarize_case_documents(result))
        span_out["pool_in"] = len(docs)
        span_out["pool_out"] = len(result)
        return result


def rerank_and_resolve_documents(
    *,
    question: str,
    docs: List[Document],
    final_k: int,
    case_id: str,
    rag_service,
    budget_profile: Optional[Dict[str, Any]] = None,
    exact_query: Optional[str] = None,
    pin_clause_anchors: bool = True,
    lexical_terms: Optional[Sequence[str]] = None,
) -> Tuple[List[Document], Dict[str, Any]]:
    """Rerank micro pool, then expand to macro parents for LLM context.

    Exact + lexical channels bypass rerank: verified literal hits lead the model
    context and are merged additively with the reranked pool.
    """
    from app.services.chat.context_resolution import (
        filter_rerank_pool_to_micro,
        parent_context_enabled,
        resolve_parent_context,
    )
    from app.services.clause_anchor import (
        exclude_docs_by_identity,
        select_pinned_clause_anchor_docs,
    )
    from app.services.observability.case_assistant_langfuse_tracing import case_assistant_span
    from app.services.retrieval_channels import (
        merge_evidence_pins,
        select_pinned_lexical_docs,
    )

    meta: Dict[str, Any] = {}
    exact_q = (exact_query or "").strip() or None
    terms = tuple(
        str(t).strip() for t in (lexical_terms or ()) if str(t).strip()
    )
    exact_pins: List[Document] = []
    lexical_pins: List[Document] = []
    if pin_clause_anchors:
        exact_pins = select_pinned_clause_anchor_docs(docs, exact_query=exact_q)
        if exact_pins:
            meta["clause_anchor_pins"] = len(exact_pins)
            meta["clause_anchor_exact_query"] = (exact_q or "")[:64]
            meta["exact_channel"] = True
    if terms:
        lexical_pins = select_pinned_lexical_docs(docs, terms=terms)
        if lexical_pins:
            meta["lexical_pins"] = len(lexical_pins)
            meta["lexical_channel"] = True

    use_parent = _parent_context_for_budget(budget_profile)
    pool = filter_rerank_pool_to_micro(docs) if use_parent and parent_context_enabled() else list(docs)
    # Literal hits do not compete in rerank — they already have a reserved lane.
    reserved = exact_pins + lexical_pins
    if reserved:
        pool = exclude_docs_by_identity(pool, reserved)
    meta["rerank_pool_in"] = len(docs)
    meta["rerank_pool_micro"] = len(pool)

    ranked = rerank_case_documents(
        question=question,
        docs=pool,
        final_k=final_k,
        budget_profile=budget_profile,
    )
    meta["rerank_out"] = len(ranked)

    resolved = ranked
    if use_parent and parent_context_enabled() and rag_service:
        vector_store = getattr(
            getattr(rag_service, "document_processor", None),
            "vector_store",
            None,
        )
        if vector_store is None:
            meta["context_resolution"] = {"parent_context": False, "reason": "no_vector_store"}
        else:
            with case_assistant_span(
                "context_resolution",
                input_payload={"ranked_micro": len(ranked), "final_k": final_k},
                metadata={"case_id": case_id},
            ) as span_out:
                resolved, resolve_meta = resolve_parent_context(
                    ranked,
                    case_id=str(case_id),
                    vector_store=vector_store,
                )
                span_out.update(resolve_meta)
                meta.update(resolve_meta)

    if exact_pins or lexical_pins:
        resolved = merge_evidence_pins(
            exact_pins=exact_pins,
            lexical_pins=lexical_pins,
            ranked=resolved,
            final_k=final_k,
        )
    return resolved, meta


def assemble_rag_output(
    *,
    rag_service,
    docs: List[Document],
    case_id: str,
    db: Optional[Session],
    budget_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Format context + citations after rerank."""
    max_context_chars = max_assemble_context_chars(budget_profile)

    if db and case_id and docs:
        try:
            from app.services.chat.chunk_file_passport import (
                load_case_file_summary_map,
                stamp_file_summaries_on_documents,
            )

            stamp_file_summaries_on_documents(
                docs,
                summaries_by_file_id=load_case_file_summary_map(db, str(case_id)),
            )
        except Exception:
            pass

    with case_assistant_span(
        "assemble_context",
        input_payload={"docs_in": len(docs), "max_context_chars": max_context_chars},
        metadata={"case_id": case_id},
    ) as span_out:
        # Excel/registers: never number whole-sheet dumps as citation sources.
        docs_for_prompt = filter_docs_for_tabular_citations(docs)
        context, included_docs = rag_service.format_sources_for_prompt_with_docs(
            docs_for_prompt, max_context_chars=max_context_chars
        )

        originals = {}
        file_index: Optional[CaseCitationFileIndex] = None
        if db and case_id:
            try:
                file_index = CaseCitationFileIndex.from_db(db, str(case_id))
            except Exception:
                file_index = None
            with case_assistant_span(
                "fetch_originals",
                input_payload={"docs_in": len(included_docs or [])},
                metadata={"case_id": case_id},
            ) as orig_out:
                originals = fetch_originals_for_citation_docs(
                    db, str(case_id), included_docs or []
                )
                orig_out["originals_count"] = len(originals or {})

        citations = build_retrieval_citations(
            included_docs or [],
            original_text_by_file_id=originals or None,
            case_id=str(case_id) if case_id else None,
            db=db,
            case_file_index=file_index,
        )
        span_out["context_chars"] = len(context or "")
        span_out["citations_count"] = len(citations or [])
        span_out.update(summarize_case_documents(included_docs or []))

    return {
        "rag_context": context,
        "rag_documents": serialize_documents(included_docs or [])[:32],
        "citations": citations,
    }


def complete_retrieval_after_recall(
    *,
    question: str,
    docs: List[Document],
    case_id: str,
    rag_service,
    db: Optional[Session],
    budget_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Unified post-recall stage: rerank → parent context → assemble (single executor).
    """
    from app.config import config as _cfg

    budget = budget_profile if isinstance(budget_profile, dict) else {}
    if not docs:
        return {"context_pipeline_meta": {"retrieval_complete": True, "recall_docs": 0}}

    rerank_enabled = bool(budget.get("rerank_enabled", True))
    final_k = final_k_for_budget(budget)
    meta: Dict[str, Any] = {"recall_docs": len(docs), "unified_retrieval": True}

    if rerank_enabled and str(budget.get("rerank_tier") or "light") != "none":
        ranked, resolve_meta = rerank_and_resolve_documents(
            question=question,
            docs=docs,
            final_k=final_k,
            case_id=str(case_id),
            rag_service=rag_service,
            budget_profile=budget,
            exact_query=(str(budget.get("exact_query") or "").strip() or None),
            pin_clause_anchors=True,
        )
        meta.update(resolve_meta or {})
        meta["rerank_docs"] = len(ranked)
    else:
        ranked = docs[: max(1, final_k)]
        meta["rerank_skipped"] = True
        meta["rerank_docs"] = len(ranked)

    assembled = assemble_rag_output(
        rag_service=rag_service,
        docs=ranked,
        case_id=str(case_id),
        db=db,
        budget_profile=budget,
    )
    rerank_tier = str(budget.get("rerank_tier") or "light")
    rerank_model = (
        getattr(_cfg, "CASE_ASSISTANT_RERANK_LIGHT_MODEL", "")
        if rerank_tier == "light"
        else getattr(_cfg, "RERANKER_MODEL_NAME", "")
    ) or "BAAI/bge-reranker-v2-m3"
    meta.update(
        {
            "pipeline": True,
            "retrieval_complete": True,
            "final_k": final_k,
            "rerank_tier": rerank_tier,
            "rerank_model": rerank_model,
        }
    )
    assembled["context_pipeline_meta"] = meta
    return assembled


def _parse_retrieval_task(raw: Optional[Dict[str, Any]]) -> Optional[RetrievalTask]:
    if not isinstance(raw, dict):
        return None
    if not str(raw.get("search_query") or "").strip():
        return None
    try:
        return RetrievalTask.model_validate(raw)
    except Exception:
        return None


def run_case_context_pipeline(
    *,
    rag_service,
    case_id: str,
    question: str,
    db: Optional[Session] = None,
    attached_file_ids: Optional[List[str]] = None,
    document_id: Optional[str] = None,
    corpus_size: int = 0,
    budget_profile: Optional[Dict[str, Any]] = None,
    retrieval_task: Optional[Dict[str, Any]] = None,
    editor_case_files_only: bool = False,
) -> Dict[str, Any]:
    """
    Полный контекст по делу: secretary router → hybrid recall → rerank → citations.
    Используется внутренним ассистентом (rerank_context) и чатом редактора.
    """
    from app.config import config as _cfg
    from app.services.chat.retrieval_router import create_case_retrieval_router

    question = (question or "").strip()
    if not case_id or not question or not rag_service:
        return {}

    attached_ids = [str(x) for x in (attached_file_ids or []) if str(x).strip()]
    if editor_case_files_only and not attached_ids:
        logger.info(
            "[CaseContextPipeline] Editor: no attached case files — skipping case RAG"
        )
        return {}

    budget = budget_profile if isinstance(budget_profile, dict) else {}
    out: Dict[str, Any] = {}

    if not pipeline_enabled():
        k = final_k_for_budget(budget)
        file_ids = attached_ids or None
        docs = rag_service.retrieve_context(
            case_id=case_id,
            query=question,
            k=k,
            db=db,
            file_ids=file_ids,
            use_hybrid=True,
            retrieval_strategy="hybrid",
        )
        docs = [d for d in (docs or []) if d is not None and hasattr(d, "page_content")]
        if not docs:
            return {}
        assembled = assemble_rag_output(
            rag_service=rag_service,
            docs=docs[:k],
            case_id=str(case_id),
            db=db,
            budget_profile=budget,
        )
        assembled["context_pipeline_meta"] = {"pipeline": False, "recall_docs": len(docs), "final_k": k}
        return assembled

    task_obj = _parse_retrieval_task(retrieval_task)
    if task_obj is None and db:
        router = create_case_retrieval_router()
        task_obj = router.route(
            question=question,
            case_id=str(case_id),
            db=db,
            attached_file_ids=attached_ids or None,
            document_id=None if editor_case_files_only else document_id,
            corpus_size=int(corpus_size or 0),
            editor_attach_only=editor_case_files_only,
        )
        out["retrieval_task"] = task_obj.model_dump()
        out["scoped_file_ids"] = list(task_obj.file_ids) if task_obj.file_ids else None
        out["scoped_doc_type"] = task_obj.doc_type

    docs, recall_meta = run_hybrid_recall(
        rag_service=rag_service,
        case_id=str(case_id),
        question=question,
        db=db,
        retrieval_task=task_obj,
        attached_file_ids=attached_ids or None,
        budget_profile=budget,
    )
    if editor_case_files_only and not attached_ids:
        return out
    if not docs:
        logger.info("[CaseContextPipeline] No recall docs case_id=%s", case_id)
        return out

    final_k = final_k_for_budget(budget)
    ranked, resolve_meta = rerank_and_resolve_documents(
        question=question,
        docs=docs,
        final_k=final_k,
        case_id=str(case_id),
        rag_service=rag_service,
        budget_profile=budget,
    )
    assembled = assemble_rag_output(
        rag_service=rag_service,
        docs=ranked,
        case_id=str(case_id),
        db=db,
        budget_profile=budget,
    )
    rerank_model = getattr(_cfg, "RERANKER_MODEL_NAME", "") or "BAAI/bge-reranker-v2-m3"
    assembled["context_pipeline_meta"] = {
        "pipeline": True,
        "recall_docs": len(docs),
        "rerank_docs": len(ranked),
        "rerank_model": rerank_model,
        "final_k": final_k,
        "scope_mode": recall_meta.get("scope_mode"),
        "scoped_files_count": recall_meta.get("scoped_files_count"),
        "router_confidence": recall_meta.get("router_confidence"),
        **resolve_meta,
    }
    out.update(assembled)
    return out
