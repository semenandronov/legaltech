"""
Step 0: resolve deictic / underspecified questions into standalone retrieval queries.

Runs before intent classification. Code-first (no LLM) — uses dialog history and
optional anchor filenames from prior citations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_DATE_RE = re.compile(r"\d{2}[./]\d{2}[./]\d{2,4}")
_DOC_LABEL_RE = re.compile(
    r"(?:договор|контракт|иск(?:овое)?\s+заявлен\w*|заявлен\w*|акт|протокол|решени\w*|определени\w*|возражени\w*)"
    r"(?:\s+№?\s*[\w./\-]+)?(?:\s+от\s+\d{2}[./]\d{2}[./]\d{2,4})?",
    re.IGNORECASE,
)
_DEICTIC_NEED_RESOLVE_RE = re.compile(
    r"(?:"
    r"\b(?:этот|этого|этом|эта|это|тот|того|том|та|то|там|него|неё|нее|него)\b"
    r"|\bподробнее\b"
    r"|\bещё\b|\bеще\b"
    r"|\bвыше\b|\bранее\b"
    r")",
    re.IGNORECASE,
)
_FILENAME_RE = re.compile(
    r"([А-ЯA-Za-z0-9_\-\.]+\.(?:pdf|docx?|rtf|txt))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StandaloneQueryResult:
    original_question: str
    resolved_question: str
    reason: str
    changed: bool


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _extract_doc_labels_from_text(text: str) -> List[str]:
    out: List[str] = []
    for m in _DOC_LABEL_RE.finditer(text or ""):
        label = _normalize_ws(m.group(0))
        if label and label not in out:
            out.append(label)
    return out


def _extract_filenames_from_text(text: str) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for m in _FILENAME_RE.finditer(text or ""):
        name = m.group(1).strip()
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def needs_standalone_resolution(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if not _DEICTIC_NEED_RESOLVE_RE.search(q):
        return False
    if _DOC_LABEL_RE.search(q) and _DATE_RE.search(q):
        return False
    return True


def resolve_standalone_query(
    question: str,
    *,
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Optional[Sequence[str]] = None,
) -> StandaloneQueryResult:
    """
    Produce a self-contained query for intent routing and retrieval.

    Does not call LLM — enriches from recent dialog text and citation anchors.
    """
    original = (question or "").strip()
    if not original or not needs_standalone_resolution(original):
        return StandaloneQueryResult(
            original_question=original,
            resolved_question=original,
            reason="explicit_or_no_deictic",
            changed=False,
        )

    context_parts: List[str] = []
    if (conversation_summary or "").strip():
        context_parts.append(conversation_summary.strip())
    if (dialog_history or "").strip():
        context_parts.append(dialog_history.strip())

    combined = "\n".join(context_parts)
    doc_labels = _extract_doc_labels_from_text(combined)
    filenames = list(anchor_filenames or []) + _extract_filenames_from_text(combined)

    resolved = original
    reason = "unresolved_deictic"

    if doc_labels:
        anchor = doc_labels[-1]
        if _DEICTIC_NEED_RESOLVE_RE.search(resolved):
            if re.search(r"\b(?:договор|контракт|документ|файл)\b", resolved, re.I):
                resolved = re.sub(
                    r"\b(?:этот|этого|этом|эта|тот|того|том|та)\s+(?:договор|контракт|документ|файл)\b",
                    anchor,
                    resolved,
                    count=1,
                    flags=re.IGNORECASE,
                )
                reason = "substituted_doc_label_from_history"
            elif re.search(r"\bподробнее\b", resolved, re.I):
                anchor_l = anchor.lower()
                if anchor_l not in resolved.lower():
                    resolved = f"{resolved.rstrip('?.! ')} ({anchor})"
                else:
                    date_m = _DATE_RE.search(anchor)
                    if date_m and date_m.group(0) not in resolved:
                        resolved = f"{resolved.rstrip('?.! ')} от {date_m.group(0)}"
                reason = "appended_doc_label_for_drill_down"
            elif re.search(r"\b(?:там|него|неё|нее|него|этом)\b", resolved, re.I):
                resolved = f"{resolved.rstrip('?.! ')} ({anchor})"
                reason = "appended_doc_label_parenthetical"

    if filenames and reason == "unresolved_deictic":
        fname = filenames[-1]
        human = re.sub(r"[_\-]+", " ", re.sub(r"\.(pdf|docx?|rtf|txt)$", "", fname, flags=re.I))
        resolved = f"{resolved.rstrip('?.! ')} ({human.strip()})"
        reason = "appended_filename_from_history"

    resolved = _normalize_ws(resolved)
    changed = resolved.lower() != original.lower()
    return StandaloneQueryResult(
        original_question=original,
        resolved_question=resolved if changed else original,
        reason=reason if changed else "explicit_or_no_deictic",
        changed=changed,
    )
