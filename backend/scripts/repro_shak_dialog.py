#!/usr/bin/env python3
"""Reproduce case-assistant dialog: SQL follow-up + RAG objection drill-down."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

CASE_ID = "c7d6af43-d744-4037-9125-97c616796555"

DIALOG = [
    "выписка из т-банка! там сколько операции в июне 2026?",
    "а в мае 2026",
    "о чем возражение шашиошвили",
    "подробнее про возражение",
]


def _parse_sse(events: list[str]) -> dict:
    text_parts: list[str] = []
    citations: list = []
    turn_state: dict | None = None
    session_id = ""
    for raw in events:
        if not raw.startswith("data: "):
            continue
        try:
            payload = json.loads(raw.replace("data: ", "", 1).strip())
        except json.JSONDecodeError:
            continue
        t = payload.get("type")
        if t == "text-delta":
            text_parts.append(str(payload.get("textDelta") or ""))
        elif t == "citations":
            citations = list(payload.get("citations") or [])
        elif t == "turn_state":
            ts = payload.get("turn_state")
            if isinstance(ts, dict):
                turn_state = ts
        elif t == "session":
            session_id = str(payload.get("sessionId") or payload.get("session_id") or "")
    return {
        "response": "".join(text_parts).strip(),
        "citations": citations,
        "turn_state": turn_state,
        "session_id": session_id,
    }


async def main() -> int:
    from app import config as app_config
    from app.models.case import Case
    from app.models.user import User
    from app.services.chat import ChatRequest
    from app.services.chat.case_chat_request_prep import CaseChatPrepParams, prepare_case_chat_request
    from app.services.chat.history_service import ChatHistoryService
    from app.services.chat.orchestrator import ChatOrchestrator
    from app.utils.database import SessionLocal

    app_config.config.CASE_TRANSACTION_AGENT_ENABLED = True

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == CASE_ID).first()
        if not case:
            print(f"ERROR: case {CASE_ID} not found")
            return 1
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            print("ERROR: case owner not found")
            return 1

        session_id = str(uuid.uuid4())
        orchestrator = ChatOrchestrator(db=db)
        hist = ChatHistoryService(db)

        print(f"case_id={CASE_ID} user={user.email} session={session_id}\n")

        for i, question in enumerate(DIALOG, 1):
            print("=" * 72)
            print(f"[{i}] USER: {question}")

            prep = prepare_case_chat_request(
                db,
                CaseChatPrepParams(
                    case_id=CASE_ID,
                    question=question,
                    current_user=user,
                    session_id=session_id,
                ),
            )
            req = prep.chat_request
            req.session_id = session_id
            tc = prep.turn_context_dict or {}
            router_meta = req.structured_data_router_meta or {}
            bp = req.budget_profile or {}
            ec = bp.get("execution_contract") or {}

            print(
                f"  PREP: plane={req.structured_data_plane} "
                f"need={bp.get('information_need')} "
                f"referential={tc.get('referential_kind')} "
                f"standalone={str(tc.get('standalone_query') or '')[:80]}"
            )
            print(
                f"  ROUTER: {router_meta.get('data_plane')} "
                f"resolver={router_meta.get('resolver')} "
                f"need={router_meta.get('information_need')}"
            )
            if ec:
                print(
                    f"  CONTRACT: need={ec.get('information_need')} "
                    f"hints={ec.get('sql_plan_hints')} "
                    f"prior_domain={(ec.get('prior_turn_state') or {}).get('domain')}"
                )

            events: list[str] = []
            async for ev in orchestrator.process_request(req):
                events.append(ev)

            parsed = _parse_sse(events)
            if parsed.get("session_id"):
                session_id = parsed["session_id"]

            answer = parsed["response"][:500]
            print(f"  ASSISTANT: {answer}")
            print(f"  citations={len(parsed['citations'])} turn_state={parsed.get('turn_state')}")

            # DB state after turn
            recent = hist.get_session_history(case_id=CASE_ID, session_id=session_id, limit=4)
            last_asst = next((m for m in reversed(recent or []) if m.role == "assistant"), None)
            if last_asst:
                ev = getattr(last_asst, "evidence", None) or {}
                meta = (ev.get("retrieval_metadata") or {}) if isinstance(ev, dict) else {}
                ts_db = meta.get("turn_state")
                cit_count = len(ev.get("citations") or []) if isinstance(ev, dict) else 0
                print(f"  DB evidence: citations={cit_count} turn_state_domain={(ts_db or {}).get('domain') if isinstance(ts_db, dict) else None}")
                refs = getattr(last_asst, "source_references", None)
                if refs and cit_count == 0:
                    print(f"  DB source_references type={type(refs).__name__} (citations only in refs?)")

            if i == 4 and ("Контекст не найден" in answer or "материалы дела отсутствуют" in answer.lower()):
                print("\n>>> REPRODUCED FAILURE on turn 4")
                if last_asst:
                    print(f"  full evidence keys: {list(ev.keys()) if isinstance(ev, dict) else ev}")
                    print(f"  turn_context: {json.dumps(tc, ensure_ascii=False)[:400]}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
