"""
Tabular cell extraction: case-assistant-style RAG (recall → rerank → single LLM).

All column types, including document_type, are filled from retrieved context + model output.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import config
from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.chat.case_context_pipeline import rerank_case_documents
from app.services.document_type_labels import DOC_TYPE_LABELS
from app.services.tabular_cell_verification import (
    CellVerificationOutcome,
    apply_evidence_first_policy,
)
from app.services.tabular_review_models import TabularCellExtractionModel

logger = logging.getLogger(__name__)

_SIMPLE_COLUMN_TYPES = frozenset({"date", "currency", "number", "yes_no", "tag"})


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
    """Tabular-specific rerank toggle (independent of case assistant rerank)."""
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
    return f"{column.prompt} {column.column_label}".strip()


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


def recall_documents_for_cell(
    rag_service,
    *,
    case_id: str,
    file_id: str,
    query: str,
    db=None,
    filename: str = "",
) -> List[Document]:
    """Case-assistant hybrid recall (macro/micro funnel) scoped to one file."""
    k = tabular_recall_k()
    docs = rag_service.retrieve_context(
        case_id=case_id,
        query=query,
        k=k,
        retrieval_strategy="hybrid",
        db=db,
        use_hybrid=True,
        file_ids=[file_id],
        metadata_filter={"file_id": file_id},
        pipeline_micro_only=True,
    )
    valid = [d for d in (docs or []) if d is not None and getattr(d, "page_content", None)]
    scoped = [d for d in valid if doc_belongs_to_file(d, file_id, filename)]
    if scoped:
        return scoped
    if valid:
        logger.warning(
            "Tabular recall: %s docs for case %s but none scoped to file %s",
            len(valid),
            case_id,
            file_id,
        )
    return []


def prepare_cell_retrieval_sync(
    rag_service,
    *,
    case_id: str,
    file: File,
    column: TabularColumn,
) -> PreparedCellContext:
    """
    Blocking recall → rerank → context format for one cell.

    Uses a dedicated DB session so parallel asyncio.to_thread workers stay thread-safe.
    """
    from app.utils.database import SessionLocal

    query = build_retrieval_query(column)
    db = SessionLocal()
    try:
        file_chunks = recall_documents_for_cell(
            rag_service,
            case_id=case_id,
            file_id=file.id,
            query=query,
            db=db,
            filename=file.filename or "",
        )

        if not file_chunks:
            file_chunks = fallback_chunks_from_file_text(file)
            if not file_chunks and not (file.original_text or "").strip():
                return PreparedCellContext(
                    file_chunks=[],
                    context_text="",
                    included_docs=[],
                    error="No text content",
                )
            if not file_chunks:
                return PreparedCellContext(
                    file_chunks=[],
                    context_text="",
                    included_docs=[],
                    error="No chunks available for extraction",
                )
            logger.info(
                "Tabular cell using local text chunks for file %s (index empty)",
                file.id,
            )

        ranked_docs = rerank_for_cell(query, file_chunks, column.column_type)
        context_text, included_docs = format_cell_context(rag_service, ranked_docs)
        return PreparedCellContext(
            file_chunks=file_chunks,
            context_text=context_text,
            included_docs=included_docs,
        )
    finally:
        db.close()


def fallback_chunks_from_file_text(file: File, *, max_chunks: int = 8) -> List[Document]:
    document_text = file.original_text or ""
    if not document_text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )
    raw_chunks = splitter.split_text(document_text)
    return [
        Document(
            page_content=raw_chunks[i],
            metadata={
                "chunk_index": i,
                "file_id": file.id,
                "source_file": file.filename,
            },
        )
        for i in range(min(max_chunks, len(raw_chunks)))
    ]


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
) -> Tuple[str, List[Document]]:
    return rag_service.format_sources_for_prompt_with_docs(
        docs,
        max_context_chars=tabular_context_max_chars(),
    )


def _document_type_hint() -> str:
    examples = ", ".join(list(DOC_TYPE_LABELS.values())[:12])
    return (
        "Определи категорию документа по содержанию и структуре (заголовок, стороны, предмет, "
        "процессуальные формулировки). Не ищи готовую строку «Тип документа:». "
        f"Ответ на русском, кратко (например: {examples}, …)."
    )


def column_type_description(column: TabularColumn) -> str:
    descriptions: Dict[str, str] = {
        "text": "свободный текст",
        "number": "числовое значение",
        "currency": "денежная сумма с валютой (например: '100000 USD' или '50 000 руб.')",
        "yes_no": "только 'Yes' или 'No'",
        "date": "дата в формате YYYY-MM-DD",
        "tag": "один тег из предопределенного списка",
        "verbatim": "точная цитата из документа с указанием источника",
        "manual_input": "ручной ввод (не используется AI)",
        "document_type": _document_type_hint(),
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


def build_extraction_prompt(column: TabularColumn, context_text: str) -> ChatPromptTemplate:
    type_desc = column_type_description(column)
    tag_text = tag_options_suffix(column)
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                f"""Ты эксперт по извлечению информации из юридических документов.
Тип ответа: {column.column_type}
Описание: {type_desc}{tag_text}

