"""Tabular context compiler: route → retrieve → gate → escalate → assemble."""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chat.case_context_pipeline import (
    assemble_rag_output,
    documents_from_state_serializable,
    final_k_for_budget,
    pipeline_enabled,
    rerank_and_resolve_documents,
    run_hybrid_recall,
)
from app.services.chat.retrieval_escalation import (
    build_escalated_retrieval_task,
    plan_retrieval_escalation,
)
from app.services.chat.retrieval_router import create_case_retrieval_router
from app.services.tabular_context_status import classify_tabular_context_outcome, merge_context_meta
from app.services.tabular_coverage_gate import evaluate_tabular_coverage
from app.services.tabular_cross_ref_enrich import enrich_docs_with_cross_references
from app.services.tabular_document_context import TabularFileContextPackage
from app.services.tabular_section_router import route_column_to_sections

logger = logging.getLogger(__name__)


def tabular_context_compiler_enabled() -> bool:
    return bool(getattr(config, "TABULAR_CONTEXT_COMPILER_ENABLED", True))


def tabular_retrieval_escalation_enabled() -> bool:
    return bool(getattr(config, "TABULAR_RETRIEVAL_ESCALATION_ENABLED", False))


def tabular_max_retrieval_rounds() -> int:
    return max(1, int(getattr(config, "TABULAR_MAX_RETRIEVAL_ROUNDS", 2) or 2))


def build_navigation_context(
    *,
    route_plan: Any,
    file_context: Optional[TabularFileContextPackage],
    lexical_terms: Tuple[str, ...],
) -> str:
    lines: List[str] = []
    if file_context and file_context.passport_blurb:
        lines.append("[Кратко о документе]")
        lines.append(file_context.passport_blurb[:800])
    if route_plan and getattr(route_plan, "section_root_ids", None):
        lines.append("[Маршрут по разделам]")
        lines.append(
            f"method={getattr(route_plan, 'route_method', '')} "
            f"confidence={getattr(route_plan, 'confidence', 0):.2f}"
        )
        for sid in route_plan.section_root_ids[:6]:
            title = sid
            if file_context:
                for entry in file_context.outline:
                    if entry.section_root_id == sid:
                        title = entry.section_title or entry.section_number or sid
                        break
            lines.append(f"- {title}")
    if lexical_terms:
        lines.append("[Ключевые термины поиска]")
        lines.append(", ".join(lexical_terms[:10]))
    return "\n".join(lines).strip()


def _filter_docs_by_section(
    docs: List[Document],
    section_root_ids: Tuple[str, ...]
) -> List[Document]:
    if not section_root_ids:
        return docs
    allowed = set(section_root_ids)
    filtered = [
        d
        for d in docs
        if str((d.metadata or {}).get("section_root_id") or "").strip() in allowed
        or not str((d.metadata or {}).get("section_root_id") or "").strip()
    ]
    return filtered if filtered else docs


def _dedupe_recall_docs(docs: List[Document]) -> List[Document]:
    from app.services.clause_anchor import clause_anchor_doc_identity

    out: List[Document] = []
    seen: set[str] = set()
    for doc in docs or []:
        if doc is None or not getattr(doc, "page_content", None):
            continue
        key = clause_anchor_doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def _resolve_search_queries(params: Any, primary: str) -> List[str]:
    raw = list(getattr(params, "search_queries", None) or ())
    queries: List[str] = []
    seen: set[str] = set()
    for item in [primary, *raw]:
        q = str(item or "").strip()
        if not q:
            continue
        key = q.lower().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        queries.append(q)
        if len(queries) >= 4:
            break
    return queries or ([primary] if primary else [])


