"""
Parent context resolution: ranked micro → hard legal section for LLM.

Contract (LegalChunkerV2 v2.2):
- Retrieve/rerank on micro leaves.
- Expand to the full hard section (section_root_id), stitching all size-window
  macros that share that root — not only the single size-macro that owns the hit.
- Legacy chunks without section_root_id fall back to parent_macro_id expand.
- PDF geometry stays on micro leaves (grounding_* stamped on the section doc).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config

logger = logging.getLogger(__name__)


def parent_context_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_PARENT_CONTEXT_ENABLED", True))


def micro_only_recall_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED", True))


def micro_recall_k() -> int:
    return max(8, int(getattr(config, "CASE_ASSISTANT_MICRO_RECALL_K", 40) or 40))


def section_context_max_chars() -> int:
    return max(1200, int(getattr(config, "CASE_ASSISTANT_SECTION_CONTEXT_MAX_CHARS", 8000) or 8000))


def chunk_level(doc: Document) -> str:
    return str((doc.metadata or {}).get("chunk_level") or "").strip().lower()


def is_micro_chunk(doc: Document) -> bool:
    return chunk_level(doc) == "micro"


def is_macro_chunk(doc: Document) -> bool:
    return chunk_level(doc) == "macro"


def parent_macro_id(doc: Document) -> str:
    md = doc.metadata or {}
    pid = str(md.get("parent_macro_id") or "").strip()
    if pid:
        return pid
    if is_macro_chunk(doc):
        return str(md.get("macro_id") or md.get("chunk_id") or "").strip()
    return ""


def section_root_id(doc: Document) -> str:
    return str((doc.metadata or {}).get("section_root_id") or "").strip()


def expand_key(doc: Document) -> Tuple[str, str]:
    """
    Key used to group hits for LLM context.

    Prefer hard section root; fall back to size-macro id for legacy indexes.
    Returns (kind, id) where kind is "section" | "macro".
    """
    sid = section_root_id(doc)
    if sid:
        return ("section", sid)
    pid = parent_macro_id(doc)
    if pid:
        return ("macro", pid)
    return ("", "")


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
        if level in ("micro", "docling", ""):
            out.append(d)
        elif level == "macro":
            continue
        else:
            out.append(d)
    return out if out else list(docs)


def _char_start(doc: Document) -> int:
    try:
        return int((doc.metadata or {}).get("char_start") or 0)
    except (TypeError, ValueError):
        return 0


def _char_end(doc: Document) -> int:
    try:
        return int((doc.metadata or {}).get("char_end") or 0)
    except (TypeError, ValueError):
        return 0


def stitch_section_macros(macros: Sequence[Document]) -> Tuple[str, int, int]:
    """
    Join size-window macros of one hard section in char order, dropping overlap.

    Overlap windows share a char-span prefix; we skip that prefix in the next
    macro's text using the same offsets used at index time.
    Returns (text, char_start, char_end) of the assembled span.
    """
    ordered = sorted(macros, key=_char_start)
    if not ordered:
        return "", 0, 0

    parts: List[str] = []
    last_end = -1
    span_start = _char_start(ordered[0])
    span_end = span_start

    for doc in ordered:
        cs, ce = _char_start(doc), _char_end(doc)
        text = doc.page_content or ""
        if ce <= last_end:
            continue
        if last_end < 0 or cs >= last_end:
            if text:
                parts.append(text)
            span_end = max(span_end, ce if ce > cs else span_end + len(text))
            last_end = max(last_end, ce if ce > cs else last_end + len(text))
            if last_end < 0:
                last_end = len(text)
            continue

        # Overlapping window: drop the already-covered prefix.
        overlap = last_end - cs
        span_len = max(ce - cs, 1)
        if abs(len(text) - span_len) <= 2:
            skip = min(max(0, overlap), len(text))
        else:
            # Rare misaligned metadata: map overlap proportionally into text.
            skip = min(len(text), max(0, int(round(len(text) * (overlap / span_len)))))
        remnant = text[skip:]
        if remnant:
            parts.append(remnant)
        span_end = max(span_end, ce)
        last_end = max(last_end, ce)

    return "".join(parts), span_start, span_end


def fit_section_text_to_budget(
    text: str,
    *,
    max_chars: int,
    grounding_char_start: Optional[int],
    grounding_char_end: Optional[int],
    section_char_start: int,
) -> str:
    """
    Fit a hard section into the LLM budget.

    Prefer keeping the section head (title + early clauses). If the grounding
    micro lies beyond the budget, keep a short head and a window that covers it.
    """
    body = text or ""
    if len(body) <= max_chars:
        return body

    head_keep = min(1200, max(400, max_chars // 4))
    g_start = grounding_char_start
    g_end = grounding_char_end
    if g_start is None or g_end is None or g_end <= g_start:
        return body[:max_chars]

    # Offsets relative to assembled section text.
    rel_start = max(0, int(g_start) - int(section_char_start))
    rel_end = max(rel_start, int(g_end) - int(section_char_start))
    if rel_end <= max_chars:
        return body[:max_chars]

    tail_budget = max_chars - head_keep - 5
    if tail_budget < 200:
        return body[:max_chars]

    pad = 200
    need_end = min(len(body), rel_end + pad)
    tail_start = max(head_keep, need_end - tail_budget)
    if tail_start <= head_keep:
        return body[:max_chars]
    return body[:head_keep] + "\n…\n" + body[tail_start:need_end]


def _stamp_grounding(md: Dict[str, Any], anchor: Optional[Document], resolution: str) -> None:
    if anchor is None:
        md["context_resolution"] = resolution
        return
    am = anchor.metadata or {}
    md["rerank_score"] = am.get("rerank_score")
    md["grounding_micro_chunk_id"] = am.get("chunk_id")
    md["grounding_micro_char_start"] = am.get("char_start")
    md["grounding_micro_char_end"] = am.get("char_end")
    if am.get("dl_meta") is not None and not md.get("grounding_micro_dl_meta"):
        md["grounding_micro_dl_meta"] = am.get("dl_meta")
    if am.get("page_start") is not None:
        md["grounding_micro_page_start"] = am.get("page_start")
    if not str(md.get("section_title") or "").strip() and am.get("section_title"):
        md["section_title"] = am.get("section_title")
    if not str(md.get("section_number") or "").strip() and am.get("section_number"):
        md["section_number"] = am.get("section_number")
    md["context_resolution"] = resolution


def resolve_parent_context(
    ranked_docs: List[Document],
    *,
    case_id: str,
    vector_store,
) -> Tuple[List[Document], Dict[str, Any]]:
    """
    Expand ranked micro hits to deduplicated hard sections (or legacy macros).

    Citation/geometry consumers should use grounding_micro_* / leaf recall pool.
    """
    meta: Dict[str, Any] = {
        "parent_context": True,
        "input_docs": len(ranked_docs or []),
        "parents_requested": 0,
        "parents_resolved": 0,
        "sections_resolved": 0,
        "macros_resolved": 0,
        "fallback_micro": 0,
    }
    if not ranked_docs:
        return [], meta

    if not parent_context_enabled() or not vector_store:
        meta["parent_context"] = False
        meta["reason"] = "disabled_or_no_store"
        return list(ranked_docs), meta

    ordered_keys: List[Tuple[str, str]] = []
    best_micro_by_key: Dict[Tuple[str, str], Document] = {}
    passthrough: List[Document] = []

    for doc in ranked_docs:
        if is_micro_chunk(doc) or is_macro_chunk(doc):
            key = expand_key(doc)
            if not key[1]:
                passthrough.append(doc)
                continue
            if key not in best_micro_by_key:
                ordered_keys.append(key)
                best_micro_by_key[key] = doc
            else:
                prev_score = float((best_micro_by_key[key].metadata or {}).get("rerank_score") or 0)
                cur_score = float((doc.metadata or {}).get("rerank_score") or 0)
                if cur_score > prev_score:
                    best_micro_by_key[key] = doc
        else:
            passthrough.append(doc)

    if not ordered_keys:
        meta["reason"] = "no_parent_ids"
        meta["fallback_micro"] = len(passthrough)
        return list(ranked_docs), meta

    meta["parents_requested"] = len(ordered_keys)
    section_ids = [kid for kind, kid in ordered_keys if kind == "section"]
    macro_ids = [kid for kind, kid in ordered_keys if kind == "macro"]

    section_map: Dict[str, List[Document]] = {}
    macro_map: Dict[str, Document] = {}
    if section_ids and hasattr(vector_store, "fetch_macro_chunks_by_section_root_ids"):
        section_map = vector_store.fetch_macro_chunks_by_section_root_ids(case_id, section_ids) or {}
    if macro_ids:
        macro_map = vector_store.fetch_macro_chunks_by_macro_ids(case_id, macro_ids) or {}

    resolved: List[Document] = []
    seen: set[Tuple[str, str]] = set()
    max_chars = section_context_max_chars()

    for key in ordered_keys:
        if key in seen:
            continue
        seen.add(key)
        kind, kid = key
        anchor = best_micro_by_key.get(key)

        if kind == "section":
            macros = section_map.get(kid) or []
            if not macros:
                if anchor is not None:
                    resolved.append(anchor)
                    meta["fallback_micro"] += 1
                continue
            stitched, sec_cs, sec_ce = stitch_section_macros(macros)
            if not stitched.strip():
                if anchor is not None:
                    resolved.append(anchor)
                    meta["fallback_micro"] += 1
                continue
            g_cs = (anchor.metadata or {}).get("char_start") if anchor else None
            g_ce = (anchor.metadata or {}).get("char_end") if anchor else None
            try:
                g_cs_i = int(g_cs) if g_cs is not None else None
                g_ce_i = int(g_ce) if g_ce is not None else None
            except (TypeError, ValueError):
                g_cs_i, g_ce_i = None, None
            fitted = fit_section_text_to_budget(
                stitched,
                max_chars=max_chars,
                grounding_char_start=g_cs_i,
                grounding_char_end=g_ce_i,
                section_char_start=sec_cs,
            )
            head = macros[0]
            out_doc = Document(
                page_content=fitted,
                metadata=dict(head.metadata or {}),
            )
            md = out_doc.metadata
            md["chunk_level"] = "macro"
            md["section_root_id"] = kid
            md["char_start"] = sec_cs
            md["char_end"] = sec_ce
            md["section_macro_count"] = len(macros)
            md["section_context_chars"] = len(fitted)
            _stamp_grounding(md, anchor, "section_from_micro")
            resolved.append(out_doc)
            meta["sections_resolved"] += 1
            continue

        # Legacy: single size-macro expand.
        macro = macro_map.get(kid)
        if macro is None:
            if anchor is not None:
                resolved.append(anchor)
                meta["fallback_micro"] += 1
            continue
        out_doc = Document(
            page_content=macro.page_content,
            metadata=dict(macro.metadata or {}),
        )
        _stamp_grounding(out_doc.metadata, anchor, "macro_from_micro" if anchor else "macro_direct")
        resolved.append(out_doc)
        meta["macros_resolved"] += 1

    for doc in passthrough:
        key = expand_key(doc)
        if key[1] and key in seen:
            continue
        resolved.append(doc)

    meta["parents_resolved"] = len(resolved)
    meta["output_docs"] = len(resolved)
    if not resolved:
        meta["reason"] = "fetch_miss"
        return list(ranked_docs), meta

    logger.info(
        "[ContextResolution] case=%s micro_in=%s keys=%s sections=%s macros=%s fallback_micro=%s",
        case_id,
        len(ranked_docs),
        len(ordered_keys),
        meta["sections_resolved"],
        meta["macros_resolved"],
        meta["fallback_micro"],
    )
    return resolved, meta
