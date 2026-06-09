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
from app.services.tabular_cell_verification import CellVerificationOutcome
from app.services.tabular_extraction_schemas import (
    cell_value_field_description,
    extraction_schema_for_column,
    typed_extraction_to_cell_model,
)
from app.services.tabular_review_models import TabularCellExtractionModel

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


@dataclass
class PreparedCellContext:
    """Sync retrieval output for one tabular cell (recall → rerank → format)."""

    file_chunks: List[Document]
    context_text: str
    included_docs: List[Document]
    error: Optional[str] = None


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
        return max(2, int(getattr(config, "TABULAR_FINAL_K_SIMPLE", 3) or 3))
    return max(3, int(getattr(config, "TABULAR_FINAL_K", 5) or 5))


def tabular_context_max_chars() -> int:
    return max(2000, int(getattr(config, "TABULAR_CONTEXT_MAX_CHARS", 6000) or 6000))


def tabular_rerank_enabled() -> bool:
    """Cross-encoder rerank per cell (off by default; single-file scope uses hybrid top-k)."""
    return bool(getattr(config, "TABULAR_RERANK_ENABLED", False))


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

    header = original_text.strip()[:2500]
    if not header:
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
    """Single-file tabular retrieval budget (not whole-case corpus scale)."""
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
        "parent_context_enabled": False,
    }


def cell_retrieval_params_from_models(
    file: File,
    column: TabularColumn,
    *,
    column_run: Optional["TabularColumnRunContext"] = None,
) -> CellRetrievalParams:
    """Snapshot ORM fields on the request thread before asyncio.to_thread workers."""
    from app.services.tabular_column_run_context import TabularColumnRunContext

    run_ctx: Optional[TabularColumnRunContext] = column_run
    search_query = run_ctx.search_query if run_ctx else build_retrieval_query(column)
    query_embedding = run_ctx.query_embedding if run_ctx else ()
    return CellRetrievalParams(
        case_id=str(file.case_id),
        file_id=str(file.id),
        filename=str(file.filename or ""),
        original_text=str(file.original_text or ""),
        query=build_retrieval_query(column),
        column_type=str(column.column_type or "text"),
        search_query=search_query,
        query_embedding=query_embedding,
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
    query = (params.search_query or params.query).strip()
    if not query:
        return "", [], [], {"status": "empty_query"}

    attached_file_ids = [params.file_id]
    budget = _tabular_cell_budget_profile(params.column_type)
    final_k = final_k_for_budget(budget)
    meta: Dict[str, Any] = {"pipeline": True, "file_id": params.file_id, "corpus_size": 1}

    query_embedding = list(params.query_embedding) if params.query_embedding else None
    search_query = query

    retrieval_task = None
    if pipeline_enabled() and query_embedding is None:
        try:
            router = create_case_retrieval_router()
            retrieval_task = router.route(
                question=query,
                case_id=params.case_id,
                db=db,
                attached_file_ids=attached_file_ids,
                corpus_size=1,
            )
            meta["scope_mode"] = retrieval_task.scope_mode
            meta["router_confidence"] = retrieval_task.confidence
            search_query = (retrieval_task.search_query if retrieval_task else None) or query
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
    )
    meta.update(recall_meta or {})
    recall_docs = [
        d
        for d in (recall_docs or [])
        if d is not None
        and getattr(d, "page_content", None)
        and doc_belongs_to_file(d, params.file_id, params.filename)
    ]
    if not recall_docs:
        meta["status"] = "no_recall_docs"
        return "", [], [], meta

    ranked_docs, resolve_meta = rerank_and_resolve_documents(
        question=search_query,
        docs=recall_docs,
        final_k=final_k,
        case_id=params.case_id,
        rag_service=rag_service,
        budget_profile=budget,
    )
    meta.update(resolve_meta or {})
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
    """
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        context_text, included_docs, recall_pool, _meta = retrieve_case_assistant_context_for_cell(
            rag_service,
            params=params,
            db=db,
        )

        if context_text.strip() and included_docs:
            return PreparedCellContext(
                file_chunks=recall_pool,
                context_text=context_text,
                included_docs=included_docs,
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
            "- Извлеки дату подписания или составления ЭТОГО документа из шапки, реквизитов, "
            "строки «г. …» или блока подписей\n"
            "- Не подставляй даты из приложений, ссылок на другие документы и исторических данных сторон\n"
            "- cell_value — только YYYY-MM-DD или ровно N/A\n"
        )
    yes_no_rules = ""
    if column.column_type == "yes_no":
        yes_no_rules = (
            "\nДля yes_no:\n"
            '- cell_value — строго «Да», «Нет» или N/A\n'
            "- «Да» — в документе есть основание для положительного ответа на вопрос колонки\n"
            "- «Нет» — в документе явно следует отрицательный ответ\n"
            "- N/A — в фрагментах нет данных для ответа (не выдумывай)\n"
            "- Не используй Yes/No, true/false, 1/0\n"
        )
    return (
        "Ты эксперт по извлечению информации из юридических документов.\n"
        f"Тип ответа: {column.column_type}\n"
        f"Описание: {type_desc}{tag_text}\n"
        f"Формат cell_value: {value_contract}{date_rules}{yes_no_rules}\n\n"
        "ВАЖНО:\n"
        "- Указывай source_page только как целое число страницы; если неизвестно — не указывай поле\n"
        '- Указывай source_section при наличии (например, "Раздел 3.1")\n'
        "- source_references — массив цитат с полями text, page и при необходимости section\n"
        "- verbatim_extract — дословная цитата-поддержка ответа (если применимо)\n"
        "- Указывай reasoning — откуда взято значение\n"
        "- Указывай confidence (0.0–1.0)\n"
        '- Если информации нет в фрагментах — cell_value = "N/A" (не выдумывай)\n'
        "- Не отвечай без опоры на приведённые фрагменты\n"
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

Фрагменты документа (уже отобраны по релевантности):
{context}

Извлеки значение для ячейки таблицы согласно типу {column_type}.
Если тип verbatim — приведи точную цитату в verbatim_extract.""",
            ),
        ]
    )


