"""
Document zones for tabular DD retrieval (phase 2).

Zones are orthogonal to chunk_level (macro/micro/row): they describe *where*
in a contract the span lives so columns can prefer preamble vs table vs requisites.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

DOCUMENT_ZONES: Tuple[str, ...] = (
    "preamble",
    "body",
    "table",
    "requisites",
    "signature",
)

DOCUMENT_ZONE_SET = frozenset(DOCUMENT_ZONES)

_REQUISITES_RE = re.compile(
    r"(?i)(?:\bинн\b|\bкпп\b|\bогрн\b|\bбик\b|"
    r"р/?с\b|к/?с\b|корр(?:еспондентск)?ий\s+сч[её]т|"
    r"расч[её]тный\s+сч[её]т|банковск\w*\s+реквизит|"
    r"платежн\w*\s+реквизит)"
)
_SIGNATURE_RE = re.compile(
    r"(?i)(?:\bподпис\w*\b|\bм\.?\s*п\.?\b|печать\s+сторон|"
    r"реквизиты\s+и\s+подписи|в\s+удостоверение\s+чего)"
)
_HARD_SECTION_START_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"(?:\d{1,2}\.\s+[A-ZА-ЯЁ])|"
    r"(?:Статья\s+\d+)|"
    r"(?:РАЗДЕЛ\s+[IVXLCDM\d]+)|"
    r"(?:1\.\s*ПРЕДМЕТ)|"
    r"(?:ПРЕДМЕТ\s+ДОГОВОРА)"
    r")",
    re.IGNORECASE,
)


def normalize_zone(value: Any) -> Optional[str]:
    z = str(value or "").strip().lower()
    if z in DOCUMENT_ZONE_SET:
        return z
    if z == "full_document":
        return "full_document"
    return None


def doc_zone(doc: Document) -> str:
    meta = doc.metadata or {}
    z = normalize_zone(meta.get("zone"))
    if z and z != "full_document":
        return z
    if z == "full_document":
        return "full_document"
    return infer_chunk_zone(
        page_content=doc.page_content or "",
        metadata=meta,
    )


def _truthy(meta: Dict[str, Any], *keys: str) -> bool:
    for key in keys:
        val = meta.get(key)
        if val is True:
            return True
        if isinstance(val, str) and val.strip().lower() in {"1", "true", "yes", "y"}:
            return True
        if isinstance(val, (int, float)) and val == 1:
            return True
    return False


def _label_hints_table(meta: Dict[str, Any]) -> bool:
    for key in ("label", "docling_label", "element_type", "category", "block_type"):
        raw = str(meta.get(key) or "").strip().lower()
        if "table" in raw or raw in {"tabular", "grid"}:
            return True
    return False


def _requisites_density(text: str) -> int:
    return len(_REQUISITES_RE.findall(text or ""))


def infer_chunk_zone(
    *,
    page_content: str,
    metadata: Optional[Dict[str, Any]] = None,
    document_chars: Optional[int] = None,
) -> str:
    """
    Infer DD zone for one chunk.

    Priority: explicit metadata → table signals → requisites → signature →
    preamble (chunk_level / early position) → body.
    """
    meta = dict(metadata or {})
    explicit = normalize_zone(meta.get("zone"))
    if explicit and explicit != "full_document":
        return explicit

    text = page_content or ""
    level = str(meta.get("chunk_level") or "").strip().lower()

    if level == "row" or _truthy(meta, "is_table", "is_table_fragment", "has_table_fragment"):
        return "table"
    if _label_hints_table(meta):
        return "table"

    req_hits = _requisites_density(text)
    if req_hits >= 2 or (req_hits >= 1 and len(text) < 900):
        # Dense bank/party identifiers → requisites (even mid-doc).
        if not _HARD_SECTION_START_RE.search(text[:200]):
            return "requisites"

    if _SIGNATURE_RE.search(text) and len(text) < 2500:
        # Prefer signature when near document end.
        try:
            cs = int(meta.get("char_start") or 0)
        except (TypeError, ValueError):
            cs = 0
        doc_len = document_chars
        if doc_len is None:
            try:
                doc_len = int(meta.get("document_chars") or 0) or None
            except (TypeError, ValueError):
                doc_len = None
        if doc_len and doc_len > 0 and cs >= int(0.7 * doc_len):
            return "signature"
        if level not in {"macro", "micro"} and req_hits == 0:
            return "signature"

    if level == "preamble":
        return "preamble"

    try:
        cs = int(meta.get("char_start") or 0)
    except (TypeError, ValueError):
        cs = 0
    doc_len = document_chars
    if doc_len is None:
        try:
            doc_len = int(meta.get("document_chars") or 0) or None
        except (TypeError, ValueError):
            doc_len = None
    if doc_len and doc_len > 0 and cs <= int(0.12 * doc_len):
        if not _HARD_SECTION_START_RE.search(text[:180]):
            return "preamble"

    return "body"


def annotate_documents_with_zones(
    documents: Sequence[Document],
    *,
    document_chars: Optional[int] = None,
) -> List[Document]:
    """Mutate metadata['zone'] on each chunk; return same list for chaining."""
    if not documents:
        return list(documents)

    inferred_len = document_chars
    if inferred_len is None:
        max_end = 0
        for doc in documents:
            meta = doc.metadata or {}
            try:
                end = int(meta.get("char_end") or 0)
            except (TypeError, ValueError):
                end = 0
            if end > max_end:
                max_end = end
        inferred_len = max_end or None

    for doc in documents:
        meta = dict(doc.metadata or {})
        if inferred_len:
            meta["document_chars"] = int(inferred_len)
        zone = infer_chunk_zone(
            page_content=doc.page_content or "",
            metadata=meta,
            document_chars=inferred_len,
        )
        meta["zone"] = zone
        doc.metadata = meta
    return list(documents)


def prefer_zone_docs_for_prompt(
    docs: Sequence[Document],
    preferred_zones: Sequence[str],
) -> List[Document]:
    """
    Soft reorder: preferred-zone chunks lead; others follow (stable within groups).

    If nothing matches preferred zones, return original order unchanged.
    """
    zones = [z for z in (normalize_zone(z) for z in preferred_zones) if z and z != "full_document"]
    if not docs or not zones:
        return list(docs)

    preferred_set = frozenset(zones)
    preferred: List[Document] = []
    other: List[Document] = []
    for doc in docs:
        z = doc_zone(doc)
        if z in preferred_set or z == "full_document":
            preferred.append(doc)
        else:
            other.append(doc)
    if not preferred:
        return list(docs)
    return preferred + other


def zone_histogram(docs: Iterable[Document]) -> Dict[str, int]:
    hist: Dict[str, int] = {}
    for doc in docs:
        z = doc_zone(doc)
        hist[z] = hist.get(z, 0) + 1
    return hist
