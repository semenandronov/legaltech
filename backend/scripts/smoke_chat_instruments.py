#!/usr/bin/env python3
"""Smoke-test case assistant: legal_research vs court_practice (SSE)."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _pick_case_and_token():
    from datetime import datetime, timedelta

    from sqlalchemy import desc

    from app.config import config
    from app.models.case import Case
    from app.models.user import User, UserSession
    from app.utils.auth import create_access_token, create_refresh_token
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        case = (
            db.query(Case)
            .filter(Case.num_documents > 0)
            .order_by(desc(Case.updated_at))
            .first()
        )
        if not case:
            case = db.query(Case).order_by(desc(Case.updated_at)).first()
        if not case:
            raise RuntimeError("No cases in DB")
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            raise RuntimeError(f"No user for case {case.id}")
        access_token = create_access_token(data={"sub": user.id})
        refresh_token = create_refresh_token(data={"sub": user.id})
        expires_at = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
        session = (
            db.query(UserSession)
            .filter(UserSession.user_id == user.id, UserSession.is_active == True)
            .first()
        )
        if session:
            session.token = access_token
            session.refresh_token = refresh_token
            session.expires_at = expires_at
            session.last_used_at = datetime.utcnow()
        else:
            db.add(
                UserSession(
                    user_id=user.id,
                    token=access_token,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    is_active=True,
                )
            )
        db.commit()
        return str(case.id), access_token, user.email
    finally:
        db.close()


def _parse_sse(body: str) -> dict:
    types: list[str] = []
    text_parts: list[str] = []
    errors: list[str] = []
    phases: list[str] = []
    citations_n = 0
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        t = obj.get("type") or ""
        types.append(t)
        if t in ("text_delta", "text-delta"):
            text_parts.append(
                str(obj.get("textDelta") or obj.get("text_delta") or obj.get("content") or obj.get("text") or "")
            )
        elif t == "error":
            errors.append(str(obj.get("message") or obj))
        elif t == "status":
            ph = obj.get("phase") or obj.get("status") or ""
            if ph:
                phases.append(str(ph))
        elif t == "citations":
            c = obj.get("citations") or []
            if isinstance(c, list):
                citations_n = len(c)
    return {
        "event_types": types,
        "answer_chars": len("".join(text_parts)),
        "answer_preview": ("".join(text_parts))[:400],
        "errors": errors,
        "phases": phases[-8:],
        "citations_count": citations_n,
        "has_finish": "finish" in types,
    }


def run_mode(
    *,
    base_url: str,
    case_id: str,
    token: str,
    legal_research: bool,
    court_practice: bool,
    question: str,
    timeout_sec: float,
) -> dict:
    session_id = str(uuid.uuid4())
    body = {
        "case_id": case_id,
        "messages": [{"role": "user", "content": question}],
        "session_id": session_id,
        "legal_research": legal_research,
        "use_legal_corpus": legal_research,
        "court_practice": court_practice,
        "draft_mode": False,
        "web_search": False,
        "deep_think": False,
    }
    label = []
    if legal_research:
        label.append("spravochnik")
    if court_practice:
        label.append("court_practice")
    mode_label = "+".join(label) or "baseline"

    t0 = time.monotonic()
    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(
            f"{base_url}/api/v2/assistant/chat",
            headers={
                "Content-Type": "application/json",
                "X-Access-Token": token,
            },
            json=body,
        )
    wall_ms = int((time.monotonic() - t0) * 1000)
    parsed = _parse_sse(resp.text) if resp.status_code == 200 else {}
    return {
        "mode": mode_label,
        "http_status": resp.status_code,
        "wall_ms": wall_ms,
        "session_id": session_id,
        **parsed,
        "http_body_preview": (resp.text[:500] if resp.status_code != 200 else ""),
    }


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    timeout_sec = float(sys.argv[2] if len(sys.argv) > 2 else "240")

    # Health
    try:
        httpx.get(f"{base_url}/docs", timeout=5.0)
    except Exception as exc:
        print(f"FAIL: server not reachable at {base_url}: {exc}")
        return 1

    case_id, token, email = _pick_case_and_token()
    print(f"case_id={case_id} user={email} timeout={timeout_sec}s")

    question_sprav = (
        "Какие сроки оспаривания подозрительных сделок должника по 127-ФЗ? "
        "Кратко со ссылкой на нормы из справочника."
    )
    question_cp = (
        "Найди судебную практику по оспариванию сделок должника в банкротстве. "
        "Дай 2–3 карточки дел с номерами."
    )

    runs = [
        ("Справочник", dict(legal_research=True, court_practice=False, question=question_sprav)),
        ("Суд. практика", dict(legal_research=False, court_practice=True, question=question_cp)),
    ]

    ok = True
    for title, kwargs in runs:
        print(f"\n=== {title} ===")
        try:
            result = run_mode(
                base_url=base_url,
                case_id=case_id,
                token=token,
                timeout_sec=timeout_sec,
                **kwargs,
            )
        except httpx.TimeoutException:
            print(f"TIMEOUT after {timeout_sec}s")
            ok = False
            continue
        except Exception as exc:
            print(f"ERROR: {exc}")
            ok = False
            continue

        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("http_status") != 200:
            ok = False
        elif result.get("answer_chars", 0) < 20 and not result.get("errors"):
            print("WARN: empty or tiny answer")
            ok = False
        elif result.get("errors"):
            ok = False

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