async def invoke_structured_cell_extraction(
    llm,
    *,
    column: TabularColumn,
    context_text: str,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    file: File,
) -> TabularCellExtractionModel:
    """Single LLM call with merged retrieval context and type-specific structured output."""
    prompt = build_extraction_prompt(column)
    schema = extraction_schema_for_column(column)

    async def _finalize(raw_result: Any) -> TabularCellExtractionModel:
        if hasattr(raw_result, "model_dump"):
            result_dict = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result_dict = raw_result
        else:
            result_dict = raw_result.__dict__ if hasattr(raw_result, "__dict__") else {}
        result_dict = normalize_fn(result_dict, column, file)
        return typed_extraction_to_cell_model(result_dict, column=column)

    try:
        structured_llm = llm.with_structured_output(schema, method="json_mode")
        chain = prompt | structured_llm
        raw = await chain.ainvoke(
            {
                "question": column.prompt,
                "context": context_text,
                "column_type": column.column_type,
            }
        )
        return await _finalize(raw)
    except Exception as structured_err:
        logger.warning("Tabular structured output failed, fallback chain: %s", structured_err)

    chain = prompt | llm
    response = await chain.ainvoke(
        {
            "question": column.prompt,
            "context": context_text,
            "column_type": column.column_type,
        }
    )
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
            "cell_value": "N/A",
            "reasoning": f"Не удалось извлечь данные из документа '{file.filename}'",
            "extraction_method": "llm_rag",
        },
        column=column,
    )


def enrich_source_from_documents(
    result: TabularCellExtractionModel,
    included_docs: List[Document],
) -> TabularCellExtractionModel:
    """Fill provenance fields from top retrieved chunk when the model omitted them."""
    if not included_docs:
        return result
    top = included_docs[0]
    meta = top.metadata or {}
    page = meta.get("source_page")
    if not result.source_page and page is not None:
        result.source_page = page
    if not result.source_section and meta.get("source_section"):
        result.source_section = meta.get("source_section")
    chunk_text = (top.page_content or "").strip()
    if not result.verbatim_extract and chunk_text:
        if result.column_type == "verbatim":
            result.verbatim_extract = chunk_text[:500]
        elif not result.source_references:
            result.verbatim_extract = chunk_text[:400]
    if not result.source_references and chunk_text:
        result.source_references = [
            {
                "text": chunk_text[:500],
                "page": page,
                "section": meta.get("source_section"),
                "char_start": meta.get("char_start"),
                "char_end": meta.get("char_end"),
            }
        ]
    return result


@dataclass
class TabularCellPipelineResult:
    """Output of the canonical retrieve → extract → verify pipeline."""

    extraction: TabularCellExtractionModel
    prepared: PreparedCellContext
    verification: CellVerificationOutcome


async def run_tabular_cell_extraction(
    llm,
    *,
    rag_service,
    file: File,
    column: TabularColumn,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    column_run=None,
) -> TabularCellPipelineResult:
    """
    One cell = internal case-assistant RAG (single file) + typed structured extract.

    Column type is enforced via extraction schema + strict_normalize only.
    """
    import asyncio

    retrieval_params = cell_retrieval_params_from_models(file, column, column_run=column_run)
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

    extraction = await invoke_structured_cell_extraction(
        llm,
        column=column,
        context_text=context_text,
        normalize_fn=normalize_fn,
        file=file,
    )
    extraction = enrich_source_from_documents(extraction, prepared.included_docs)
    from app.services.tabular_cell_verification import apply_evidence_first_policy

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
