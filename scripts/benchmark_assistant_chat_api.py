#!/usr/bin/env python3
"""End-to-end benchmark: POST /api/v2/assistant/chat (full case assistant path)."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_CASE_ID = "bde0a4a1-7ebd-43e0-bebd-5308b852d910"
DEFAULT_QUESTION = "о чем выписка егрюл"


def _auth_for_case(case_id: str) -> tuple[str, str]:
    from datetime import datetime, timedelta

    from app.config import config
    from app.models.case import Case
    from app.models.user import User, UserSession
    from app.utils.auth import create_access_token, create_refresh_token
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise RuntimeError(f"Case not found: {case_id}")
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            raise RuntimeError(f"No user for case {case_id}")
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
        return access_token, user.email or str(user.id)
    finally:
        db.close()


def _stream_chat(
    *,
    base_url: str,
    case_id: str,
    token: str,
    question: str,
    timeout_sec: float,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    body = {
        "case_id": case_id,
        "messages": [{"role": "user", "content": question}],
        "session_id": session_id,
        "draft_mode": False,
        "web_search": False,
        "legal_research": False,
        "court_practice": False,
        "deep_think": False,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Access-Token": token,
    }

    t0 = time.perf_counter()
    first_byte_ms: Optional[float] = None
    first_text_ms: Optional[float] = None
    finish_ms: Optional[float] = None
    phases: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    errors: List[str] = []
    citations_n = 0
    http_status = 0

    with httpx.Client(timeout=timeout_sec) as client:
        with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/api/v2/assistant/chat",
            headers=headers,
            json=body,
        ) as resp:
            http_status = resp.status_code
            for line in resp.iter_lines():
                if first_byte_ms is None and line:
                    first_byte_ms = (time.perf_counter() - t0) * 1000
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                now_ms = (time.perf_counter() - t0) * 1000
                ev_type = str(obj.get("type") or "")
                if ev_type == "status":
                    phase = obj.get("phase") or obj.get("status")
                    if phase:
                        phases.append({"ms": round(now_ms, 1), "phase": str(phase)})
                elif ev_type in ("text_delta", "text-delta"):
                    chunk = str(
                        obj.get("textDelta")
                        or obj.get("text_delta")
                        or obj.get("content")
                        or obj.get("text")
                        or ""
                    )
                    if chunk and first_text_ms is None:
                        first_text_ms = now_ms
                    text_parts.append(chunk)
                elif ev_type == "citations":
                    c = obj.get("citations") or []
                    if isinstance(c, list):
                        citations_n = len(c)
                elif ev_type == "error":
                    errors.append(str(obj.get("message") or obj))
                elif ev_type == "finish":
                    finish_ms = now_ms

    total_ms = (time.perf_counter() - t0) * 1000
    answer = "".join(text_parts)
    return {
        "session_id": session_id,
        "http_status": http_status,
        "total_ms": round(total_ms, 1),
        "first_byte_ms": round(first_byte_ms, 1) if first_byte_ms is not None else None,
        "first_text_ms": round(first_text_ms, 1) if first_text_ms is not None else None,
        "finish_event_ms": round(finish_ms, 1) if finish_ms is not None else None,
        "phases": phases,
        "answer_chars": len(answer),
        "answer_preview": answer[:350],
        "citations_count": citations_n,
        "errors": errors,
    }


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    case_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CASE_ID
    question = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_QUESTION
    runs = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    timeout_sec = float(sys.argv[5]) if len(sys.argv) > 5 else 300.0

    try:
        httpx.get(f"{base_url.rstrip('/')}/docs", timeout=5.0)
    except Exception as exc:
        print(f"FAIL: server not reachable at {base_url}: {exc}")
        return 1

    token, email = _auth_for_case(case_id)
    print("=== Full assistant API benchmark ===")
    print(f"URL: {base_url}/api/v2/assistant/chat")
    print(f"case_id: {case_id}")
    print(f"user: {email}")
    print(f"question: {question!r}")
    print()

    results: List[Dict[str, Any]] = []
    for i in range(runs):
        label = "cold-ish" if i == 0 else f"warm #{i}"
        print(f"--- Run {i + 1} ({label}) ---")
        try:
            r = _stream_chat(
                base_url=base_url,
                case_id=case_id,
                token=token,
                question=question,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            print(f"FAILED: {exc}")
            return 1
        results.append(r)
        print(f"HTTP {r['http_status']}")
        print(f"total:          {r['total_ms']/1000:.2f}s")
        print(f"first byte:     {(r['first_byte_ms'] or 0)/1000:.2f}s")
        print(f"first text:     {(r['first_text_ms'] or 0)/1000:.2f}s  (TTFT to user)")
        print(f"finish event:   {(r['finish_event_ms'] or r['total_ms'])/1000:.2f}s")
        print(f"answer:         {r['answer_chars']} chars, citations={r['citations_count']}")
        if r["errors"]:
            print(f"errors: {r['errors']}")
        if r["phases"]:
            print("phases:")
            prev = 0.0
            for p in r["phases"]:
                delta = p["ms"] - prev
                print(f"  +{p['ms']/1000:6.2f}s  (+{delta/1000:.2f}s)  {p['phase']}")
                prev = p["ms"]
        print(f"preview: {r['answer_preview'][:200]}...")
        print()

    if len(results) >= 2:
        print("=== Summary ===")
        print(f"run1 total: {results[0]['total_ms']/1000:.2f}s")
        print(f"run2 total: {results[1]['total_ms']/1000:.2f}s")
        print(f"run1 TTFT:  {(results[0]['first_text_ms'] or 0)/1000:.2f}s")
        print(f"run2 TTFT:  {(results[1]['first_text_ms'] or 0)/1000:.2f}s")

    return 0 if all(r["http_status"] == 200 and not r["errors"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
