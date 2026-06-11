#!/usr/bin/env python3
"""Smoke: upload supply-contract PDFs, run workflow, print result."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.config import config  # noqa: E402
from app.models.case import Case, File as FileModel  # noqa: E402
from app.services.agent_runs.executor import AgentRunExecutor  # noqa: E402
from app.services.agent_runs.repository import AgentRunRepository  # noqa: E402
from app.services.agent_runs.worker import get_agent_run_worker  # noqa: E402
from app.services.case_file_bytes import case_file_content_for_db  # noqa: E402
from app.services.file_processor_bg import process_files_background  # noqa: E402
from app.utils.database import SessionLocal  # noqa: E402

PDFS = [
    Path("/Users/semyon_andronov04/Downloads/Договор поставки.pdf"),
    Path("/Users/semyon_andronov04/Downloads/Платежное поручение.pdf"),
    Path("/Users/semyon_andronov04/Downloads/Акт приема-передачи оборудования.pdf"),
]

TASK = (
    "По трём документам дела (договор поставки, платёжное поручение, акт приёма-передачи) "
    "выполни комплексный анализ:\n"
    "1) Определи стороны, предмет поставки, сумму, сроки и условия оплаты из договора.\n"
    "2) Сверь сумму и получателя в платёжном поручении с договором.\n"
    "3) Проверь по акту, что поставка состоялась и что передано.\n"
    "4) Составь таблицу: документ | ключевые реквизиты | вывод.\n"
    "5) Перечисли юридические риски (просрочка, неполная поставка, расхождение сумм).\n"
    "Опирайся только на документы дела, не выдумывай факты."
)


def _get_user_id(db) -> str:
    email = os.getenv("WORKFLOW_SMOKE_USER_EMAIL", "semenandronov2004@mail.ru")
    row = db.execute(text("SELECT id FROM users WHERE email = :e LIMIT 1"), {"e": email}).first()
    if row:
        return str(row[0])
    row = db.execute(text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")).first()
    if not row:
        raise SystemExit("No users in database")
    return str(row[0])


def _upload_pdfs(db, case_id: str) -> list[str]:
    upload_dir = config.UPLOAD_DIR
    case_dir = os.path.join(upload_dir, case_id)
    os.makedirs(case_dir, exist_ok=True)
    file_ids: list[str] = []
    for src in PDFS:
        if not src.exists():
            raise SystemExit(f"Missing file: {src}")
        content = src.read_bytes()
        filename = src.name[:255]
        dest = os.path.join(case_dir, filename)
        shutil.copy2(src, dest)
        rel = os.path.join(case_id, filename)
        fm = FileModel(
            case_id=case_id,
            filename=filename,
            file_type="pdf",
            original_text="",
            file_path=rel,
            file_content=case_file_content_for_db(content),
            processing_status="pending",
        )
        db.add(fm)
        db.flush()
        file_ids.append(str(fm.id))
        print(f"  queued: {filename} -> {fm.id}")
    case = db.query(Case).filter(Case.id == case_id).first()
    if case:
        all_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        case.num_documents = len(all_files)
        case.file_names = [f.filename for f in all_files]
    db.commit()
    return file_ids


def _wait_ready(db, file_ids: list[str], timeout_sec: int = 600) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        rows = (
            db.query(FileModel)
            .filter(FileModel.id.in_(file_ids))
            .all()
        )
        statuses = {f.filename: f.processing_status for f in rows}
        print(f"  processing: {statuses}")
        if all((f.processing_status or "") == "ready" for f in rows):
            return
        if any((f.processing_status or "") == "error" for f in rows):
            errs = {f.filename: f.processing_error for f in rows if f.processing_status == "error"}
            raise SystemExit(f"File processing failed: {errs}")
        time.sleep(5)
        db.expire_all()
    raise SystemExit("Timeout waiting for file processing")


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
            t = str(data.get("tool") or "")
            tool_names.append(t)
            print(f"  [tool] {t}")
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
        print("AGENT_RUNS_ENABLED=false")
        return 1

    db = SessionLocal()
    try:
        user_id = _get_user_id(db)
        case_id = str(uuid.uuid4())
        case = Case(
            id=case_id,
            user_id=user_id,
            title="Smoke: договор поставки (3 документа)",
            status="pending",
            full_text="",
            num_documents=0,
            file_names=[],
        )
        db.add(case)
        db.commit()
        print(f"Case: {case_id}")

        print("Uploading PDFs...")
        file_ids = _upload_pdfs(db, case_id)

        print("Processing files (OCR + index)...")
        process_files_background(file_ids, case_id)
        _wait_ready(db, file_ids)

        print(f"\nTask:\n{TASK}\n")
        repo = AgentRunRepository(db)
        run = repo.create(
            user_id=user_id,
            case_id=case_id,
            user_task=TASK,
            file_ids=file_ids,
        )
        run_id = str(run.id)
        print(f"Run: {run_id}")
        db.commit()
    finally:
        db.close()

    worker = get_agent_run_worker()
    await worker.start()
    try:
        result = await _run_stream(run_id, user_id)
    finally:
        await worker.stop()

    db = SessionLocal()
    try:
        run_row = AgentRunRepository(db).get_for_user(run_id, user_id)
        summary = (run_row.result_summary or "") if run_row else ""
        status = run_row.status if run_row else "?"
        tools = int(run_row.total_tool_calls or 0) if run_row else 0
    finally:
        db.close()

    print("\n" + "=" * 60)
    print(f"STATUS: {status}")
    print(f"TOOLS: {tools} — {result.get('tools')}")
    print("=" * 60)
    body = result.get("text") or summary
    if body:
        print(body[:8000])
    else:
        print("(no text output)")
        print(json.dumps(result.get("last_event"), ensure_ascii=False, indent=2))

    print("\n" + "=" * 60)
    print(f"Open in UI: /cases/{case_id}/workflows?run={run_id}")

    ok = result["terminal"] == "run_completed" and bool(body)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
