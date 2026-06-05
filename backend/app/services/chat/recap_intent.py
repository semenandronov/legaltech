from __future__ import annotations

import re

_RECAP_PATTERNS = [
    r"\bповтори\b",
    r"\bповтор(и|и\s+пожалуйста|и\s+еще\s+раз)\b",
    r"\bнапомни\b",
    r"\bперескаж(и|и\s+еще\s+раз)\b",
    r"\bпро\s+то\s+дело\b",
    r"\bто\s+дело\b",
    r"\bто\s+решени[еия]\b",
    r"\bкотор(ое|ый)\s+ты\s+(приводил|упоминал|писал)\b",
    r"\bкакое\s+дело\s+ты\s+(приводил|упоминал)\b",
]

_RECAP_RE = re.compile("|".join(_RECAP_PATTERNS), re.IGNORECASE)


def is_recap_query(text: str) -> bool:
    """
    Best-effort intent heuristic.

    NOTE: This is a fallback when UI does not provide an explicit intent flag.
    The actual recap eligibility is validated against server-owned evidence in DB.
    """
    t = (text or "").strip()
    if not t:
        return False
    # Avoid triggering on very long inputs (likely a new question or pasted doc).
    if len(t) > 800:
        return False
    return bool(_RECAP_RE.search(t))