def _hybrid_recall_multi_query(
    *,
    rag_service,
    params: Any,
    search_query: str,
    db,
    retrieval_task,
    attached_file_ids: List[str],
    budget: Dict[str, Any],
    query_embedding: Optional[List[float]],
    exact_query: Optional[str],
    section_root_ids: Optional[List[str]],
    doc_belongs_to_file,
) -> Tuple[List[Document], Dict[str, Any]]:
    """Hybrid recall for primary + alternate document-language queries, then merge."""
    queries = _resolve_search_queries(params, search_query)
    merged: List[Document] = []
    meta: Dict[str, Any] = {
        "search_queries": queries[:4],
        "multi_query_count": len(queries),
    }
    per_query_counts: List[int] = []

    for idx, query in enumerate(queries):
        round_budget: Dict[str, Any] = budget
        emb = query_embedding if idx == 0 and query == search_query else None
        if idx > 0:
            round_budget = copy.deepcopy(budget)
            base_k = int(budget.get("recall_k") or 30)
            round_budget["recall_k"] = max(8, base_k // 2)

        docs, recall_meta = run_hybrid_recall(
            rag_service=rag_service,
            case_id=params.case_id,
            question=query,
            db=db,
            retrieval_task=retrieval_task,
            attached_file_ids=attached_file_ids,
            budget_profile=round_budget,
            query_embedding=emb,
            exact_query=exact_query if idx == 0 else None,
            section_root_ids=section_root_ids,
        )
        if idx == 0:
            meta.update(recall_meta or {})
        scoped = [
            d
            for d in (docs or [])
            if d is not None
            and getattr(d, "page_content", None)
            and doc_belongs_to_file(d, params.file_id, params.filename)
        ]
        per_query_counts.append(len(scoped))
        merged.extend(scoped)

    meta["multi_query_recall_counts"] = per_query_counts
    return _dedupe_recall_docs(merged), meta


def compile_tabular_cell_context(
    rag_service,
    *,
    params: Any,
    db,
    budget: Dict[str, Any],
    doc_belongs_to_file,
) -> Tuple[str, List[Document], List[Document], Dict[str, Any]]:
    """
    Full context compile for one tabular cell.

    ``params`` is CellRetrievalParams from tabular_cell_pipeline.
    """
    from app.services.tabular_cell_pipeline import augment_context_for_column

    search_query = (params.search_query or params.query).strip()
    if not search_query:
        return "", [], [], {"status": "empty_query"}

    exact_query = (params.exact_query or "").strip() or None
    lexical_terms = tuple(
        dict.fromkeys(
            [
                *(str(t).strip() for t in (params.lexical_terms or ()) if str(t).strip()),
                *(str(t).strip() for t in (params.exact_literals or ()) if str(t).strip()),
            ]
        )
    )
    rerank_bits = [exact_query or "", " ".join(lexical_terms), search_query]
    rerank_question = " ".join(b for b in rerank_bits if b).strip() or search_query

    file_context: Optional[TabularFileContextPackage] = getattr(params, "file_context", None)
    route_plan = route_column_to_sections(
        file_context=file_context,
        semantic_query=search_query,
        lexical_terms=lexical_terms,
        exact_query=exact_query or "",
        column_type=params.column_type,
        column_label=params.column_label or "",
    )

    attached_file_ids = [params.file_id]
    final_k = final_k_for_budget(budget)
    meta: Dict[str, Any] = {
        "pipeline": True,
        "compiler": True,
        "file_id": params.file_id,
        "corpus_size": 1,
        "source_query": (params.query or "")[:500],
        "search_query": search_query[:500],
        "exact_query": (exact_query or "")[:64],
        "lexical_terms": list(lexical_terms)[:12],
        "rewrite_method": params.rewrite_method or "",
        "rewrite_rationale": (params.rewrite_rationale or "")[:200],
        "route_method": route_plan.route_method,
        "route_confidence": route_plan.confidence,
        "route_section_roots": list(route_plan.section_root_ids),
        "search_queries": list(getattr(params, "search_queries", None) or ())[:4],
    }
    navigation_context = build_navigation_context(
        route_plan=route_plan,
        file_context=file_context,
        lexical_terms=lexical_terms,
    )

    if not exact_query and not lexical_terms:
        try:
            from app.services.front_matter_facts import resolve_front_matter_evidence

            fm_question = (params.query or search_query).strip()
            fm = resolve_front_matter_evidence(
                db,
                file_id=params.file_id,
                question=fm_question,
                column_label=params.column_label or "",
                filename=params.filename or "",
                original_text=params.original_text or "",
                allow_llm=True,
            )
            meta["front_matter"] = fm.meta
            if fm.used and fm.context_text.strip() and fm.documents:
                meta["status"] = "front_matter_hit"
                meta["docs"] = len(fm.documents)
                meta = merge_context_meta(
                    meta,
                    outcome="front_matter_hit",
                    navigation_context=navigation_context,
                )
                return fm.context_text, list(fm.documents), list(fm.documents), meta
        except Exception as fm_exc:
            logger.warning("Front-matter failed file=%s: %s", params.file_id, fm_exc)
            meta["front_matter_error"] = str(fm_exc)[:200]

    query_embedding = list(params.query_embedding) if params.query_embedding else None
    retrieval_task = None
    if pipeline_enabled() and query_embedding is None:
        try:
            router = create_case_retrieval_router()
            retrieval_task = router.route(
                question=search_query,
                case_id=params.case_id,
                db=db,
                attached_file_ids=attached_file_ids,
                corpus_size=1,
            )
            meta["scope_mode"] = retrieval_task.scope_mode
            meta["router_confidence"] = retrieval_task.confidence
        except Exception as exc:
            logger.warning("Tabular router failed file=%s: %s", params.file_id, exc)
    elif query_embedding is not None:
        meta["scope_mode"] = "attached"
        meta["query_embedding_reused"] = True

    vector_store = getattr(
        getattr(rag_service, "document_processor", None),
        "vector_store",
        None,
    )

    max_rounds = tabular_max_retrieval_rounds() if tabular_retrieval_escalation_enabled() else 1
    recall_docs: List[Document] = []
    recall_meta: Dict[str, Any] = {}
    escalation_used = False
    weak_coverage = False
    section_filter_ids = list(route_plan.section_root_ids)

    for round_idx in range(max_rounds):
        round_budget = copy.deepcopy(budget)
        if round_idx > 0:
            round_budget["recall_k"] = int(round_budget.get("recall_k") or 30) + 16

        recall_docs, recall_meta = _hybrid_recall_multi_query(
            rag_service=rag_service,
            params=params,
            search_query=search_query,
            db=db,
            retrieval_task=retrieval_task,
            attached_file_ids=attached_file_ids,
            budget=round_budget,
            query_embedding=query_embedding,
            exact_query=exact_query,
            section_root_ids=section_filter_ids if section_filter_ids else None,
            doc_belongs_to_file=doc_belongs_to_file,
        )
        meta.update(recall_meta or {})
        meta["retrieval_round"] = round_idx

        if section_filter_ids and not recall_docs:
            meta["router_fallback_full_file"] = True
            section_filter_ids = []
            recall_docs, recall_meta = _hybrid_recall_multi_query(
                rag_service=rag_service,
                params=params,
                search_query=search_query,
                db=db,
                retrieval_task=retrieval_task,
                attached_file_ids=attached_file_ids,
                budget=round_budget,
                query_embedding=query_embedding,
                exact_query=exact_query,
                section_root_ids=None,
                doc_belongs_to_file=doc_belongs_to_file,
            )
            meta.update(recall_meta or {})

        if lexical_terms:
            try:
                from app.services.retrieval_channels import (
                    merge_retrieval_channels,
                    recall_lexical_term_docs,
                )

                lexical_docs = recall_lexical_term_docs(
                    case_id=params.case_id,
                    file_ids=attached_file_ids,
                    terms=lexical_terms,
                    vector_store=vector_store,
                    k=max(8, final_k),
                )
                lexical_docs = [
                    d
                    for d in lexical_docs
                    if d is not None and doc_belongs_to_file(d, params.file_id, params.filename)
                ]
                meta["lexical_recall_docs"] = len(lexical_docs)
                if lexical_docs:
                    recall_docs = merge_retrieval_channels(
                        lexical_docs=lexical_docs,
                        hybrid_docs=recall_docs,
                    )
            except Exception as lex_exc:
                meta["lexical_recall_error"] = str(lex_exc)[:200]

        if route_plan.section_root_ids:
            recall_docs = _filter_docs_by_section(recall_docs, route_plan.section_root_ids)

        coverage = evaluate_tabular_coverage(
            question=params.query or search_query,
            docs=recall_docs,
            lexical_terms=lexical_terms,
            exact_literals=tuple(params.exact_literals or ()),
            column_type=params.column_type,
            recall_meta=recall_meta,
        )
        if coverage.verdict == "sufficient" or round_idx >= max_rounds - 1:
            if coverage.verdict == "weak":
                weak_coverage = True
                meta["coverage_reason"] = coverage.reason
            break

        task_dict = {
            "scope_mode": meta.get("scope_mode") or "attached",
            "file_ids": attached_file_ids,
            "search_query": search_query,
            "confidence": float(meta.get("router_confidence") or 0.9),
            "rationale": "tabular_cell",
        }
        plan = plan_retrieval_escalation(
            question=rerank_question,
            retrieval_task=task_dict,
            docs=recall_docs,
            retrieval_round=round_idx,
            max_rounds=max_rounds,
        )
        if plan.action == "accept":
            weak_coverage = True
            break
        escalation_used = True
        build_escalated_retrieval_task(
            plan=plan,
            question=search_query,
            prior_task=task_dict,
        )
        section_filter_ids = []

    if not recall_docs:
        meta["status"] = "no_recall_docs"
        meta = merge_context_meta(
            meta,
            outcome="no_recall_docs",
            escalation_used=escalation_used,
            navigation_context=navigation_context,
        )
        return "", [], [], meta

    if params.preferred_zones:
        try:
            from app.services.document_zones import prefer_zone_docs_for_prompt

            recall_docs = prefer_zone_docs_for_prompt(
                recall_docs, params.preferred_zones
            )
        except Exception:
            pass

    ranked_docs, resolve_meta = rerank_and_resolve_documents(
        question=rerank_question,
        docs=recall_docs,
        final_k=final_k,
        case_id=params.case_id,
        rag_service=rag_service,
        budget_profile=budget,
        exact_query=exact_query,
        pin_clause_anchors=True,
        lexical_terms=lexical_terms,
    )
    meta.update(resolve_meta or {})

    ranked_docs, xref_meta = enrich_docs_with_cross_references(
        ranked_docs,
        file_context=file_context,
        vector_store=vector_store,
        case_id=params.case_id,
        file_id=params.file_id,
    )
    meta["cross_ref"] = xref_meta

    try:
        from app.services.retrieval_channels import prefer_short_docs_for_prompt

        ranked_docs = prefer_short_docs_for_prompt(ranked_docs)
    except Exception:
        pass

    try:
        from app.services.document_zones import prefer_zone_docs_for_prompt, zone_histogram

        if params.preferred_zones:
            ranked_docs = prefer_zone_docs_for_prompt(
                ranked_docs, params.preferred_zones
            )
            meta["preferred_zones"] = list(params.preferred_zones)
            meta["zone_histogram"] = zone_histogram(ranked_docs)
    except Exception as zone_exc:
        meta["zone_preference_error"] = str(zone_exc)[:200]

    assembled = assemble_rag_output(
        rag_service=rag_service,
        docs=ranked_docs,
        case_id=params.case_id,
        db=db,
        budget_profile=budget,
    )
    context_text = str(assembled.get("rag_context") or "")
    context_text = augment_context_for_column(
        context_text,
        column_type=params.column_type,
        original_text=params.original_text,
    )
    included_docs = documents_from_state_serializable(assembled.get("rag_documents"))
    meta["docs"] = len(included_docs)

    if not context_text.strip() or not included_docs:
        meta["status"] = "empty_context"
        outcome = classify_tabular_context_outcome(meta=meta, context_text=context_text, recall_docs_count=len(recall_docs))
        meta = merge_context_meta(
            meta,
            outcome=outcome,
            escalation_used=escalation_used,
            navigation_context=navigation_context,
        )
        return "", [], recall_docs, meta

    if weak_coverage:
        meta["status"] = "weak_coverage"

    outcome = classify_tabular_context_outcome(
        meta=meta,
        context_text=context_text,
        recall_docs_count=len(recall_docs),
        weak_coverage=weak_coverage,
        escalated=escalation_used,
    )
    meta = merge_context_meta(
        meta,
        outcome=outcome,
        escalation_used=escalation_used,
        navigation_context=navigation_context,
    )
    return context_text, included_docs, recall_docs, meta
