"""
Tabular cell extraction: internal case-assistant RAG per file + typed LLM output.

Each cell = run_case_context_pipeline scoped to one file_id, then structured extract
with column_type contract. No tabular-specific retrieval or forced_na gates.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from app.config import config
from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.chat.case_context_pipeline import (
    assemble_rag_output,
    documents_from_state_serializable,
    final_k_for_budget,
    pipeline_enabled,
    rerank_and_resolve_documents,
    rerank_case_documents,
    run_hybrid_recall,
)
from app.services.chat.retrieval_router import create_case_retrieval_router
from app.services.tabular_cell_verification import (
    CellVerificationOutcome,
    apply_evidence_first_policy,
)
from app.services.tabular_extraction_schemas import (
    cell_value_field_description,
    extraction_schema_for_column,
    typed_extraction_to_cell_model,
)
from app.services.tabular_extraction_policy import TABULAR_NA_VALUE, ensure_na_reasoning
from app.services.tabular_review_models import TabularCellExtractionModel
from app.services.document_date_resolver import select_document_date_zone

logger = logging.getLogger(__name__)

_SIMPLE_COLUMN_TYPES = frozenset({"date", "currency", "number", "yes_no", "tag"})

_RETRIEVAL_QUERY_HINTS: Dict[str, str] = {
    "date": (
        "дата подписания составления документа реквизиты шапка подпись "
        "«г.» число месяц год"
    ),
    "yes_no": "является ли документ признаки формулировки да нет",
    "currency": "сумма руб USD EUR стоимость цена неустойка штраф",
    "number": "число количество процент номер",
    "verbatim": "точная цитата дословный фрагмент",
}


@dataclass(frozen=True)
class CellRetrievalParams:
    """Thread-safe primitives for parallel cell retrieval (no ORM in worker threads)."""

    case_id: str
    file_id: str
    filename: str
    original_text: str
    query: str
    column_type: str
    search_query: str = ""
    query_embedding: Tuple[float, ...] = ()
    rewrite_method: str = ""
    rewrite_rationale: str = ""
    exact_query: str = ""
    column_label: str = ""
    lexical_terms: Tuple[str, ...] = ()
    exact_literals: Tuple[str, ...] = ()
    search_queries: Tuple[str, ...] = ()
    file_context: Optional[Any] = None  # TabularFileContextPackage when DCP enabled
    preferred_zones: Tuple[str, ...] = ()


@dataclass
class PreparedCellContext:
    """Sync retrieval output for one tabular cell (recall → rerank → format)."""

    file_chunks: List[Document]
    context_text: str
    included_docs: List[Document]
    error: Optional[str] = None
    navigation_context: str = ""
    retrieval_meta: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class TabularColumnExtractionOutcome:
    """Result of one file×column extraction task (safe to await via asyncio.as_completed)."""

    file_id: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and isinstance(self.result, dict) and not self.result.get("error")

    @classmethod
    def from_result(cls, file_id: str, result: Dict[str, Any]) -> "TabularColumnExtractionOutcome":
        if result.get("error"):
            return cls(file_id=file_id, error=str(result["error"]))
        return cls(file_id=file_id, result=result)

    @classmethod
    def from_exception(cls, file_id: str, exc: BaseException) -> "TabularColumnExtractionOutcome":
        return cls(file_id=file_id, error=str(exc))


def cell_result_to_api_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Shape saved extraction result for POST /columns/{id}/run response."""
    return {
        "file_id": result.get("file_id"),
        "column_id": result.get("column_id"),
        "cell_value": result.get("cell_value"),
        "normalized_value": result.get("normalized_value"),
        "verbatim_extract": result.get("verbatim_extract"),
        "reasoning": result.get("reasoning"),
        "confidence_score": result.get("confidence_score"),
        "source_page": result.get("source_page"),
        "source_section": result.get("source_section"),
        "source_references": result.get("source_references"),
        "status": result.get("status", "completed"),
        "candidates": result.get("candidates"),
    }


