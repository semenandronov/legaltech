"""Attach cross-referenced sections to tabular cell context."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.contract_cross_ref_resolve import (
    parse_contract_cross_references,
    resolve_ref_to_section_root_ids,
)
from app.services.tabular_document_context import TabularFileContextPackage

logger = logging.getLogger(__name__)


def tabular_cross_ref_follow_enabled() -> bool:
    return bool(getattr(config, "TABULAR_CROSS_REF_FOLLOW_ENABLED", False))


def tabular_cross_ref_max_chars() -> int:
    return max(400, int(getattr(config, "TABULAR_CROSS_REF_MAX_CHARS", 2500) or 2500))


def _outline_rows(pkg: TabularFileContextPackage) -> List[Tuple[str, str, str, str]]:
    return [
        (e.section_root_id, e.section_number, e.section_title, e.section_label)
        for e in pkg.outline
    ]


def enrich_docs_with_cross_references(
    docs: Sequence[Document],
    *,
    file_context: Optional[TabularFileContextPackage],
    vector_store: Any,
    case_id: str,
    file_id: str,
    max_refs: int = 3,
) -> Tuple[List[Document], Dict[str, Any]]:
    meta: Dict[str, Any] = {"cross_ref_enrich": False}
    if not tabular_cross_ref_follow_enabled() or not file_context or not vector_store:
        meta["skipped"] = "disabled_or_no_context"
        return list(docs), meta

    outline = _outline_rows(file_context)
    if not outline:
        meta["skipped"] = "empty_outline"
        return list(docs), meta

    refs = []
    for doc in list(docs)[:5]:
        md = doc.metadata or {}
        for raw in list(md.get("cross_references") or [])[:6]:
            refs.append(str(raw))
        refs.extend([r.raw for r in parse_contract_cross_references(doc.page_content or "", limit=4)])

    section_ids: List[str] = []
    for raw in refs:
        for parsed in parse_contract_cross_references(raw, limit=2):
            section_ids.extend(resolve_ref_to_section_root_ids(parsed, outline))

    section_ids = list(dict.fromkeys(section_ids))[:max_refs]
    if not section_ids:
        meta["skipped"] = "no_resolved_refs"
        return list(docs), meta

    try:
        section_map = vector_store.fetch_macro_chunks_by_section_root_ids(case_id, section_ids) or {}
    except Exception as exc:
        logger.warning("cross_ref fetch failed: %s", exc)
        meta["error"] = str(exc)[:200]
        return list(docs), meta

    extra: List[Document] = []
    budget = tabular_cross_ref_max_chars()
    used = 0
    for sid in section_ids:
        for macro in section_map.get(sid) or []:
            text = str(getattr(macro, "page_content", "") or "")
            if not text.strip():
                continue
            if used + len(text) > budget:
                break
            extra.append(macro)
            used += len(text)

    if not extra:
        meta["skipped"] = "no_extra_docs"
        return list(docs), meta

    merged = list(docs)
    seen = {id(d) for d in merged}
    for d in extra:
        if id(d) not in seen:
            merged.append(d)
            seen.add(id(d))

    meta.update({"cross_ref_enrich": True, "sections": section_ids, "extra_docs": len(extra)})
    return merged, meta
