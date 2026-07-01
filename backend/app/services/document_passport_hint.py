"""Lightweight doc_type hints for passport generation (no LLM).

The passport graph determines the final document type from content.
Filename hints only nudge the model when the name is descriptive.
"""

from __future__ import annotations

# Order matters: more specific phrases before shorter substrings.
_FILENAME_HINTS: tuple[tuple[str, str], ...] = (
    ("возражен", "возражение"),
    ("ходатайств", "ходатайство"),
    ("претенз", "претензия"),
    ("жалоб", "жалоба"),
    ("отзыв", "отзыв"),
    ("договор", "договор"),
    ("соглашен", "договор"),
    ("акт сверки", "акт"),
    ("акт ", "акт"),
    ("исков", "иск"),
    (" иск", "иск"),
    ("иск.", "иск"),
)


def infer_doc_type_hint_from_filename(filename: str) -> str:
    """Return a soft doc_type hint from filename, default ``прочее``."""
    name = (filename or "").strip().lower()
    if not name:
        return "прочее"
    for keyword, doc_type in _FILENAME_HINTS:
        if keyword in name:
            return doc_type
    return "прочее"
