"""
LangGraph short-term dialog memory (messages + trim/summarize).

Shared helpers for case/global graphs: Postgres transcript is canonical;
checkpoint `messages` are hydrated and trimmed before each model turn.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.messages import trim_messages

from app.config import config
from app.services.langchain_agents.utils.message_utils import MessageManager, should_trim_messages
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def global_graph_memory_limits() -> Dict[str, int]:
    turns = max(1, int(getattr(config, "GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_TURNS", 16) or 16))
    max_tokens = max(2000, int(getattr(config, "CASE_GRAPH_MEMORY_MAX_TOKENS", 8000) or 8000))
    summarize = max(
        turns + 2,
        int(getattr(config, "GLOBAL_ASSISTANT_HISTORY_SUMMARIZE_AFTER_TURNS", 20) or 20),
    )
    return {
        "max_messages": turns * 2 + 4,
        "max_tokens": max_tokens,
        "summarize_threshold": summarize,
        "keep_last_n": turns * 2,
    }


def messages_to_chat_history(messages: Sequence[BaseMessage]) -> List[Dict[str, str]]:
    """Best-effort transcript dicts for legacy nodes that still read chat_history."""
    out: List[Dict[str, str]] = []
    for msg in messages or []:
        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        content = content.strip()
        if not content:
            continue
        if isinstance(msg, HumanMessage):
            out.append({"role": "user", "content": content})
        elif isinstance(msg, AIMessage):
            out.append({"role": "assistant", "content": content})
    return out


def format_messages_for_prompt(
    messages: Sequence[BaseMessage],
    *,
    message_summary: str = "",
    max_turns: int = 16,
    max_chars: int = 6400,
) -> str:
    """Render LangChain messages as a compact dialog block for RAG/answer prompts."""
    lines: List[str] = []
    summary = (message_summary or "").strip()
    if summary:
        lines.append(f"[Сводка раннего диалога: {summary[:4000]}]")

    dialog = list(messages or [])[-max(1, max_turns * 2) :]
    for msg in dialog:
        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        content = content.strip()
        if not content or content.startswith("[Краткое содержание"):
            continue
        if isinstance(msg, HumanMessage):
            lines.append(f"Пользователь: {content}")
        elif isinstance(msg, AIMessage):
            lines.append(f"Ассистент: {content}")

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def _simple_token_counter(msgs: Sequence[BaseMessage]) -> int:
    total = 0
    for msg in msgs:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(content) // 3
    return total


async def manage_dialog_messages(
    state: MutableMapping[str, Any],
    *,
    limits: Mapping[str, int],
) -> MutableMapping[str, Any]:
    """
    Trim/summarize state['messages'] (LangGraph add_messages + RemoveMessage pattern).
    Updates state['message_summary'] when summarization runs.
    """
    messages: List[BaseMessage] = list(state.get("messages") or [])
    summarize_threshold = int(limits.get("summarize_threshold") or 24)
    keep_last_n = int(limits.get("keep_last_n") or 12)
    max_tokens = int(limits.get("max_tokens") or 8000)
    max_messages = int(limits.get("max_messages") or 36)

    if len(messages) < summarize_threshold and not should_trim_messages(messages, max_tokens):
        return state

    logger.info("[GlobalManageMemory] processing %s messages", len(messages))

    try:
        trimmed_messages = trim_messages(
            messages,
            max_tokens=max_tokens,
            token_counter=_simple_token_counter,
            strategy="last",
            allow_partial=False,
            include_system=True,
            start_on="human",
        )

        if len(trimmed_messages) < len(messages):
            trimmed_ids = {getattr(msg, "id", None) for msg in trimmed_messages if hasattr(msg, "id")}
            remove_messages: List[RemoveMessage] = []
            for msg in messages:
                msg_id = getattr(msg, "id", None)
                if msg_id and msg_id not in trimmed_ids:
                    remove_messages.append(RemoveMessage(id=msg_id))
            if remove_messages:
                state["messages"] = remove_messages
                logger.info(
                    "[GlobalManageMemory] trim_messages %s → %s (%s removed)",
                    len(messages),
                    len(trimmed_messages),
                    len(remove_messages),
                )
                return state

        if len(messages) >= summarize_threshold:
            llm = create_legal_llm(use_rate_limiting=False, streaming=False)
            manager = MessageManager(
                llm=llm,
                max_messages=max_messages,
                max_tokens=max_tokens,
                summarize_threshold=summarize_threshold,
                keep_last_n=keep_last_n,
            )
            result = await manager.process_messages(messages)
            if result.get("trimmed"):
                if result.get("summary"):
                    state["message_summary"] = result["summary"]
                    summary_msg = SystemMessage(
                        content=f"[Краткое содержание предыдущего диалога: {result['summary']}]"
                    )
                    state["messages"] = [summary_msg] + list(result.get("messages") or [])
                else:
                    state["messages"] = list(result.get("messages") or [])
                logger.info(
                    "[GlobalManageMemory] summarized → %s messages",
                    len(state.get("messages") or []),
                )
    except Exception as exc:
        logger.warning("[GlobalManageMemory] failed: %s, keep_last_n fallback", exc)
        if len(messages) > keep_last_n:
            state["messages"] = messages[-keep_last_n:]

    return state
