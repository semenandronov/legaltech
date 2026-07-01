"""Tools for file-scoped document agent (SQL transactions + RAG within scoped files)."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled,
)
from app.services.chat.case_transaction_tools import (
    aggregate_case_transactions,
    initialize_case_transaction_tools,
    list_case_transactions,
    pop_transaction_tool_citation_rows,
    reset_transaction_tool_citation_rows,
)

logger = logging.getLogger(__name__)

_db: Optional[Session] = None
_case_id: Optional[str] = None
_scoped_file_ids: Optional[List[str]] = None
_rag_service = None
_rag_citation_docs: List[Document] = []


def reset_file_scoped_tool_state() -> None:
    """Clear per-turn citation buffers."""
    global _rag_citation_docs
    _rag_citation_docs = []
    reset_transaction_tool_citation_rows()


def pop_file_scoped_rag_documents() -> List[Document]:
    global _rag_citation_docs
    docs = list(_rag_citation_docs)
    _rag_citation_docs = []
    return docs


def _record_rag_documents(docs: Sequence[Document]) -> None:
    global _rag_citation_docs
    seen = {id(d) for d in _rag_citation_docs}
    for doc in docs:
        if id(doc) not in seen:
            _rag_citation_docs.append(doc)
            seen.add(id(doc))


def initialize_file_scoped_tools(
    *,
    db: Session,
    case_id: str,
    file_ids: Sequence[str],
    rag_service,
) -> None:
    global _db, _case_id, _scoped_file_ids, _rag_service
    _db = db
    _case_id = case_id
    _scoped_file_ids = [str(fid).strip() for fid in file_ids if str(fid).strip()]
    _rag_service = rag_service
    initialize_case_transaction_tools(
        db=db,
        case_id=case_id,
        attached_file_ids=_scoped_file_ids,
    )


def scoped_files_have_transactions(db: Session, case_id: str, file_ids: Sequence[str]) -> bool:
    if not feature_enabled():
        return False
    ids = [str(fid).strip() for fid in file_ids if str(fid).strip()]
    if not ids:
        return False
    return CaseFileTransactionService.case_has_transactions(db, case_id, ids)


@tool
def search_in_scoped_files(query: str, k: int = 15) -> str:
    """
    Семантический поиск по тексту документов в текущей области (один или несколько файлов дела).

    ИСПОЛЬЗУЙ для:
    - шапки выписки, реквизитов, банка, номера счёта;
    - точных цитат и формулировок из PDF;
    - вопросов, где ответ в тексте, а не в таблице операций.

    НЕ используй для полного списка операций или сумм за период — для этого list_case_transactions / aggregate_case_transactions.

    Args:
        query: поисковый запрос
        k: число фрагментов (5–30)
    """
    if not _rag_service or not _case_id:
        return "Поиск недоступен: контекст дела не инициализирован."

    scoped = list(_scoped_file_ids or [])
    if not scoped:
        return "Нет файлов в области поиска."

    k_val = max(5, min(30, int(k or 15)))
    try:
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query=(query or "").strip(),
            k=k_val,
            retrieval_strategy="multi_query",
            db=_db,
            file_ids=scoped,
        )
    except Exception as exc:
        logger.warning("[FileScopedTools] search failed: %s", exc)
        return f"Ошибка поиска: {exc}"

    if not documents:
        return f"По запросу «{query}» ничего не найдено в выбранных документах."

    scoped_set = set(scoped)
    filtered: List[Document] = []
    for doc in documents:
        meta = doc.metadata or {}
        fid = str(meta.get("file_id") or meta.get("doc_id") or "")
        if fid and fid in scoped_set:
            filtered.append(doc)
    if not filtered:
        filtered = list(documents)

    _record_rag_documents(filtered[:k_val])

    parts: List[str] = []
    for idx, doc in enumerate(filtered[:k_val], 1):
        meta = doc.metadata or {}
        page = meta.get("page_start") or meta.get("source_page") or meta.get("page")
        page_hint = f", стр. {page}" if page is not None else ""
        text = (doc.page_content or "").strip()
        if not text:
            continue
        parts.append(f"[{idx}{page_hint}]\n{text[:2500]}")

    if not parts:
        return "Фрагменты пусты."

    logger.info(
        "[FileScopedTools] search_in_scoped_files case=%s files=%s hits=%s",
        _case_id,
        len(scoped),
        len(parts),
    )
    return "\n\n".join(parts)


def get_file_scoped_tools(
    db: Session,
    case_id: str,
    file_ids: Sequence[str],
    rag_service,
    *,
    sql_only: bool = False,
) -> List:
    """
    Return tools for the file-scoped agent.

    sql_only=True (chat SQL path): only transaction SQL tools, no text search.
    """
    initialize_file_scoped_tools(
        db=db,
        case_id=case_id,
        file_ids=file_ids,
        rag_service=rag_service,
    )
    tools: List = []
    if scoped_files_have_transactions(db, case_id, file_ids):
        tools.extend([list_case_transactions, aggregate_case_transactions])
    if not sql_only:
        tools.insert(0, search_in_scoped_files)
    return tools
