"""Target-anchored cross-reference follow for tabular cell context.

Contract (context-engineering):
1. If the column names an exact clause (e.g. 7.9), that clause is the primary
   evidence — always first in the prompt, never displaced by follows.
2. Cross-refs are parsed ONLY from the target clause body (not from the whole
   recall bag / neighboring 7.8).
3. Followed appendices are supplements AFTER the target, not a replacement.
4. Without an exact clause (e.g. «Объект аренды»), follow from top subject
   hits as before so Приложение №1 inventory can load.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.clause_anchor import (
    normalize_clause_number,
    postgres_clause_boundary_regex,
    text_has_clause_boundary,
)
from app.services.contract_cross_ref_resolve import collect_follow_section_ids
from app.services.tabular_document_context import TabularFileContextPackage

logger = logging.getLogger(__name__)

_INVENTORY_HINT_RE = re.compile(
    r"(?i)зарядн|количеств|наименован|E-Scooter|итого|спецификац|"
    r"электросамокат|шт\.|штук|цена\s+за\s+единиц"
)
_SIGNATURE_HEAVY_RE = re.compile(
    r"(?i)(?:бик|р/с|кор\.?\s*сч|паспорт|реквизиты\s+расчетного).{0,80}"
    r"(?:бик|р/с|инн)"
)
_NEXT_CLAUSE_HEADING_RE = re.compile(
    r"(?m)^(?:\s*)(?:п\.?\s*п\.?|пункт|п\.?)?\s*(\d+(?:\.\d+)*)(?:\.(?!\d)|\s)"
)


def tabular_cross_ref_follow_enabled() -> bool:
    return bool(getattr(config, "TABULAR_CROSS_REF_FOLLOW_ENABLED", True))


def tabular_cross_ref_max_chars() -> int:
    return max(400, int(getattr(config, "TABULAR_CROSS_REF_MAX_CHARS", 2500) or 2500))


def tabular_cross_ref_appendix_max_chars() -> int:
    return max(
        tabular_cross_ref_max_chars(),
        int(getattr(config, "TABULAR_CROSS_REF_APPENDIX_MAX_CHARS", 9000) or 9000),
    )


def _macro_inventory_score(text: str) -> int:
    body = text or ""
    score = 0
    if _INVENTORY_HINT_RE.search(body):
        score += 20
    if re.search(r"(?i)зарядн", body):
        score += 15
    if re.search(r"(?i)\b\d{1,4}\s+\d{1,3}(?:\s?\d{3})+", body):
        score += 8
    if _SIGNATURE_HEAVY_RE.search(body) and score < 15:
        score -= 12
    return score


def extract_clause_body(text: str, exact_query: str) -> str:
    """Slice one clause body from a larger section chunk (7.9 without 7.8)."""
    anchor = normalize_clause_number(exact_query)
    body = text or ""
    if not anchor or not body:
        return ""
    rx = postgres_clause_boundary_regex(anchor)
    if not rx:
        return ""
    m = re.search(rx, body, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    rest = body[m.end() :]
    for nm in _NEXT_CLAUSE_HEADING_RE.finditer(rest):
        other = normalize_clause_number(nm.group(1))
        if not other or other == anchor:
            continue
        if other.startswith(anchor + "."):
            continue  # 7.9.1 stays inside 7.9
        return body[start : m.end() + nm.start()].strip()
    return body[start:].strip()


def mark_exact_clause_targets(
    docs: Sequence[Document],
    exact_query: Optional[str],
) -> List[Document]:
    """Stamp docs that contain the asked clause heading as query targets."""
    anchor = normalize_clause_number(exact_query or "")
    if not anchor:
        return list(docs)
    out: List[Document] = []
    for doc in docs or []:
        text = doc.page_content or ""
        md = dict(doc.metadata or {})
        if text_has_clause_boundary(text, anchor) or md.get("anchor_match") or md.get(
            "exact_channel"
        ):
            md["query_target"] = True
            md["exact_clause_target"] = True
            md["anchor_pinned"] = True
            md["lexical_pinned"] = True
            span = extract_clause_body(text, anchor)
            if span and len(span) < len(text):
                md["query_target_span_chars"] = len(span)
            out.append(Document(page_content=doc.page_content, metadata=md))
        else:
            out.append(doc)
    return out


def order_docs_for_prompt(docs: Sequence[Document]) -> List[Document]:
    """
    Prompt order:
      1) exact query targets (the clause the user asked about)
      2) cross-ref supplements pulled FROM that target
      3) everything else
    """
    targets: List[Document] = []
    supplements: List[Document] = []
    rest: List[Document] = []
    for doc in docs or []:
        md = doc.metadata or {}
        if md.get("query_target") or md.get("exact_clause_target"):
            targets.append(doc)
        elif md.get("cross_ref_followed") or md.get("cross_ref_required"):
            supplements.append(doc)
        else:
            rest.append(doc)
    return targets + supplements + rest


def prioritize_required_cross_ref_docs(docs: Sequence[Document]) -> List[Document]:
    """Backward-compatible alias — target-first ordering."""
    return order_docs_for_prompt(docs)


def _follow_seed_texts(
    docs: Sequence[Document],
    *,
    exact_query: Optional[str],
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """
    Build texts used to discover follows.

    Exact clause mode → only the target clause bodies.
    Otherwise → top bag (subject / inventory questions).
    """
    meta: Dict[str, Any] = {}
    anchor = normalize_clause_number(exact_query or "")
    texts: List[str] = []
    extra_raw: List[str] = []

    if anchor:
        targets = [
            d
            for d in docs
            if (d.metadata or {}).get("query_target")
            or text_has_clause_boundary(d.page_content or "", anchor)
        ]
        meta["follow_mode"] = "exact_clause_target"
        meta["target_docs"] = len(targets)
        if not targets:
            # No verified target yet — do NOT scavenge neighbor refs.
            meta["follow_mode"] = "exact_clause_no_target"
            return [], [], meta
        for doc in targets:
            span = extract_clause_body(doc.page_content or "", anchor)
            texts.append(span or (doc.page_content or ""))
            md = doc.metadata or {}
            for raw in list(md.get("cross_references") or [])[:8]:
                # Only keep metadata refs that also appear in the target span.
                raw_s = str(raw)
                seed = span or (doc.page_content or "")
                if raw_s and raw_s.lower() in seed.lower():
                    extra_raw.append(raw_s)
        return texts, extra_raw, meta

    meta["follow_mode"] = "bag_subject"
    for doc in list(docs)[:8]:
        texts.append(doc.page_content or "")
        md = doc.metadata or {}
        for raw in list(md.get("cross_references") or [])[:8]:
            extra_raw.append(str(raw))
    return texts, extra_raw, meta


def enrich_docs_with_cross_references(
    docs: Sequence[Document],
    *,
    file_context: Optional[TabularFileContextPackage],
    vector_store: Any,
    case_id: str,
    file_id: str,
    max_refs: int = 3,
    exact_query: Optional[str] = None,
) -> Tuple[List[Document], Dict[str, Any]]:
    """
    One-hop follow anchored on the query target when exact_query is set.
    """
    meta: Dict[str, Any] = {"cross_ref_enrich": False, "file_id": file_id}
    working = mark_exact_clause_targets(docs, exact_query)

    if not tabular_cross_ref_follow_enabled() or not file_context or not vector_store:
        meta["skipped"] = "disabled_or_no_context"
        return order_docs_for_prompt(working), meta

    if not file_context.outline:
        meta["skipped"] = "empty_outline"
        return order_docs_for_prompt(working), meta

    texts, extra_raw, seed_meta = _follow_seed_texts(working, exact_query=exact_query)
    meta.update(seed_meta)

    if not texts:
        meta["skipped"] = seed_meta.get("follow_mode") or "no_follow_seeds"
        return order_docs_for_prompt(working), meta

    section_ids, used_refs = collect_follow_section_ids(
        texts,
        file_context.outline,
        extra_raw_refs=extra_raw,
        max_refs=max(8, max_refs * 3),
        max_sections=max_refs,
    )
    meta["parsed_refs"] = [
        {"kind": r.kind, "anchor": r.anchor, "raw": r.raw[:80]} for r in used_refs
    ]
    has_appendix = any(r.kind in ("appendix", "appendix_clause") for r in used_refs)
    meta["has_appendix_follow"] = has_appendix
    exact_mode = bool(normalize_clause_number(exact_query or ""))

    if not section_ids:
        meta["skipped"] = "no_resolved_refs"
        return order_docs_for_prompt(working), meta

    try:
        section_map = (
            vector_store.fetch_macro_chunks_by_section_root_ids(case_id, list(section_ids))
            or {}
        )
    except Exception as exc:
        logger.warning("cross_ref fetch failed: %s", exc)
        meta["error"] = str(exc)[:200]
        return order_docs_for_prompt(working), meta

    # Exact-clause questions: smaller appendix budget — target must dominate.
    if exact_mode:
        budget = min(tabular_cross_ref_max_chars(), 3200)
    elif has_appendix:
        budget = tabular_cross_ref_appendix_max_chars()
    else:
        budget = tabular_cross_ref_max_chars()

    extra: List[Document] = []
    used = 0
    for sid in section_ids:
        macros = list(section_map.get(sid) or [])
        macros.sort(
            key=lambda m: (
                -_macro_inventory_score(str(getattr(m, "page_content", "") or "")),
                int((getattr(m, "metadata", None) or {}).get("char_start") or 0),
            )
        )
        for macro in macros:
            md = getattr(macro, "metadata", None) or {}
            macro_fid = str(md.get("file_id") or "").strip()
            if macro_fid and macro_fid != str(file_id):
                continue
            text = str(getattr(macro, "page_content", "") or "")
            if not text.strip():
                continue
            inventory_hit = _macro_inventory_score(text) >= 20
            if used + len(text) > budget and extra and not (inventory_hit and not exact_mode):
                continue
            if used + len(text) > budget * (1 if exact_mode else 2):
                break
            tagged = Document(
                page_content=macro.page_content,
                metadata={
                    **dict(md),
                    "cross_ref_followed": True,
                    # Required supplement, but NOT above the query target.
                    "cross_ref_required": not exact_mode,
                    "cross_ref_supplement": True,
                    "cross_ref_section_root_id": sid,
                    "anchor_pinned": True,
                    "lexical_pinned": True,
                },
            )
            extra.append(tagged)
            used += len(text)

    if not extra:
        meta["skipped"] = "no_extra_docs"
        return order_docs_for_prompt(working), meta

    merged: List[Document] = []
    seen_keys = set()
    # Targets stay ahead of follows — never prepend appendix over 7.9.
    for d in list(working) + list(extra):
        md = d.metadata or {}
        key = (
            str(md.get("chunk_id") or md.get("id") or ""),
            str(md.get("section_root_id") or ""),
            (d.page_content or "")[:80],
        )
        if key in seen_keys:
            continue
        merged.append(d)
        seen_keys.add(key)

    meta.update(
        {
            "cross_ref_enrich": True,
            "cross_ref_required": not exact_mode,
            "sections": list(section_ids),
            "extra_docs": len(extra),
            "chars_used": used,
            "budget_chars": budget,
            "exact_query": normalize_clause_number(exact_query or "") or None,
        }
    )
    return order_docs_for_prompt(merged), meta
