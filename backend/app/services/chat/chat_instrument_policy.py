"""Совместимость режима чата и инструментов (справочник / судебная практика / draft)."""
from __future__ import annotations


def normalize_chat_instrument_flags(
    *,
    draft_mode: bool,
    legal_research: bool = False,
    use_legal_corpus: bool = False,
    court_practice: bool = False,
) -> tuple[bool, bool, bool]:
    """
    Draft взаимоисключающий со справочником и судебной практикой.
    Справочник и судебная практика взаимоисключают друг друга:
    если включены оба режима, приоритет у судебной практики.

    Returns:
        (draft_mode, legal_research_effective, court_practice_effective)
    """
    draft = bool(draft_mode)
    legal = bool(legal_research or use_legal_corpus)
    practice = bool(court_practice)
    if draft:
        legal = False
        practice = False
    # Взаимоисключение инструментов: практика приоритетнее справочника.
    if practice and legal:
        legal = False
    return draft, legal, practice


def normalize_editor_mode_for_legal_research(
    mode_hint: str | None,
    *,
    legal_research: bool,
    court_practice: bool = False,
) -> str:
    """При справочнике или судебной практике в редакторе — только ask."""
    mode = (mode_hint or "ask").strip().lower()
    if mode not in ("ask", "edit", "draft"):
        mode = "ask"
    if legal_research or court_practice:
        return "ask"
    return mode
