#!/usr/bin/env python3
"""Create case from KOB/SS PDFs, run ingest, print case_id."""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

PDFS = [
    Path("/Users/semyon_andronov04/Downloads/00. vstrechnyj isk IP KOB h SS 15l.pdf"),
    Path("/Users/semyon_andronov04/Downloads/03. pretenzija 5l.pdf"),
    Path("/Users/semyon_andronov04/Downloads/00. Pozicija po vozrazhenijam SS h IP KOB 8l.pdf"),
]
USER_EMAIL = "semenandronov2004@mail.ru"
TITLE = "Eval KOB vs Smart City (встречный иск / претензия / позиция)"


def main() -> int:
    from app.config import config
    from app.models.case import Case, File
    from app.models.user import User
    from app.services.file_processor_bg import process_files_background
    from app.utils.database import SessionLocal

    for p in PDFS:
        if not p.is_file():
            print(f"ERROR: missing {p}")
            return 1

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == USER_EMAIL).first()
        if not user:
            print(f"ERROR: user {USER_EMAIL} not found")
            return 1

        case_id = str(uuid.uuid4())
        filenames = [p.name for p in PDFS]
        case = Case(
            id=case_id,
            user_id=user.id,
            title=TITLE,
            description="Golden eval corpus: counterclaim + pretension + position",
            full_text="",
            file_names=filenames,
            num_documents=len(filenames),
            status="processing",
        )
        db.add(case)
        db.flush()

        upload_root = Path(config.UPLOAD_DIR)
        if not upload_root.is_absolute():
            upload_root = (BACKEND_ROOT / upload_root).resolve()
        case_dir = upload_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        file_ids: list[str] = []
        for src in PDFS:
            dest = case_dir / src.name
            shutil.copy2(src, dest)
            fid = str(uuid.uuid4())
            rel = f"{case_id}/{src.name}"
            ext = src.suffix.lstrip(".").lower() or "pdf"
            row = File(
                id=fid,
                case_id=case_id,
                filename=src.name[:255],
                file_type=ext[:50],
                original_text="",
                file_path=rel,
                processing_status="pending",
            )
            db.add(row)
            file_ids.append(fid)
            print(f"staged {src.name} -> {rel} id={fid}")

        db.commit()
        print(f"case_id={case_id}")
        print(f"processing {len(file_ids)} files…")
        process_files_background(file_ids, case_id)

        db.expire_all()
        files = db.query(File).filter(File.case_id == case_id).all()
        for f in files:
            print(
                f"  {f.filename}: status={f.processing_status} "
                f"text_chars={len(f.original_text or '')} "
                f"summary={(f.doc_summary_short or '')[:80]!r}"
            )
            if f.processing_status != "ready":
                print(f"ERROR: file not ready: {f.filename} status={f.processing_status}")
                return 2

        case = db.query(Case).filter(Case.id == case_id).first()
        print(f"case status={getattr(case, 'status', None)}")
        print(f"READY case_id={case_id}")
        out = BACKEND_ROOT / "evals" / "case_kob_ss_case_id.txt"
        out.write_text(case_id + "\n", encoding="utf-8")
        print(f"wrote {out}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
