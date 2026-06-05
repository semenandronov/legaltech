"""
Canonical dialog transcript helpers.

Production contract:
- Postgres session messages are the source of truth for in-dialog memory.
- LangGraph checkpoint messages are hydrated from DB on every case-assistant turn.
- Client-provided message arrays are not trusted for LLM context.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TranscriptTurn = Dict[str, str]


def _normalize_role(role: str) -> str:
    return (role or "").strip().lower()


def _normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def transcript_turns_from_role_content_pairs(
    pairs: Sequence[Tuple[str, str]],
    *,
    skip_empty_assistant: bool = True,
) -> List[TranscriptTurn]:
    """Build normalized transcript turns from (role, content) rows."""
    out: List[TranscriptTurn] = []
    for role_raw, content_raw in pairs:
        role = _normalize_role(role_raw)
        content = _normalize_content(content_raw)
        if role not in ("user", "assistant"):
            continue
        if role == "assistant" and skip_empty_assistant and not content:
            continue
        if role == "user" and not content:
            continue
        out.append({"role": role, "content": content})
    return out


def load_global_chat_history(db: Session, session_id: str) -> List[TranscriptTurn]:
    """Load global assistant transcript for a session from Postgres."""
    from app.models.case import GlobalAssistantMessage

    sid = (session_id or "").strip()
    if not sid:
        return []

    rows = (
        db.query(GlobalAssistantMessage)
        .filter(GlobalAssistantMessage.session_id == sid)
        .order_by(GlobalAssistantMessage.created_at.asc())
        .all()
    )
    return transcript_turns_from_role_content_pairs(
        [(row.role, row.content) for row in rows],
        skip_empty_assistant=True,
    )


def build_chat_history(
    transcript: Sequence[TranscriptTurn],
    pending_question: str = "",
) -> List[TranscriptTurn]:
    """
    Return chat_history dicts for global assistant, avoiding duplicate pending user turn.
    """
    history = [dict(turn) for turn in transcript if turn.get("content")]
    q = _normalize_content(pending_question)
    if not q:
        return history
    if history and history[-1].get("role") == "user" and _normalize_content(history[-1].get("content")) == q:
        return history
    return history + [{"role": "user", "content": q}]


def transcript_to_langchain_messages(
    transcript: Sequence[TranscriptTurn],
    *,
    skip_empty_assistant: bool = True,
) -> List[BaseMessage]:
    """Convert transcript turns to LangChain messages."""
    messages: List[BaseMessage] = []
    for turn in transcript:
        role = _normalize_role(turn.get("role", ""))
        content = _normalize_content(turn.get("content"))
        if role == "user" and content:
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            if content or not skip_empty_assistant:
                messages.append(AIMessage(content=content))
    return messages


def build_global_turn_messages(
    transcript: Sequence[TranscriptTurn],
    pending_question: str,
) -> List[BaseMessage]:
    """Build LangChain messages for a global-assistant graph turn from DB transcript."""
    return build_case_turn_messages(transcript, pending_question)


def build_case_turn_messages(
    transcript: Sequence[TranscriptTurn],
    pending_question: str,
) -> List[BaseMessage]:
    """
    Build LangChain messages for a case-assistant graph turn from DB transcript.

    ``pending_question`` may already be persisted as the last user row (orchestrator path).
    """
    lc_messages = transcript_to_langchain_messages(transcript, skip_empty_assistant=True)
    q = _normalize_content(pending_question)
    if not q:
        return lc_messages
    if lc_messages and isinstance(lc_messages[-1], HumanMessage):
        last_content = _normalize_content(lc_messages[-1].content)
        if last_content == q:
            return lc_messages
    return lc_messages + [HumanMessage(content=q)]


def reconcile_langchain_messages(
    checkpoint_messages: Optional[Sequence[BaseMessage]],
    canonical_messages: Sequence[BaseMessage],
) -> Tuple[List[BaseMessage], bool]:
    """
    Prefer canonical DB transcript over checkpoint messages.

    Returns:
        (messages, replaced_checkpoint)
    """
    canonical = list(canonical_messages)
    if not checkpoint_messages:
        return canonical, bool(canonical)

    def _signature(messages: Sequence[BaseMessage]) -> List[Tuple[str, str]]:
        sig: List[Tuple[str, str]] = []
        for msg in messages:
            role = "assistant" if isinstance(msg, AIMessage) else "user"
            sig.append((role, _normalize_content(msg.content)))
        return sig

    checkpoint_sig = _signature(checkpoint_messages)
    canonical_sig = _signature(canonical)
    if checkpoint_sig == canonical_sig:
        return canonical, False

    logger.info(
        "[DialogTranscript] Replacing checkpoint messages with DB transcript "
        "(checkpoint_turns=%s db_turns=%s)",
        len(checkpoint_sig),
        len(canonical_sig),
    )
    return canonical, True


def count_transcript_turns(transcript: Sequence[TranscriptTurn]) -> int:
    return len([t for t in transcript if _normalize_content(t.get("content"))])
