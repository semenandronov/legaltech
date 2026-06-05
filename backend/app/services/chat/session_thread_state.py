"""
Persistent thread state for one chat session (always-on narrative thread).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.session_context_types import Scope, SessionMessageTurn
from app.services.chat.session_transcript import turns_to_resolver_transcript
from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import get_langchain_callbacks
from app.utils.database import engine as _shared_engine

logger = logging.getLogger(__name__)

_schema_lock = threading.Lock()
_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        try:
            with _shared_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS chat_session_context (
                            scope VARCHAR(16) NOT NULL,
                            session_key VARCHAR(512) NOT NULL,
                            thread_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                            conversation_summary TEXT,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (scope, session_key)
                        )
                        """
                    )
                )
            _schema_ready = True
        except Exception as exc:
            logger.warning("chat_session_context schema ensure failed: %s", exc)


def load_session_thread(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
) -> Tuple[Dict[str, Any], str]:
    sk = (session_key or "").strip()
    if not sk:
        return {}, ""
    _ensure_schema()
    try:
        row = db.execute(
            text(
                """
                SELECT thread_state, conversation_summary
                FROM chat_session_context
                WHERE scope = :scope AND session_key = :session_key
                """
            ),
            {"scope": scope, "session_key": sk},
        ).fetchone()
        if not row:
            return {}, ""
        state = row[0] if isinstance(row[0], dict) else {}
        if isinstance(row[0], str):
            try:
                state = json.loads(row[0])
            except Exception:
                state = {}
        summary = (row[1] or "").strip() if row[1] else ""
        return state if isinstance(state, dict) else {}, summary
    except Exception as exc:
        logger.debug("load_session_thread failed: %s", exc)
        return {}, ""


def save_session_thread(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    thread_state: Dict[str, Any],
    conversation_summary: str = "",
) -> None:
    sk = (session_key or "").strip()
    if not sk:
        return
    _ensure_schema()
    try:
        db.execute(
            text(
                """
                INSERT INTO chat_session_context (
                    scope, session_key, thread_state, conversation_summary, updated_at
                ) VALUES (
                    :scope, :session_key, CAST(:thread_state AS jsonb),
                    :conversation_summary, NOW()
                )
                ON CONFLICT (scope, session_key) DO UPDATE SET
                    thread_state = EXCLUDED.thread_state,
                    conversation_summary = EXCLUDED.conversation_summary,
                    updated_at = NOW()
                """
            ),
            {
                "scope": scope,
                "session_key": sk,
                "thread_state": json.dumps(thread_state or {}, ensure_ascii=False),
                "conversation_summary": (conversation_summary or "")[:8000],
            },
        )
        db.flush()
    except Exception as exc:
        logger.warning("save_session_thread failed: %s", exc)


def _heuristic_thread_state(turns: List[SessionMessageTurn]) -> Dict[str, Any]:
    """Cheap fallback when LLM update is off or fails."""
    topics: List[str] = []
    entities: List[str] = []
    last_user = ""
    last_assistant = ""
    for t in turns[-6:]:
        if (t.role or "").lower() == "user":
            last_user = t.content[:500]
        else:
            last_assistant = t.content[:500]
    for t in reversed(turns):
        if (t.role or "").lower() == "user" and t.content:
            snippet = t.content[:120].strip()
            if snippet and snippet not in topics:
                topics.insert(0, snippet)
            if len(topics) >= 3:
                break
    return {
        "topics": topics,
        "entities": entities,
        "last_user_question": last_user,
        "last_assistant_summary": (last_assistant or "")[:400],
        "open_questions": [],
    }


