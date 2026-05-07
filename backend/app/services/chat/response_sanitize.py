"""
Удаление типичных «утечек» из сырого текста ответа LLM (до разметки цитат).

Модель иногда дублирует служебный JSON answer_blocks или оборачивает его в ```json.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Начало объекта Phase 2, который никогда не должен попадать в пользовательский markdown
_BLOCKS_KEY_RE = re.compile(r"\s*\{[\s\n]*\"blocks\"[\s\n]*:", re.MULTILINE)

# Оградка ```json ... ``` если внутри есть "blocks"
_FENCED_BLOCKS_RE = re.compile(
    r"```(?:json)?\s*[\s\S]*?\"blocks\"[\s\S]*?```",
    re.IGNORECASE,
)


def _brace_end_exclusive(s: str, open_idx: int) -> int | None:
    """Индекс символа сразу после закрывающей `}` для объекта, начинающегося в open_idx, либо None."""
    depth = 0
    i = open_idx
    n = len(s)
    in_str = False
    esc = False
    q: str | None = None
    while i < n:
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif q and c == q:
                in_str = False
                q = None
            i += 1
            continue
        if c in "\"'":
            in_str = True
            q = c
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _strip_one_blocks_object(t: str) -> tuple[str, bool]:
    """Удалить один объект JSON с ключом \"blocks\" (сбалансированные скобки)."""
    m = _BLOCKS_KEY_RE.search(t)
    if not m:
        return t, False
    brace = t.find("{", m.start())
    if brace < 0:
        cut = t[: m.start()].rstrip()
        return re.sub(r"[.\s\u2014\-]+$", "", cut).rstrip(), True
    end_excl = _brace_end_exclusive(t, brace)
    if end_excl is None:
        cut = t[:brace].rstrip()
        return re.sub(r"[.\s\u2014\-]+$", "", cut).rstrip(), True
    return (t[: m.start()] + t[end_excl:]).strip(), True


def strip_llm_answer_leaks(text: str) -> str:
    """
    Вырезает из ответа ассистента случайно попавший JSON блоков / fenced-блоки.

    Возвращает исходную строку, если паттернов нет.
    """
    if not text or not isinstance(text, str):
        return (text or "").strip() if text else ""
    original_len = len(text)
    t = text
    t = _FENCED_BLOCKS_RE.sub("", t)
    changed = True
    while changed:
        t, changed = _strip_one_blocks_object(t)
    t = t.strip()
    if len(t) < original_len:
        logger.info(
            "[response_sanitize] stripped llm leak from answer (%s -> %s chars)",
            original_len,
            len(t),
        )
    return t
