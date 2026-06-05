"""
История диалога чата редактора документа — единый блок для Ask / Edit / Draft.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

EDITOR_MEMORY_INSTRUCTION = """ПАМЯТЬ ДИАЛОГА:
- Учитывай историю переписки ниже (если есть).
- Если пользователь пишет «его», «её», «это», «туда», «как выше», «как ты писал» — подставляй конкретные данные
  (ИНН, адрес, суммы, наименования, даты) из последних ответов ассистента в истории, не выдумывай значения."""


def message_role(msg: Any) -> Optional[str]:
    t = getattr(msg, "type", None)
    if t == "human":
        return "user"
    if t == "ai":
        return "assistant"
    if isinstance(msg, dict):
        r = msg.get("role")
        if r == "user":
            return "user"
        if r == "assistant":
            return "assistant"
    return None


def message_text(msg: Any) -> str:
    c = getattr(msg, "content", None)
    if c is None and isinstance(msg, dict):
        c = msg.get("content")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        parts = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts).strip()
    return str(c or "").strip()


def _clean_user_line(text: str) -> str:
    if "[editor_mode_hint=" in text:
        text = text.split("[editor_mode_hint=")[0].strip()
    if "[selected_text_preview]" in text:
        text = text.split("[selected_text_preview]")[0].strip()
    return text


def editor_transcript_for_prompt(
    state: Dict[str, Any],
    *,
    max_messages: int = 14,
    require_document_context: bool = True,
) -> str:
    """
    История чата редактора без текущего вопроса (он в state.question).
    """
    if require_document_context and not (state.get("document_context") or "").strip():
        return ""
    msgs = list(state.get("messages") or [])
    if len(msgs) <= 1:
        return ""
    prior = msgs[:-1][-max_messages:]
    lines: List[str] = []
    for m in prior:
        role = message_role(m)
        if role not in ("user", "assistant"):
            continue
        text = message_text(m)
        if not text:
            continue
        if role == "user":
            text = _clean_user_line(text)
        if len(text) > 2500:
            text = text[:2500] + "…"
        label = "Пользователь" if role == "user" else "Ассистент"
        lines.append(f"{label}: {text}")
    if not lines:
        return ""
    return "=== ИСТОРИЯ ДИАЛОГА В РЕДАКТОРЕ ===\n" + "\n\n".join(lines)


def editor_memory_block_for_prompt(state: Dict[str, Any], *, max_messages: int = 14) -> str:
    """История + инструкция для Edit / Draft / selection-edit."""
    hist = editor_transcript_for_prompt(state, max_messages=max_messages)
    if hist:
        return f"{hist}\n\n{EDITOR_MEMORY_INSTRUCTION}"
    return EDITOR_MEMORY_INSTRUCTION
