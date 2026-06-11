#!/usr/bin/env python3
"""
Smoke E2E: создать agent run по реальному делу с файлами и прогнать executor.

Использование:
  cd backend && python3 scripts/smoke_agent_run_e2e.py
  AGENT_RUN_SMOKE_CASE_ID=<uuid> python3 scripts/smoke_agent_run_e2e.py
  AGENT_RUN_SMOKE_TASK="..." python3 scripts/smoke_agent_run_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import config  # noqa: E402
from app.services.agent_runs.executor import AgentRunExecutor  # noqa: E402
from app.services.agent_runs.repository import AgentRunRepository  # noqa: E402
from app.services.agent_runs.worker import get_agent_run_worker  # noqa: E402
from app.utils.database import SessionLocal  # noqa: E402


DEFAULT_TASK = (
    "Сначала найди в документах дела упоминания сумм и сторон через agent_case_search. "
    "Затем кратко перечисли найденное. Если данных мало — вызови agent_ping с сообщением smoke."
)


def _pick_case(conn) -> tuple[str, str, str, int]:
    case_id = (os.getenv("AGENT_RUN_SMOKE_CASE_ID") or "").strip()
    if case_id:
        row = conn.execute(
            text(
                """
                SELECT c.id, c.user_id, c.title,
                       (SELECT COUNT(*) FROM files f WHERE f.case_id = c.id) AS file_count
                FROM cases c
                WHERE c.id = :case_id
                """
            ),
            {"case_id": case_id},
        ).first()
        if not row:
            raise SystemExit(f"Case not found: {case_id}")
        return str(row[0]), str(row[1]), str(row[2] or ""), int(row[3] or 0)

    row = conn.execute(
        text(
            """
            SELECT c.id, c.user_id, c.title, COUNT(f.id) AS file_count
            FROM cases c
            JOIN files f ON f.case_id = c.id
            GROUP BY c.id, c.user_id, c.title
            HAVING COUNT(f.id) > 0
            ORDER BY COUNT(f.id) DESC
            LIMIT 1
            """
        )
    ).first()
    if not row:
        raise SystemExit("No case with files found in database")
    return str(row[0]), str(row[1]), str(row[2] or ""), int(row[3] or 0)


def _pick_file_ids(conn, case_id: str, limit: int = 5) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT id FROM files
            WHERE case_id = :case_id
            ORDER BY created_at DESC NULLS LAST
            LIMIT :lim
            """
        ),
        {"case_id": case_id, "lim": limit},
    ).fetchall()
    return [str(r[0]) for r in rows]


async def _run_stream(run_id: str, user_id: str) -> dict:
    executor = AgentRunExecutor()
    events: list[dict] = []
    tool_names: list[str] = []
    text_parts: list[str] = []

    async for chunk in executor.stream(run_id, user_id):
        if not chunk.startswith("data: "):
            continue
        try:
            payload = json.loads(chunk[6:].strip())
        except json.JSONDecodeError:
            continue
        events.append(payload)
        etype = payload.get("type")
        data = payload.get("data") or {}
        if etype == "tool_started":
            tool_names.append(str(data.get("tool") or ""))
        if etype == "text_delta" and data.get("text"):
            text_parts.append(str(data["text"]))
        if etype in ("run_completed", "run_failed", "run_cancelled", "error", "interrupt"):
            return {
                "terminal": etype,
                "events_count": len(events),
                "tools": tool_names,
                "text": "".join(text_parts).strip(),
                "last_event": payload,
            }

    return {
        "terminal": "no_terminal_event",
        "events_count": len(events),
        "tools": tool_names,
        "text": "".join(text_parts).strip(),
        "last_event": events[-1] if events else None,
    }


async def main() -> int:
    if not getattr(config, "AGENT_RUNS_ENABLED", True):
        print("AGENT_RUNS_ENABLED=false — abort")
        return 1

    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        case_id, user_id, title, file_count = _pick_case(conn)
        file_ids = _pick_file_ids(conn, case_id)

    task = (os.getenv("AGENT_RUN_SMOKE_TASK") or DEFAULT_TASK).strip()
    print(f"Case: {title!r} ({case_id}), files={file_count}, scope={len(file_ids)}")
    print(f"Task: {task[:120]}...")

    db = SessionLocal()
    try:
        repo = AgentRunRepository(db)
        run = repo.create(
            user_id=user_id,
            case_id=case_id,
            user_task=task,
            file_ids=file_ids,
        )
        print(f"Created run: {run.id}")
        db.refresh(run)
    finally:
        db.close()

    worker = get_agent_run_worker()
    await worker.start()
    try:
        result = await _run_stream(run.id, user_id)
    finally:
        await worker.stop()
    print("\n--- E2E result ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    db = SessionLocal()
    try:
        run = AgentRunRepository(db).get_for_user(run.id, user_id)
        print(f"Final status: {run.status if run else 'missing'}")
        print(f"Langfuse trace: {run.langfuse_trace_id if run else None}")
        print(f"Tool calls: {run.total_tool_calls if run else 0}")
    finally:
        db.close()

    ok = result["terminal"] in ("run_completed", "interrupt")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