def cell_result_to_websocket_payload(cell_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Realtime tabular cell update (WebSocket cell_updated)."""
    payload = cell_result_to_api_payload(result)
    payload["cell_id"] = cell_id
    return payload


def tabular_recall_k() -> int:
    return max(5, int(getattr(config, "TABULAR_RECALL_K", 30) or 30))


def tabular_final_k(column_type: str) -> int:
    if column_type in _SIMPLE_COLUMN_TYPES:
        return max(2, int(getattr(config, "TABULAR_FINAL_K_SIMPLE", 8) or 8))
    return max(3, int(getattr(config, "TABULAR_FINAL_K", 8) or 8))


def tabular_context_max_chars() -> int:
    return max(2000, int(getattr(config, "TABULAR_CONTEXT_MAX_CHARS", 12000) or 12000))


def tabular_rerank_enabled() -> bool:
    """Cross-encoder rerank per cell (on by default; align with case-assistant RAG)."""
    return bool(getattr(config, "TABULAR_RERANK_ENABLED", True))


def truncate_recall_to_final_k(docs: List[Document], final_k: int) -> List[Document]:
    """Pick top final_k from hybrid recall using existing retrieval scores (no cross-encoder)."""
    if not docs:
        return []

    def _score(doc: Document) -> float:
        md = doc.metadata or {}
        for key in ("combined_score", "similarity_score", "bm25_score", "score"):
            raw = md.get(key)
            if raw is None:
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        return 0.0

    ranked = sorted(docs, key=_score, reverse=True)
    return ranked[: max(1, min(final_k, len(ranked)))]


def build_retrieval_query(column: TabularColumn) -> str:
    """Case-assistant question for one cell (column prompt + type-aware hints)."""
    prompt = (getattr(column, "prompt", None) or "").strip()
    label = (getattr(column, "column_label", None) or "").strip()
    base = prompt or label
    if not base:
        return ""
    column_type = str(getattr(column, "column_type", "") or "text")
    hint = _RETRIEVAL_QUERY_HINTS.get(column_type)
    if hint and hint.lower() not in base.lower():
        return f"{base}. {hint}"
    return base


def augment_context_for_column(
    context_text: str,
    *,
    column_type: str,
    original_text: str,
) -> str:
    """Ensure tabular extraction sees document header when dates/types live outside top chunks."""
    if not context_text.strip() or not original_text.strip():
        return context_text
    if column_type != "date":
        return context_text

    header, _ = select_document_date_zone(original_text)
    if not header.strip():
        return context_text
    if header[:120] in context_text:
        return context_text

    return (
        "[Начало документа — шапка и реквизиты]\n"
        f"{header}\n\n"
        "[Релевантные фрагменты по запросу]\n"
        f"{context_text}"
    )


def _tabular_cell_budget_profile(column_type: str) -> Dict[str, Any]:
    """Single-file tabular retrieval budget (not whole-case corpus scale).

    Small-to-big: recall/rerank on micro leaves, expand to macro parents for LLM.
    Geometry/highlight always uses the micro recall pool (see docs_for_cell_geometry).
    """
    final_k = tabular_final_k(column_type)
    recall_k = tabular_recall_k()
    max_chars = tabular_context_max_chars()
    return {
        "final_k": final_k,
        "recall_k": recall_k,
        "max_context_chars": max_chars,
        "max_sources": final_k,
        "rerank_enabled": tabular_rerank_enabled(),
        "skip_micro_recall_cap": True,
        "parent_context_enabled": True,
    }


def docs_for_cell_geometry(prepared: PreparedCellContext) -> List[Document]:
    """
    Leaf chunks for PDF highlight / bbox.

    Prefer the micro recall pool (file_chunks). Never use macro parents for pixels —
    better no highlight than a wrong parent box.
    """
    from app.services.tabular_source_geometry import filter_docs_for_geometry

    primary = filter_docs_for_geometry(prepared.file_chunks or [])
    if primary:
        return primary
    return filter_docs_for_geometry(prepared.included_docs or [])


def cell_retrieval_params_from_models(
    file: File,
    column: TabularColumn,
    *,
    column_run: Optional["TabularColumnRunContext"] = None,
    file_context: Optional[Any] = None,
) -> CellRetrievalParams:
    """Snapshot ORM fields on the request thread before asyncio.to_thread workers."""
    from app.services.tabular_column_run_context import TabularColumnRunContext
    from app.services.tabular_search_query_rewrite import (
        column_source_query,
        rewrite_tabular_search_query,
    )
    from app.services.tabular_zone_routing import resolve_preferred_zones_for_column

    run_ctx: Optional[TabularColumnRunContext] = column_run
    source_query = column_source_query(column)
    lexical_terms: Tuple[str, ...] = ()
    exact_literals: Tuple[str, ...] = ()
    search_queries: Tuple[str, ...] = ()
    preferred_zones = resolve_preferred_zones_for_column(column)
    if run_ctx:
        search_query = run_ctx.search_query
        query_embedding = run_ctx.query_embedding
        rewrite_method = run_ctx.rewrite_method
        rewrite_rationale = run_ctx.rewrite_rationale
        exact_query = (run_ctx.exact_query or "") or ""
        lexical_terms = tuple(run_ctx.lexical_terms or ())
        exact_literals = tuple(run_ctx.exact_literals or ())
        search_queries = tuple(run_ctx.search_queries or ()) or (search_query,)
        if run_ctx.source_query:
            source_query = run_ctx.source_query
    else:
        # No column prewarm: heuristic only (avoid per-cell LLM).
        rewritten = rewrite_tabular_search_query(column, allow_llm=False)
        search_query = rewritten.search_query or build_retrieval_query(column)
        query_embedding = ()
        rewrite_method = rewritten.method
        rewrite_rationale = rewritten.rationale
        source_query = rewritten.source_query or source_query
        exact_query = (rewritten.exact_query or "") or ""
        lexical_terms = tuple(rewritten.lexical_terms or ())
        exact_literals = tuple(rewritten.exact_literals or ())
        search_queries = tuple(rewritten.search_queries or ()) or (search_query,)
    return CellRetrievalParams(
        case_id=str(file.case_id),
        file_id=str(file.id),
        filename=str(file.filename or ""),
        original_text=str(file.original_text or ""),
        query=source_query,
        column_type=str(column.column_type or "text"),
        search_query=search_query,
        query_embedding=query_embedding,
        rewrite_method=rewrite_method,
        rewrite_rationale=rewrite_rationale,
        exact_query=exact_query,
        column_label=str(getattr(column, "column_label", None) or ""),
        lexical_terms=lexical_terms,
        exact_literals=exact_literals,
        search_queries=search_queries,
        file_context=file_context,
        preferred_zones=preferred_zones,
    )


def doc_belongs_to_file(doc: Document, file_id: str, filename: str = "") -> bool:
    """Strict scope: tabular rows must not leak chunks from sibling files."""
    meta = doc.metadata or {}
    fid = str(file_id)
    if str(meta.get("file_id") or "") == fid or str(meta.get("doc_id") or "") == fid:
        return True
    sf = str(meta.get("source_file") or "")
    if filename and sf and (sf == filename or sf.endswith(filename)):
        return True
    return False


def retrieve_case_assistant_context_for_cell(
    rag_service,
    *,
    params: CellRetrievalParams,
    db,
) -> Tuple[str, List[Document], List[Document], Dict[str, Any]]:
    """
    Internal case-assistant retrieval for one file (router → hybrid recall → rerank → assemble).

    Returns (context_text, included_docs, recall_pool_docs, meta).
    """
    from app.services.tabular_context_compiler import (
        compile_tabular_cell_context,
        tabular_context_compiler_enabled,
    )

    budget = _tabular_cell_budget_profile(params.column_type)
    if tabular_context_compiler_enabled():
        from app.services.observability.case_assistant_langfuse_tracing import case_assistant_span

        with case_assistant_span(
            "tabular.compile_context",
            input_payload={
                "file_id": params.file_id,
                "column_type": params.column_type,
            },
            metadata={"case_id": params.case_id},
        ):
            return compile_tabular_cell_context(
                rag_service,
                params=params,
                db=db,
                budget=budget,
                doc_belongs_to_file=doc_belongs_to_file,
            )

    # Legacy path (compiler disabled)
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
    # Cross-encoder: include anchors / lexical terms so related sections lose to proof.
    rerank_bits = [exact_query or "", " ".join(lexical_terms), search_query]
    rerank_question = " ".join(b for b in rerank_bits if b).strip() or search_query

    attached_file_ids = [params.file_id]
    final_k = final_k_for_budget(budget)
    meta: Dict[str, Any] = {
        "pipeline": True,
        "file_id": params.file_id,
        "corpus_size": 1,
        "source_query": (params.query or "")[:500],
        "search_query": search_query[:500],
        "exact_query": (exact_query or "")[:64],
        "lexical_terms": list(lexical_terms)[:12],
        "rewrite_method": params.rewrite_method or "",
        "rewrite_rationale": (params.rewrite_rationale or "")[:200],
    }

    # Front-matter / identity channel (party roles, header requisites).
    # Prefer lawyer prompt for intent; fall back to rewritten search query.
    # Clause-exact / lexical keyword questions stay on the hybrid + pin path.
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
                return fm.context_text, list(fm.documents), list(fm.documents), meta
        except Exception as fm_exc:
            logger.warning(
                "Front-matter channel failed file=%s: %s",
                params.file_id,
                fm_exc,
                exc_info=True,
            )
            meta["front_matter_error"] = str(fm_exc)[:200]
    else:
        meta["front_matter"] = {
            "skipped": "exact_or_lexical_query",
            "exact_query": bool(exact_query),
            "lexical_terms": len(lexical_terms),
        }

    query_embedding = list(params.query_embedding) if params.query_embedding else None

    retrieval_task = None
    if pipeline_enabled() and query_embedding is None:
        try:
            router = create_case_retrieval_router()
            # Scope only: keep column-level rewritten search_query (router would
            # otherwise pass the attached-file path through unchanged anyway).
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
            logger.warning(
                "Tabular cell retrieval router failed file=%s: %s",
                params.file_id,
                exc,
            )
    elif query_embedding is not None:
        meta["scope_mode"] = "attached"
        meta["query_embedding_reused"] = True

    recall_docs, recall_meta = run_hybrid_recall(
        rag_service=rag_service,
        case_id=params.case_id,
        question=search_query,
        db=db,
        retrieval_task=retrieval_task,
        attached_file_ids=attached_file_ids,
        budget_profile=budget,
        query_embedding=query_embedding,
        exact_query=exact_query,
    )
    meta.update(recall_meta or {})
    recall_docs = [
        d
        for d in (recall_docs or [])
        if d is not None
        and getattr(d, "page_content", None)
        and doc_belongs_to_file(d, params.file_id, params.filename)
    ]

    # Independent lexical channel: literal term hits cannot sink under dense noise.
    if lexical_terms:
        try:
            from app.services.retrieval_channels import (
                merge_retrieval_channels,
                recall_lexical_term_docs,
            )

            vector_store = getattr(
                getattr(rag_service, "document_processor", None),
                "vector_store",
                None,
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
            logger.warning(
                "Lexical recall failed file=%s: %s",
                params.file_id,
                lex_exc,
                exc_info=True,
            )
            meta["lexical_recall_error"] = str(lex_exc)[:200]

    if not recall_docs:
        meta["status"] = "no_recall_docs"
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
    included_docs = documents_from_state_serializable(assembled.get("rag_documents"))
    meta["docs"] = len(included_docs)
    if not context_text.strip() or not included_docs:
        meta["status"] = "empty_context"
        return "", [], recall_docs, meta
    return context_text, included_docs, recall_docs, meta


def prepare_cell_retrieval_sync(
    rag_service,
    *,
    params: CellRetrievalParams,
) -> PreparedCellContext:
    """
    Blocking case-assistant RAG for one cell (one file scope).

    Uses a dedicated DB session and plain-value params so parallel workers stay thread-safe.
    Short documents skip chunk RAG and use full original_text (phase 2.4).
    """
    from app.services.tabular_short_doc_policy import (
        build_short_doc_cell_context,
        should_use_short_doc_full_text,
    )
    from app.utils.database import SessionLocal

    if should_use_short_doc_full_text(params.original_text):
        context_text, included_docs = build_short_doc_cell_context(
            original_text=params.original_text,
            file_id=params.file_id,
            filename=params.filename,
        )
        return PreparedCellContext(
            file_chunks=list(included_docs),
            context_text=context_text,
            included_docs=included_docs,
            retrieval_meta={
                "status": "short_doc_full_text",
                "short_doc_chars": len(context_text),
            },
        )

    db = SessionLocal()
    try:
        context_text, included_docs, recall_pool, retrieval_meta = retrieve_case_assistant_context_for_cell(
            rag_service,
            params=params,
            db=db,
        )
        navigation = str((retrieval_meta or {}).get("navigation_context") or "")

        if context_text.strip() and included_docs:
            return PreparedCellContext(
                file_chunks=recall_pool,
                context_text=context_text,
                included_docs=included_docs,
                navigation_context=navigation,
                retrieval_meta=retrieval_meta,
            )

        if not params.original_text.strip():
            return PreparedCellContext(
                file_chunks=[],
                context_text="",
                included_docs=[],
                error="No text content",
            )
        return PreparedCellContext(
            file_chunks=[],
            context_text="",
            included_docs=[],
            error="No chunks available for extraction",
        )
    finally:
        db.close()


def rerank_for_cell(query: str, docs: List[Document], column_type: str) -> List[Document]:
    final_k = tabular_final_k(column_type)
    if not tabular_rerank_enabled():
        return truncate_recall_to_final_k(docs, final_k)
    return rerank_case_documents(
        question=query,
        docs=docs,
        final_k=final_k,
        budget_profile={"rerank_enabled": True},
    )


def format_cell_context(
    rag_service,
    docs: List[Document],
    *,
    column_type: str = "text",
) -> Tuple[str, List[Document]]:
    max_chars = _tabular_cell_budget_profile(column_type)["max_context_chars"]
    return rag_service.format_sources_for_prompt_with_docs(
        docs,
        max_context_chars=max_chars,
    )


def column_type_description(column: TabularColumn) -> str:
    descriptions: Dict[str, str] = {
        "text": "свободный текст",
        "number": "числовое значение",
        "currency": "денежная сумма с валютой (например: '100000 USD' или '50 000 руб.')",
        "yes_no": "только «Да» или «Нет» (русский канон)",
        "date": "дата в формате YYYY-MM-DD",
        "tag": "один тег из предопределенного списка",
        "verbatim": "точная цитата из документа с указанием источника",
        "manual_input": "ручной ввод (не используется AI)",
    }
    return descriptions.get(column.column_type, "свободный текст")


def tag_options_suffix(column: TabularColumn) -> str:
    if column.column_type != "tag" or not column.column_config:
        return ""
    options = column.column_config.get("options", [])
    if not options:
        return ""
    labels = ", ".join(opt.get("label", "") for opt in options if opt.get("label"))
    return f"\n\nДоступные опции тега: {labels}"


def _build_system_prompt_content(column: TabularColumn) -> str:
    """System instructions without LangChain template variables (no curly braces)."""
    type_desc = column_type_description(column)
    tag_text = tag_options_suffix(column)
    value_contract = cell_value_field_description(column)
    date_rules = ""
    if column.column_type == "date":
        date_rules = (
            "\nДля date:\n"
            "- Извлеки дату издания / подписания / составления ЭТОГО документа "
            "из шапки или титульного блока\n"
            "- Не бери даты из ссылок на законы (ФЗ), «ред. от», чужие договоры и приложения\n"
            "- cell_value — только YYYY-MM-DD или ровно «—»\n"
        )
    yes_no_rules = ""
    if column.column_type == "yes_no":
        yes_no_rules = (
            "\nДля yes_no:\n"
            '- cell_value — строго «Да», «Нет» или «—»\n'
            "- «Да» — в документе есть основание для положительного ответа на вопрос колонки\n"
            "- «Нет» — в документе явно следует отрицательный ответ\n"
            "- «—» — в фрагментах нет данных для ответа (не выдумывай)\n"
            "- Не используй Yes/No, true/false, 1/0, N/A\n"
        )
    return (
        "Ты эксперт по извлечению информации из юридических документов.\n"
        f"Тип ответа: {column.column_type}\n"
        f"Описание: {type_desc}{tag_text}\n"
        f"Формат cell_value: {value_contract}{date_rules}{yes_no_rules}\n\n"
        "ВАЖНО:\n"
        "- Указывай source_page только как целое число страницы; если неизвестно — не указывай поле\n"
        '- Указывай source_section при наличии (например, "Раздел 3.1")\n'
        "- Для любого ответа кроме «—» обязательны: verbatim_extract (дословная цитата) "
        "и source_references с полем text — цитата должна буквально встречаться во фрагментах\n"
        "- Сначала найди цитату-основание, затем выведи cell_value только из этой цитаты\n"
        "- Указывай source_references — массив цитат с полями text, page и при необходимости section\n"
        "- Указывай reasoning — как cell_value следует из цитаты\n"
        "- Указывай confidence (0.0–1.0)\n"
        '- Если информации нет в фрагментах — cell_value = "—" (не выдумывай)\n'
        "- Не отвечай без дословной опоры на приведённые фрагменты\n"
        "- Для tag используй только опции из списка выше"
    )


def build_extraction_prompt(column: TabularColumn) -> ChatPromptTemplate:
    system_content = _build_system_prompt_content(column)
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                system_content,
            ),
            (
                "human",
                """Вопрос: {question}

{navigation_block}
Фрагменты документа (уже отобраны по релевантности):
{context}

Сначала выбери дословную цитату-основание из фрагментов, затем извлеки значение
для ячейки согласно типу {column_type}. Без цитаты во фрагментах — «—».
Если тип verbatim — cell_value и verbatim_extract совпадают.""",
            ),
        ]
    )


async def _invoke_single_pass_cell_extraction(
    llm,
    *,
    column: TabularColumn,
    context_text: str,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    file: File,
    navigation_context: str = "",
) -> TabularCellExtractionModel:
    """Single structured LLM call over the full retrieval bag (evidence gate applies later)."""
    prompt = build_extraction_prompt(column)
    schema = extraction_schema_for_column(column)
    nav_block = ""
    if (navigation_context or "").strip():
        nav_block = (
            "Контекст навигации (куда смотрели в документе; не цитата):\n"
            f"{navigation_context.strip()}\n"
        )

    invoke_payload = {
        "question": column.prompt,
        "navigation_block": nav_block,
        "context": context_text,
        "column_type": column.column_type,
    }

    async def _finalize(raw_result: Any) -> TabularCellExtractionModel:
        if hasattr(raw_result, "model_dump"):
            result_dict = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result_dict = raw_result
        else:
            result_dict = raw_result.__dict__ if hasattr(raw_result, "__dict__") else {}
        result_dict = normalize_fn(result_dict, column, file)
        result_dict.setdefault("extraction_method", "llm_rag")
        return typed_extraction_to_cell_model(result_dict, column=column)

    try:
        structured_llm = llm.with_structured_output(schema, method="json_mode")
        chain = prompt | structured_llm
        raw = await chain.ainvoke(invoke_payload)
        return await _finalize(raw)
    except Exception as structured_err:
        logger.warning("Tabular structured output failed, fallback chain: %s", structured_err)

    chain = prompt | llm
    response = await chain.ainvoke(invoke_payload)
    response_text = response.content if hasattr(response, "content") else str(response)

    try:
        from app.services.langchain_agents.llm_helper import create_fixing_parser

        parser = create_fixing_parser(schema, llm, max_retries=2)
        result = parser.parse(response_text)
        return await _finalize(result)
    except Exception:
        pass

    json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL)
    if json_match:
        import json as json_module

        try:
            parsed = json_module.loads(json_match.group(0))
            return await _finalize(parsed)
        except Exception:
            pass

    return typed_extraction_to_cell_model(
        {
            "cell_value": TABULAR_NA_VALUE,
            "reasoning": ensure_na_reasoning(
                f"Не удалось извлечь данные из документа '{file.filename}'"
            ),
            "extraction_method": "llm_rag",
        },
        column=column,
    )


async def invoke_structured_cell_extraction(
    llm,
    *,
    column: TabularColumn,
    context_text: str,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    file: File,
    navigation_context: str = "",
) -> TabularCellExtractionModel:
    """Single-pass structured extraction; evidence-first gate validates quotes."""
    return await _invoke_single_pass_cell_extraction(
        llm,
        column=column,
        context_text=context_text,
        normalize_fn=normalize_fn,
        file=file,
        navigation_context=navigation_context,
    )


def enrich_source_from_documents(
    result: TabularCellExtractionModel,
    included_docs: List[Document],
) -> TabularCellExtractionModel:
    """
    Attach page/section from chunks that contain the model's quote.

    Never invent verbatim_extract from the top chunk.
    Never stamp chunk-level char_start/char_end onto source_references — those
    offsets belong to the whole leaf/parent chunk and cause PDF highlights to
    start before the quote. Quote spans are resolved later via
    locate_quote_in_original in the cell payload / geometry enrichers.
    """
    if not included_docs:
        return result

    from app.services.tabular_quote_then_answer import normalize_for_grounding

    anchor = (result.verbatim_extract or "").strip()
    if not anchor and isinstance(result.source_references, list):
        for ref in result.source_references:
            if isinstance(ref, dict):
                candidate = str(ref.get("text") or "").strip()
                if candidate:
                    anchor = candidate
                    break

    if not anchor:
        # Only page/section from top hit when the model gave no quote at all.
        top = included_docs[0]
        meta = top.metadata or {}
        page = meta.get("source_page")
        if not result.source_page and page is not None:
            result.source_page = page
        if not result.source_section and meta.get("source_section"):
            result.source_section = meta.get("source_section")
        return result

    anchor_norm = normalize_for_grounding(anchor)
    for doc in included_docs:
        content_norm = normalize_for_grounding(doc.page_content or "")
        if not content_norm or anchor_norm not in content_norm:
            continue
        meta = doc.metadata or {}
        page = meta.get("source_page")
        if not result.source_page and page is not None:
            result.source_page = page
        if not result.source_section and meta.get("source_section"):
            result.source_section = meta.get("source_section")
        if not result.source_references:
            result.source_references = [
                {
                    "text": anchor[:500],
                    "page": page,
                    "section": meta.get("source_section"),
                }
            ]
        if not result.verbatim_extract:
            result.verbatim_extract = anchor[:500]
        break
    return result


def try_extraction_from_front_matter(
    included_docs: List[Document],
    *,
    column: TabularColumn,
) -> Optional[TabularCellExtractionModel]:
    """
    When retrieval is a front-matter hit, write the matched fact ``value`` into the
    cell without a second extract-LLM call (avoids N/A on structured fact cards).
    """
    from app.services.front_matter_facts import extraction_dict_from_front_matter_docs

    payload = extraction_dict_from_front_matter_docs(included_docs)
    if not payload:
        return None
    try:
        return typed_extraction_to_cell_model(payload, column=column)
    except Exception:
        logger.warning(
            "Front-matter direct extraction failed column=%s",
            getattr(column, "id", None),
            exc_info=True,
        )
        return None


@dataclass
class TabularCellPipelineResult:
    """Output of the canonical retrieve → extract → verify pipeline."""

    extraction: TabularCellExtractionModel
    prepared: PreparedCellContext
    verification: CellVerificationOutcome


def tabular_cell_data_router_enabled() -> bool:
    from app.services.tabular_cell_data_router import tabular_cell_data_router_enabled as _enabled

    return _enabled()


def format_routed_cell_context(*, sql_block: str = "", rag_block: str = "") -> str:
    sections: List[str] = []
    if (sql_block or "").strip():
        sections.append("[SQL — структурированные данные выписки]\n" + sql_block.strip())
    if (rag_block or "").strip():
        sections.append("[RAG — фрагменты документа]\n" + rag_block.strip())
    return "\n\n".join(sections)


def enrich_extraction_from_routed_context(
    extraction: TabularCellExtractionModel,
    *,
    data_plane: str,
    file: File,
    included_docs: List[Document],
    transaction_rows: Optional[List[Any]] = None,
) -> TabularCellExtractionModel:
    """Merge SQL/RAG provenance after routed tabular extraction."""
    plane = (data_plane or "rag").strip().lower()
    extraction.extraction_method = f"tabular_routed_{plane}"
    if not extraction.reasoning.strip():
        extraction.reasoning = (
            f"Извлечено через {plane.upper()} из документа '{file.filename}'."
        )

    rows = transaction_rows or []
    if rows and not extraction.source_references:
        refs: List[Dict[str, Any]] = []
        for row in rows[:5]:
            quote = (getattr(row, "description", None) or getattr(row, "operation_datetime_text", None) or "").strip()
            amount_raw = getattr(row, "amount_raw", None)
            if amount_raw:
                quote = f"{amount_raw} — {quote}".strip(" —")
            refs.append(
                {
                    "text": quote[:500],
                    "page": getattr(row, "page_start", None),
                    "section": None,
                }
            )
        extraction.source_references = refs
        first_page = getattr(rows[0], "page_start", None)
        if not extraction.source_page and first_page:
            extraction.source_page = first_page
        if not extraction.verbatim_extract and refs:
            extraction.verbatim_extract = refs[0].get("text")

    extraction = enrich_source_from_documents(extraction, included_docs)
    return extraction


def _build_sql_routed_failure_result(
    *,
    file: File,
    column: TabularColumn,
    reason: str,
) -> TabularCellPipelineResult:
    extraction = TabularCellExtractionModel(
        cell_value=TABULAR_NA_VALUE,
        reasoning=ensure_na_reasoning(
            f"SQL-запрос не выполнен для '{file.filename}': {reason}"
        ),
        column_type=str(column.column_type or "text"),
        extraction_method="tabular_routed_sql",
    )
    prepared = PreparedCellContext(file_chunks=[], context_text="", included_docs=[])
    verification = CellVerificationOutcome(
        result=extraction,
        needs_review=True,
        issues=["sql_fetch_failed"],
    )
    return TabularCellPipelineResult(
        extraction=extraction,
        prepared=prepared,
        verification=verification,
    )


async def _run_routed_sql_flag_cell_extraction(
    llm,
    *,
    rag_service,
    db,
    file: File,
    column: TabularColumn,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    column_run=None,
) -> Optional[TabularCellPipelineResult]:
    """Routed SQL/RAG/hybrid path for files with ingested statement rows."""
    import asyncio

    from app.services.chat.file_scoped_agent_tools import scoped_files_have_transactions
    from app.services.tabular_cell_data_router import route_tabular_cell_data_plane
    from app.services.tabular_cell_sql_fetch import fetch_tabular_cell_sql_context

    if not tabular_cell_data_router_enabled():
        return None
    if not scoped_files_have_transactions(db, str(file.case_id), [str(file.id)]):
        return None

    question = (column.prompt or column.column_label or "").strip()
    if not question:
        return None

    route = await asyncio.to_thread(
        route_tabular_cell_data_plane,
        db,
        case_id=str(file.case_id),
        file_id=str(file.id),
        column=column,
    )
    plane = route.data_plane

    async def _fetch_sql():
        if plane not in {"sql", "hybrid"}:
            return None
        return await asyncio.to_thread(
            fetch_tabular_cell_sql_context,
            db,
            case_id=str(file.case_id),
            file_id=str(file.id),
            question=question,
        )

    async def _fetch_rag():
        if plane not in {"rag", "hybrid"}:
            return None
        retrieval_params = cell_retrieval_params_from_models(file, column, column_run=column_run)
        return await asyncio.to_thread(
            prepare_cell_retrieval_sync,
            rag_service,
            params=retrieval_params,
        )

    sql_ctx, rag_prepared = await asyncio.gather(_fetch_sql(), _fetch_rag())

    if plane == "sql":
        if not sql_ctx or not sql_ctx.ok:
            reason = (sql_ctx.reason if sql_ctx else "") or "no_sql_context"
            return _build_sql_routed_failure_result(file=file, column=column, reason=reason)

    rag_block = ""
    included_docs: List[Document] = []
    recall_pool: List[Document] = []
    if rag_prepared is not None:
        if rag_prepared.error == "No text content":
            raise ValueError("No text content")
        if rag_prepared.error == "No chunks available for extraction":
            raise ValueError("No chunks available for extraction")
        rag_block = augment_context_for_column(
            rag_prepared.context_text,
            column_type=str(column.column_type or "text"),
            original_text=str(file.original_text or ""),
        )
        included_docs = list(rag_prepared.included_docs)
        recall_pool = list(rag_prepared.file_chunks)

    if plane == "rag" and not rag_block.strip():
        return None

    if plane == "hybrid" and not rag_block.strip() and (not sql_ctx or not sql_ctx.ok):
        reason = (sql_ctx.reason if sql_ctx else "") or "hybrid_no_context"
        return _build_sql_routed_failure_result(file=file, column=column, reason=reason)

    sql_block = sql_ctx.context_text if sql_ctx and sql_ctx.ok else ""
    if plane == "hybrid" and not sql_block.strip() and not rag_block.strip():
        return _build_sql_routed_failure_result(file=file, column=column, reason="hybrid_empty")

    context_text = format_routed_cell_context(sql_block=sql_block, rag_block=rag_block)
    if not context_text.strip():
        return None

    extraction = try_extraction_from_front_matter(included_docs, column=column)
    if extraction is None:
        extraction = await invoke_structured_cell_extraction(
            llm,
            column=column,
            context_text=context_text,
            normalize_fn=normalize_fn,
            file=file,
        )
        transaction_rows = list(sql_ctx.rows) if sql_ctx and sql_ctx.ok else []
        extraction = enrich_extraction_from_routed_context(
            extraction,
            data_plane=plane,
            file=file,
            included_docs=included_docs,
            transaction_rows=transaction_rows,
        )
    else:
        extraction = enrich_source_from_documents(extraction, included_docs)

    prepared = PreparedCellContext(
        file_chunks=recall_pool or included_docs,
        context_text=context_text,
        included_docs=included_docs,
    )

    verification = apply_evidence_first_policy(
        extraction,
        column=column,
        file=file,
        included_docs=included_docs,
    )
    if plane == "hybrid" and sql_ctx and not sql_ctx.ok:
        verification.needs_review = True
        verification.issues.append("sql_partial_in_hybrid")

    logger.info(
        "[TabularRoutedCell] file=%s column=%s plane=%s sql_ok=%s rag_docs=%s",
        file.id,
        column.id,
        plane,
        bool(sql_ctx and sql_ctx.ok),
        len(included_docs),
    )
    return TabularCellPipelineResult(
        extraction=verification.result,
        prepared=prepared,
        verification=verification,
    )


async def run_tabular_cell_extraction(
    llm,
    *,
    rag_service,
    file: File,
    column: TabularColumn,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    column_run=None,
    db=None,
    file_context_packages: Optional[Dict[str, Any]] = None,
) -> TabularCellPipelineResult:
    """
    One cell routed by ColumnKind:
    manual → skip; risk_analysis → fixed graph; else schema-first → SQL/RAG.
    """
    from app.services.contract_facts_service import try_extraction_from_contract_facts
    from app.services.tabular_column_kind import resolve_column_kind
    from app.services.tabular_extraction_schemas import typed_extraction_to_cell_model
    from app.services.tabular_risk_analysis_graph import run_tabular_risk_analysis

    kind = resolve_column_kind(column)

    if kind == "manual":
        extraction = typed_extraction_to_cell_model(
            {
                "cell_value": TABULAR_NA_VALUE,
                "reasoning": "Колонка manual — без AI-извлечения",
                "extraction_method": "manual",
                "confidence": 0.0,
            },
            column=column,
        )
        prepared = PreparedCellContext(
            file_chunks=[],
            context_text="",
            included_docs=[],
            retrieval_meta={"status": "manual", "column_kind": kind},
        )
        verification = apply_evidence_first_policy(
            extraction,
            column=column,
            file=file,
            included_docs=[],
        )
        return TabularCellPipelineResult(
            extraction=verification.result,
            prepared=prepared,
            verification=verification,
        )

    if kind == "risk_analysis":
        file_ctx = None
        if file_context_packages:
            file_ctx = file_context_packages.get(str(file.id))
        extraction, docs, risk_meta = await run_tabular_risk_analysis(
            llm,
            rag_service=rag_service,
            file=file,
            column=column,
            normalize_fn=normalize_fn,
            column_run=column_run,
            file_context=file_ctx,
        )
        risk_meta = dict(risk_meta or {})
        risk_meta["column_kind"] = kind
        prepared = PreparedCellContext(
            file_chunks=list(docs),
            context_text=(extraction.verbatim_extract or extraction.cell_value or ""),
            included_docs=list(docs),
            retrieval_meta=risk_meta,
        )
        verification = apply_evidence_first_policy(
            extraction,
            column=column,
            file=file,
            included_docs=docs,
        )
        return TabularCellPipelineResult(
            extraction=verification.result,
            prepared=prepared,
            verification=verification,
        )

    # fact / verbatim / summary → schema-first then RAG
    schema_hit = try_extraction_from_contract_facts(file, column, allow_lazy=True)
    if schema_hit is not None:
        extraction, evidence_docs, schema_meta = schema_hit
        schema_meta = dict(schema_meta or {})
        schema_meta["column_kind"] = kind
        prepared = PreparedCellContext(
            file_chunks=list(evidence_docs),
            context_text=(extraction.verbatim_extract or extraction.cell_value or ""),
            included_docs=list(evidence_docs),
            retrieval_meta=schema_meta,
        )
        verification = apply_evidence_first_policy(
            extraction,
            column=column,
            file=file,
            included_docs=evidence_docs,
        )
        return TabularCellPipelineResult(
            extraction=verification.result,
            prepared=prepared,
            verification=verification,
        )

    if db is not None:
        routed_result = await _run_routed_sql_flag_cell_extraction(
            llm,
            rag_service=rag_service,
            db=db,
            file=file,
            column=column,
            normalize_fn=normalize_fn,
            column_run=column_run,
        )
        if routed_result is not None:
            return routed_result

    import asyncio

    file_ctx = None
    if file_context_packages:
        file_ctx = file_context_packages.get(str(file.id))
    retrieval_params = cell_retrieval_params_from_models(
        file,
        column,
        column_run=column_run,
        file_context=file_ctx,
    )
    # Summary columns: prefer fuller short-doc / larger budget via column_type already
    prepared = await asyncio.to_thread(
        prepare_cell_retrieval_sync,
        rag_service,
        params=retrieval_params,
    )
    if prepared.error == "No text content":
        raise ValueError("No text content")
    if prepared.error == "No chunks available for extraction":
        raise ValueError("No chunks available for extraction")
    if not prepared.context_text.strip():
        raise ValueError("empty_context")

    context_text = augment_context_for_column(
        prepared.context_text,
        column_type=str(column.column_type or "text"),
        original_text=str(file.original_text or ""),
    )
    if prepared.retrieval_meta is None:
        prepared.retrieval_meta = {}
    prepared.retrieval_meta["column_kind"] = kind

    extraction = try_extraction_from_front_matter(prepared.included_docs, column=column)
    if extraction is None:
        extraction = await invoke_structured_cell_extraction(
            llm,
            column=column,
            context_text=context_text,
            normalize_fn=normalize_fn,
            file=file,
            navigation_context=prepared.navigation_context,
        )
        extraction = enrich_source_from_documents(extraction, prepared.included_docs)
    verification = apply_evidence_first_policy(
        extraction,
        column=column,
        file=file,
        included_docs=prepared.included_docs,
    )
    return TabularCellPipelineResult(
        extraction=verification.result,
        prepared=prepared,
        verification=verification,
    )
