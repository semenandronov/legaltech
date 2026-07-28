"""
Clause-number anchors for legal documents (1.4, 10.2.1, …).

Exact retrieval must match a clause heading boundary, not a substring:
``1.4`` must hit ``1.4. …`` and must not hit ``4.1.4`` or ``7.1.4``.

After hybrid recall, boundary hits must not compete in rerank for survival.
Contract: top exact-channel hits (default 3) go straight to the model, merged
with the separately reranked pool (additive — exact does not consume rerank slots).

When ``exact_query`` is set, pin selection trusts verified clause-boundary text
in the pool (not only the ``anchor_match`` flag), so downstream stages that
rebuild Document copies cannot silently drop the exact channel.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

# Multi-part numbers only (1.4, 10.2.1). Bare integers like "2024" are excluded.
_NUMERIC_CLAUSE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)+)(?!\d)")

# Optional Russian label before a number in prompts: "пункт 1.4", "п. 1.4", "п.п. 1.4"
_LABELED_CLAUSE_RE = re.compile(
    r"(?:п\.?\s*п\.?|пункт|п\.?|статья|ст\.?)\s*"
    r"(?<!\d)(\d+(?:[.,]\d+)+)(?!\d)",
    re.IGNORECASE,
)

# Exact channel → model: top-N verified clause hits (1..5 via config).
DEFAULT_MAX_CLAUSE_ANCHOR_PINS = 3


def normalize_clause_number(raw: str) -> str:
    return str(raw or "").replace(",", ".").strip()


def extract_clause_numbers(text: str) -> List[str]:
    """Unique clause-like numbers in appearance order (normalized with '.')."""
    seen: set[str] = set()
    out: List[str] = []
    for m in _NUMERIC_CLAUSE_RE.finditer(str(text or "")):
        n = normalize_clause_number(m.group(1))
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def primary_exact_anchor(text: str) -> Optional[str]:
    """
    Best single exact anchor for a column prompt/label.

    Prefer an explicitly labeled clause ("пункт 1.4"); otherwise the first
    multi-part number in the text.
    """
    src = str(text or "").strip()
    if not src:
        return None
    labeled = _LABELED_CLAUSE_RE.search(src)
    if labeled:
        return normalize_clause_number(labeled.group(1))
    nums = extract_clause_numbers(src)
    return nums[0] if nums else None


def postgres_clause_boundary_regex(anchor: str) -> Optional[str]:
    """
    Regex for a clause heading at line/string start (PostgreSQL ~* and Python re).

    Matches:
      ``1.4. Текст``
      ``1.4 Текст``
      ``п. 1.4.`` / ``пункт 1.4`` at line start

    Does not match nested numbers where ``1.4`` is only an infix (``4.1.4``).
    Mid-line cross-references without a preceding newline also do not match.
    """
    n = normalize_clause_number(anchor)
    if not n or not re.fullmatch(r"\d+(?:\.\d+)+", n):
        return None
    escaped = r"\.".join(re.escape(p) for p in n.split("."))
    # Use \s (ARE / Python), not POSIX [[:space:]], so the same pattern
    # can be unit-tested in Python and executed with PostgreSQL ~*.
    # After the number: end, whitespace, or a trailing '.' that is NOT
    # another nesting digit (so 1.4 matches "1.4. …" but not "1.4.1").
    return (
        rf"(^|[\n\r])\s*"
        rf"(?:п\.?\s*п\.?|пункт|п\.?)?\s*"
        rf"{escaped}"
        rf"(?:\.(?!\d)|\s|$)"
    )


def text_has_clause_boundary(text: str, anchor: str) -> bool:
    """True when ``text`` contains a clause heading for ``anchor`` (not a nested infix)."""
    rx = postgres_clause_boundary_regex(anchor)
    if not rx:
        return False
    return bool(re.search(rx, text or "", flags=re.IGNORECASE | re.MULTILINE))


def max_clause_anchor_pins() -> int:
    """Configurable exact-channel budget (default 3, hard-clamped to 1..5)."""
    try:
        from app.config import config

        raw = int(
            getattr(config, "CLAUSE_ANCHOR_MAX_PINS", DEFAULT_MAX_CLAUSE_ANCHOR_PINS)
            or DEFAULT_MAX_CLAUSE_ANCHOR_PINS
        )
    except Exception:
        raw = DEFAULT_MAX_CLAUSE_ANCHOR_PINS
    return max(1, min(5, raw))


def _doc_metadata(doc: Any) -> dict:
    md = getattr(doc, "metadata", None)
    return dict(md) if isinstance(md, dict) else {}


def _doc_text(doc: Any) -> str:
    return str(getattr(doc, "page_content", None) or "")


def clause_anchor_doc_identity(doc: Any) -> str:
    """Stable identity for dedupe across recall / rerank / parent resolve."""
    md = _doc_metadata(doc)
    for key in ("chunk_id", "id", "uuid"):
        value = md.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{value}"
    file_id = str(md.get("file_id") or md.get("doc_id") or "").strip()
    if file_id and md.get("char_start") is not None:
        return f"span:{file_id}:{md.get('char_start')}:{md.get('char_end')}"
    text = _doc_text(doc)[:160]
    return f"text:{hash(text)}"


def _anchor_pos(doc: Any) -> int:
    md = _doc_metadata(doc)
    raw = md.get("anchor_pos")
    try:
        if raw is None:
            return 2_147_483_647
        return int(raw)
    except (TypeError, ValueError):
        return 2_147_483_647


def _chunk_level_rank(doc: Any) -> int:
    level = str(_doc_metadata(doc).get("chunk_level") or "").strip().lower()
    if level in {"micro", "row", "docling"}:
        return 0
    if level in {"macro", "preamble"}:
        return 2
    return 1


def _char_start_rank(doc: Any) -> int:
    try:
        return int(_doc_metadata(doc).get("char_start") or 0)
    except (TypeError, ValueError):
        return 0


def is_exact_channel_doc(doc: Any) -> bool:
    """True when metadata marks a doc from the deterministic clause channel."""
    md = _doc_metadata(doc)
    return bool(
        md.get("anchor_match") or md.get("exact_channel") or md.get("anchor_pinned")
    )


def select_pinned_clause_anchor_docs(
    docs: Sequence[Any],
    *,
    exact_query: Optional[str] = None,
    max_pins: Optional[int] = None,
) -> List[Any]:
    """
    Exact channel: top verified clause-boundary hits that bypass rerank.

    Rules:
    - Re-verify the clause heading in text (do not trust metadata alone).
    - If ``exact_query`` is set: any pool doc with a verified heading for that
      number qualifies. Downstream stages (e.g. within-file BM25) may strip
      ``anchor_match``; the boundary in text is the source of truth.
    - If ``exact_query`` is absent: only docs flagged ``anchor_match`` (and
      still looking like a clause heading) qualify.
    - Prefer flagged exact-channel docs, then earliest ``anchor_pos``, then micro.
    - Cap at ``max_pins`` (default 3).
    """
    if not docs:
        return []

    wanted = primary_exact_anchor(exact_query or "") or normalize_clause_number(exact_query or "")
    if wanted and not re.fullmatch(r"\d+(?:\.\d+)+", wanted):
        wanted = None

    limit = max_pins if isinstance(max_pins, int) and max_pins > 0 else max_clause_anchor_pins()
    candidates: List[Any] = []
    for doc in docs:
        if doc is None:
            continue
        md = _doc_metadata(doc)
        text = _doc_text(doc)
        if not text.strip():
            continue
        if wanted:
            if not text_has_clause_boundary(text, wanted):
                continue
        else:
            # No explicit exact_query: require the exact-channel flag and a
            # heading for some multi-part number near the start of the chunk.
            if not md.get("anchor_match"):
                continue
            nums = extract_clause_numbers(text[:240])
            if not nums or not text_has_clause_boundary(text, nums[0]):
                continue
        candidates.append(doc)

    candidates.sort(
        key=lambda d: (
            0 if is_exact_channel_doc(d) else 1,
            _anchor_pos(d),
            _chunk_level_rank(d),
            _char_start_rank(d),
        )
    )

    out: List[Any] = []
    seen: set[str] = set()
    for doc in candidates:
        key = clause_anchor_doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
        if len(out) >= limit:
            break
    return out


def exclude_docs_by_identity(
    docs: Sequence[Any],
    excluded: Sequence[Any],
) -> List[Any]:
    """Drop docs whose identity appears in ``excluded`` (exact channel out of rerank)."""
    ban = {clause_anchor_doc_identity(d) for d in (excluded or []) if d is not None}
    if not ban:
        return list(docs or [])
    return [
        d
        for d in (docs or [])
        if d is not None and clause_anchor_doc_identity(d) not in ban
    ]


def merge_pinned_clause_anchors(
    pinned: Sequence[Any],
    ranked: Sequence[Any],
    *,
    final_k: int,
    additive_ranked: bool = True,
) -> List[Any]:
    """
    Merge exact channel with reranked pool for the LLM.

    Exact hits always lead the list and are never dropped.

    ``additive_ranked=True`` (product default): keep all pins, then append up to
    ``final_k`` unique reranked docs (exact does not consume rerank budget).

    ``additive_ranked=False``: pins occupy priority slots inside ``final_k``.
    """
    pins = [d for d in (pinned or []) if d is not None]
    if not pins:
        return list(ranked or [])[: max(1, int(final_k or 1))] if ranked else []

    out: List[Any] = []
    seen: set[str] = set()

    for doc in pins:
        key = clause_anchor_doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        md = _doc_metadata(doc)
        md["anchor_pinned"] = True
        md["exact_channel"] = True
        try:
            doc.metadata = md
        except Exception:
            pass
        out.append(doc)

    ranked_budget = max(0, int(final_k or 0))
    if not additive_ranked:
        # Pins share the final_k budget.
        ranked_budget = max(0, max(int(final_k or 0), len(out)) - len(out))

    added = 0
    for doc in ranked or []:
        if added >= ranked_budget:
            break
        if doc is None:
            continue
        key = clause_anchor_doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
        added += 1
    return out