ВАЖНО:
- Указывай source_page только как целое число страницы; если неизвестно — не указывай поле
- Указывай source_section при наличии (например, "Раздел 3.1")
- source_references — JSON-массив объектов: [{{"text": "цитата из фрагмента", "page": 1}}]
- verbatim_extract — дословная цитата-поддержка ответа (если применимо)
- Указывай reasoning — откуда взято значение
- Указывай confidence (0.0–1.0)
- Если информации нет в фрагментах — cell_value = "N/A" (не выдумывай)
- Не отвечай без опоры на приведённые фрагменты
- Для tag используй только опции из списка выше""",
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
    """Single LLM call with merged retrieval context."""
    prompt = build_extraction_prompt(column, context_text)

    async def _parse_raw(raw_result: Any) -> TabularCellExtractionModel:
        if hasattr(raw_result, "model_dump"):
            result_dict = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result_dict = raw_result
        else:
            result_dict = raw_result.__dict__ if hasattr(raw_result, "__dict__") else {}
        result_dict = normalize_fn(result_dict, column, file)
        result_dict["column_type"] = column.column_type
        result_dict["extraction_method"] = result_dict.get("extraction_method") or "llm_rag"
        return TabularCellExtractionModel(**result_dict)

    try:
        structured_llm = llm.with_structured_output(TabularCellExtractionModel, method="json_mode")
        chain = prompt | structured_llm
        raw = await chain.ainvoke(
            {
                "question": column.prompt,
                "context": context_text,
                "column_type": column.column_type,
            }
        )
        return await _parse_raw(raw)
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

        parser = create_fixing_parser(TabularCellExtractionModel, llm, max_retries=2)
        result = parser.parse(response_text)
        result.column_type = column.column_type
        result.extraction_method = "llm_rag"
        return result
    except Exception:
        pass

    json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL)
    if json_match:
        import json as json_module

        try:
            parsed = json_module.loads(json_match.group(0))
            return await _parse_raw(parsed)
        except Exception:
            pass

    return TabularCellExtractionModel(
        cell_value="N/A",
        reasoning=f"Не удалось извлечь данные из документа '{file.filename}'",
        column_type=column.column_type,
        extraction_method="llm_rag",
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
) -> TabularCellPipelineResult:
    """
    Production cell pipeline (Harvey-style stages):

    1. retrieve_evidence — case-assistant hybrid RAG, scoped to file
    2. extract_structured — single LLM call on merged context
    3. verify — evidence-first policy before persist
    """
    import asyncio

    prepared = await asyncio.to_thread(
        prepare_cell_retrieval_sync,
        rag_service,
        case_id=file.case_id,
        file=file,
        column=column,
    )
    if prepared.error == "No text content":
        raise ValueError("No text content")
    if prepared.error == "No chunks available for extraction":
        raise ValueError("No chunks available for extraction")
    if not prepared.context_text.strip():
        raise ValueError("empty_context")

    extraction = await invoke_structured_cell_extraction(
        llm,
        column=column,
        context_text=prepared.context_text,
        normalize_fn=normalize_fn,
        file=file,
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
