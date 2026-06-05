"""
Reference resolution for in-session follow-ups (server-owned evidence).

Production contract:
- Memory inside one chat == one stable session_id.
- Follow-ups resolve to prior assistant turns that have persisted evidence bundles.
- No re-retrieval and no "remembering from model weights" when instruments are off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, Sequence, Set

from app.services.chat.recap_intent import is_recap_query
from app.services.court_practice_text import extract_case_numbers

# Deictic / ordinal references to prior assistant output in the same session.
_DEICTIC_PATTERNS = [
    r"\bто\s+дело\b",
    r"\bтом\s+деле\b",
    r"\bэтом\s+деле\b",
    r"\bэто\s+дело\b",
    r"\bтот\s+кейс\b",
    r"\bэтот\s+кейс\b",
    r"\bпро\s+него\b",
    r"\bпро\s+неё\b",
    r"\bпро\s+нее\b",
    r"\bоб\s+этом\s+деле\b",
    r"\bв\s+этом\s+деле\b",
    r"\bкотор(ое|ый)\s+ты\s+(приводил|упоминал|писал|показывал)\b",
    r"\bкакое\s+дело\s+ты\s+(приводил|упоминал|показывал)\b",
    r"\bиз\s+твоего\s+(ответа|подборки)\b",
    r"\bв\s+прошлом\s+ответе\b",
    r"\bв\s+предыдущем\s+ответе\b",
]
_DEICTIC_RE = re.compile("|".join(_DEICTIC_PATTERNS), re.IGNORECASE)

_ORDINAL_CASE_RE = re.compile(
    r"\b("
    r"перв(ое|ый|ую)\s+дело|"
    r"втор(ое|ой|ую)\s+дело|"
    r"трет(ье|ье|е)\s+дело|"
    r"1[\-\s]?е\s+дело|"
    r"2[\-\s]?е\s+дело|"
    r"3[\-\s]?е\s+дело|"
    r"дело\s+№?\s*1\b|"
    r"дело\s+№?\s*2\b|"
    r"дело\s+№?\s*3\b"
    r")\b",
    re.IGNORECASE,
)

# Short message that is only a case number (or case number + punctuation).
_CASE_ONLY_RE = re.compile(
    r"^\s*([АAВBСCЕEНHКKМMОOРPТTУUXХ]\d{1,2}-\d{2,7}/\d{2,4}(?:\(\d+\))?)\s*[\.\!\?]?\s*$",
    re.IGNORECASE,
)


class ReferenceKind(str, Enum):
    NONE = "none"
    EXPLICIT_RECAP = "explicit_recap"
    CASE_NUMBER = "case_number"
    DEICTIC = "deictic"
    ORDINAL_CASE = "ordinal_case"


@dataclass(frozen=True)
class ReferenceIntent:
    """Classified user intent for session evidence resolution."""

    kind: ReferenceKind
    case_numbers: tuple[str, ...] = ()
    ordinal_index: Optional[int] = None  # 0-based into last assistant evidence.case_numbers

    @property
    def should_resolve(self) -> bool:
        return self.kind is not ReferenceKind.NONE


def _normalize_case_number(raw: str) -> str:
    nums = extract_case_numbers(raw or "")
    return nums[0] if nums else (raw or "").strip().upper()


def extract_referenced_case_numbers(text: str) -> List[str]:
    """Case numbers explicitly mentioned in the user message."""
    return extract_case_numbers(text or "")


def is_deictic_reference(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 800:
        return False
    return bool(_DEICTIC_RE.search(t))


def _parse_ordinal_index(text: str) -> Optional[int]:
    t = (text or "").lower()
    if re.search(r"\bперв|1[\-\s]?е\s+дело|дело\s+№?\s*1\b", t):
        return 0
    if re.search(r"\bвтор|2[\-\s]?е\s+дело|дело\s+№?\s*2\b", t):
        return 1
    if re.search(r"\bтрет|3[\-\s]?е\s+дело|дело\s+№?\s*3\b", t):
        return 2
    return None


def classify_reference_intent(question: str) -> ReferenceIntent:
    """
    Decide whether the user message is a referential follow-up within the session.
    """
    t = (question or "").strip()
    if not t:
        return ReferenceIntent(kind=ReferenceKind.NONE)

    if len(t) > 1200:
        # Long pasted text: treat as a new task unless explicit recap phrase appears early.
        if not is_recap_query(t[:400]):
            return ReferenceIntent(kind=ReferenceKind.NONE)

    case_nums = tuple(extract_referenced_case_numbers(t))
    if case_nums and (_CASE_ONLY_RE.match(t) or len(t) <= 64):
        return ReferenceIntent(kind=ReferenceKind.CASE_NUMBER, case_numbers=case_nums)

    if is_recap_query(t):
        if case_nums:
            return ReferenceIntent(kind=ReferenceKind.CASE_NUMBER, case_numbers=case_nums)
        return ReferenceIntent(kind=ReferenceKind.EXPLICIT_RECAP)

    ordinal = _parse_ordinal_index(t)
    if ordinal is not None and (_ORDINAL_CASE_RE.search(t) or "дело" in t.lower()):
        return ReferenceIntent(kind=ReferenceKind.ORDINAL_CASE, ordinal_index=ordinal)

    if is_deictic_reference(t):
        if case_nums:
            return ReferenceIntent(kind=ReferenceKind.CASE_NUMBER, case_numbers=case_nums)
        return ReferenceIntent(kind=ReferenceKind.DEICTIC)

    # "А19-23660/2017 — а что с презумпцией?" still contains a case anchor.
    if case_nums and len(t) <= 280:
        return ReferenceIntent(kind=ReferenceKind.CASE_NUMBER, case_numbers=case_nums)

    return ReferenceIntent(kind=ReferenceKind.NONE)


def evidence_case_numbers(evidence: Any) -> List[str]:
    """Normalized case numbers from a persisted evidence bundle."""
    if not evidence or not isinstance(evidence, dict):
        return []
    raw = evidence.get("case_numbers")
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen: Set[str] = set()
    for item in raw:
        for cn in extract_case_numbers(str(item)):
            if cn not in seen:
                seen.add(cn)
                out.append(cn)
    return out


def evidence_matches_case_numbers(
    evidence: Any,
    *,
    targets: Sequence[str],
    content: str = "",
) -> bool:
    """True if evidence bundle or message content is anchored to any target case number."""
    if not targets:
        return False
    target_set = {_normalize_case_number(t) for t in targets if t}
    target_set = {t for t in target_set if t}
    if not target_set:
        return False

    stored = set(evidence_case_numbers(evidence))
    if target_set & stored:
        return True

    content_norm = (content or "").upper()
    for t in target_set:
        if t and t in content_norm:
            return True
        # Also match with Latin A vs Cyrillic А normalization via extract_case_numbers.
        for found in extract_case_numbers(content or ""):
            if found == t:
                return True
    return False


def pick_case_number_for_ordinal(
    evidence: Any,
    *,
    ordinal_index: int,
) -> Optional[str]:
    """Pick Nth case number from the last evidence bundle ordering."""
    nums = evidence_case_numbers(evidence)
    if not nums:
        return None
    if ordinal_index < 0 or ordinal_index >= len(nums):
        return None
    return nums[ordinal_index]
