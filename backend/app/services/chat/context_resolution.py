"""
Parent context resolution: ranked micro chunks → deduplicated macro parents for LLM.

After cross-encoder rerank on short micro passages, expand to logically complete
macro blocks stored at indexing time (LegalChunkerV2 parent-child contract).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from app.config import config

logger = logging.getLogger(__name__)


def parent_context_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_PARENT_CONTEXT_ENABLED", True))


def micro_only_recall_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED", True))


def micro_recall_k() -> int:
    return max(8, int(getattr(config, "CASE_ASSISTANT_MICRO_RECALL_K", 40) or 40))


def chunk_level(doc: Document) -> str:
    return str((doc.metadata or {}).get("chunk_level") or "").strip().lower()


def is_micro_chunk(doc: Document) -> bool:
    return chunk_level(doc) in ("micro", "row")


def is_macro_chunk(doc: Document) -> bool:
    return chunk_level(doc) in ("macro", "preamble")


def parent_macro_id(doc: Document) -> str:
    md = doc.metadata or {}
    pid = str(md.get("parent_macro_id") or "").strip()
    if pid:
        return pid
    if is_macro_chunk(doc):
        return str(md.get("macro_id") or md.get("chunk_id") or "").strip()
    return ""


def filter_rerank_pool_to_micro(docs: List[Document]) -> List[Document]:
    """
    Keep micro + docling anchor chunks for rerank; drop macro from rerank pool.

    Legacy chunks without chunk_level pass through unchanged.
    """
    if not docs:
        return []
    has_levels = any(chunk_level(d) for d in docs)
    if not has_levels:
        return list(docs)
    out: List[Document] = []
    for d in docs:
        level = chunk_level(d)
        if level in ("micro", "row", "docling", ""):
            out.append(d)
        elif level in ("macro", "preamble"):
            continue
        else:
            out.append(d)
    return out if out else list(docs)


def resolve_parent_context(
    ranked_docs: List[Document],
    *,
    case_id: str,
    vector_store,
) -> Tuple[List[Document], Dict[str, Any]]:
    """
    Expand ranked micro hits to deduplicated macro parents (preserving rerank order).

    Citation metadata from the best micro hit per parent is copied onto the macro doc.
    """
    meta: Dict[str, Any] = {
        "parent_context": True,
        "input_docs": len(ranked_docs or []),
        "parents_requested": 0,
        "parents_resolved": 0,
        "fallback_micro": 0,
    }
    if not ranked_docs:
        return [], meta

    if not parent_context_enabled() or not vector_store:
        meta["parent_context"] = False
        meta["reason"] = "disabled_or_no_store"
        return list(ranked_docs), meta

    ordered_parent_ids: List[str] = []
    best_micro_by_parent: Dict[str, Document] = {}
    passthrough: List[Document] = []

    for doc in ranked_docs:
        if is_micro_chunk(doc):
            pid = parent_macro_id(doc)
            if not pid:
                passthrough.append(doc)
                continue
            if pid not in best_micro_by_parent:
                ordered_parent_ids.append(pid)
                best_micro_by_parent[pid] = doc
            else:
                prev_score = float((best_micro_by_parent[pid].metadata or {}).get("rerank_score") or 0)
                cur_score = float((doc.metadata or {}).get("rerank_score") or 0)
                if cur_score > prev_score:
                    best_micro_by_parent[pid] = doc
        elif is_macro_chunk(doc):
            pid = parent_macro_id(doc)
            if pid and pid not in best_micro_by_parent:
                ordered_parent_ids.append(pid)
                best_micro_by_parent[pid] = doc
            else:
                passthrough.append(doc)
        else:
            passthrough.append(doc)

    if not ordered_parent_ids:
        meta["reason"] = "no_parent_ids"
        meta["fallback_micro"] = len(passthrough)
        return list(ranked_docs), meta

    meta["parents_requested"] = len(ordered_parent_ids)
    macro_map = vector_store.fetch_macro_chunks_by_macro_ids(case_id, ordered_parent_ids)

    resolved: List[Document] = []
    seen_parents: set[str] = set()

    for pid in ordered_parent_ids:
        if pid in seen_parents:
            continue
        seen_parents.add(pid)
        macro = macro_map.get(pid)
        anchor = best_micro_by_parent.get(pid)
        if macro is None:
            if anchor is not None:
                resolved.append(anchor)
                meta["fallback_micro"] += 1
            continue
        out_doc = Document(
            page_content=macro.page_content,
            metadata=dict(macro.metadata or {}),
        )
        md = out_doc.metadata
        if anchor is not None:
            am = anchor.metadata or {}
            md["rerank_score"] = am.get("rerank_score")
            md["grounding_micro_chunk_id"] = am.get("chunk_id")
            md["grounding_micro_char_start"] = am.get("char_start")
            md["grounding_micro_char_end"] = am.get("char_end")
            if am.get("rerank_score") is not None:
                md["context_resolution"] = "macro_from_micro"
        else:
            md["context_resolution"] = "macro_direct"
        resolved.append(out_doc)

    for doc in passthrough:
        pid = parent_macro_id(doc)
        if pid and pid in seen_parents:
            continue
        resolved.append(doc)

    meta["parents_resolved"] = len(resolved)
    meta["output_docs"] = len(resolved)
    if not resolved:
        meta["reason"] = "fetch_miss"
        return list(ranked_docs), meta

    logger.info(
        "[ContextResolution] case=%s micro_in=%s parents=%s resolved=%s fallback_micro=%s",
        case_id,
        len(ranked_docs),
        len(ordered_parent_ids),
        len(resolved),
        meta["fallback_micro"],
    )
    return resolved, meta