def update_thread_state_after_turn(
    db: Session,
    *,
    scope: Scope,
    session_key: str,
    turns: List[SessionMessageTurn],
    last_user: str,
    last_assistant: str,
) -> Tuple[Dict[str, Any], str]:
    """
    Refresh thread_state + conversation_summary after an assistant turn completes.
    """
    prev_state, prev_summary = load_session_thread(db, scope=scope, session_key=session_key)
    if not getattr(config, "SESSION_CONTEXT_THREAD_STATE_LLM_ENABLED", True):
        state = _heuristic_thread_state(turns)
        save_session_thread(db, scope=scope, session_key=session_key, thread_state=state, conversation_summary=prev_summary)
        return state, prev_summary

    transcript = turns_to_resolver_transcript(turns, max_turns=14)
    llm = create_legal_llm(use_rate_limiting=False, temperature=0.0, max_tokens=900)
    callbacks = get_langchain_callbacks(tags=["assistant", "session_context", "thread_state"])
    prompt = (
        "Ты ведёшь краткую «нить разговора» для юридического ассистента в ОДНОМ чате.\n"
        "По транскрипту и последнему обмену обнови JSON (только JSON, без markdown):\n"
        "{\n"
        '  "topic": "главная тема одной фразой",\n'
        '  "subtopics": ["..."],\n'
        '  "entities": ["сущности: дела, стороны, нормы, документы"],\n'
        '  "constraints": ["ограничения пользователя: только ВС, без советов, и т.п."],\n'
        '  "last_user_intent": "что хотел пользователь в последнем вопросе",\n'
        '  "last_assistant_point": "кратко что ответил ассистент",\n'
        '  "open_questions": ["что осталось неясным"],\n'
        '  "conversation_summary": "сжатая сводка всего диалога до 1200 символов"\n'
        "}\n"
        "Не добавляй факты, которых нет в транскрипте.\n\n"
        f"Предыдущее состояние:\n{json.dumps(prev_state, ensure_ascii=False)[:3000]}\n\n"
        f"Предыдущая сводка:\n{prev_summary or '[нет]'}\n\n"
        f"Транскрипт:\n{transcript}\n\n"
        f"Последний вопрос пользователя:\n{last_user[:2000]}\n\n"
        f"Последний ответ ассистента:\n{last_assistant[:4000]}\n"
    )
    try:
        raw = llm.invoke(
            [HumanMessage(content=prompt)],
            config={"callbacks": callbacks} if callbacks else None,
        )
        content = raw.content if hasattr(raw, "content") else str(raw)
        parsed = _parse_json_object(content)
        if not parsed:
            state = _heuristic_thread_state(turns)
            save_session_thread(db, scope=scope, session_key=session_key, thread_state=state, conversation_summary=prev_summary)
            return state, prev_summary
        summary = str(parsed.pop("conversation_summary", "") or prev_summary).strip()[:4000]
        save_session_thread(
            db,
            scope=scope,
            session_key=session_key,
            thread_state=parsed,
            conversation_summary=summary,
        )
        return parsed, summary
    except Exception as exc:
        logger.debug("thread state LLM update failed: %s", exc)
        state = _heuristic_thread_state(turns)
        save_session_thread(db, scope=scope, session_key=session_key, thread_state=state, conversation_summary=prev_summary)
        return state, prev_summary


def format_thread_state_block(thread_state: Dict[str, Any], conversation_summary: str) -> str:
    """Always injected into prompts — not trigger-based."""
    parts: List[str] = []
    if conversation_summary:
        parts.append(f"Сводка диалога:\n{conversation_summary}")
    if thread_state:
        topic = thread_state.get("topic") or thread_state.get("main_topic")
        if topic:
            parts.append(f"Тема: {topic}")
        for key, label in (
            ("subtopics", "Подтемы"),
            ("entities", "Сущности"),
            ("constraints", "Ограничения"),
            ("last_user_intent", "Последний запрос"),
            ("last_assistant_point", "Последний ответ"),
            ("open_questions", "Открытые вопросы"),
        ):
            val = thread_state.get(key)
            if isinstance(val, list) and val:
                parts.append(f"{label}: {', '.join(str(x) for x in val[:8])}")
            elif isinstance(val, str) and val.strip():
                parts.append(f"{label}: {val.strip()}")
    if not parts:
        return ""
    return "=== НИТЬ РАЗГОВОРА (сессия) ===\n" + "\n".join(parts)


def _parse_json_object(text_in: str) -> Optional[Dict[str, Any]]:
    raw = (text_in or "").strip()
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
