#!/usr/bin/env python3
"""Smoke: 3 Desktop lease PDFs → DD commercial lease tabular template."""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

DESKTOP = Path("/Users/semyon_andronov04/Desktop")
DOCS: List[Tuple[str, Path]] = [
    (
        "01_chikisheva_6l.pdf",
        DESKTOP / "Dogovor arendy pomeschenija Chikisheva 6 l.pdf",
    ),
    (
        "02_lease_20-01-2022_9l.pdf",
        DESKTOP
        / "Dogovor arendy dvizhimogo imuschestva s pravom vykupa є20-01-2022-1 ot 20.01.2022 g na 9 l.pdf",
    ),
    (
        "03_lease_03-03-2022_10l.pdf",
        DESKTOP
        / "Dogovor arendy dvizhimogo imuschestva s pravom vykupa є03-03-2022-1 ot 03.03.2022 g na 10 l.pdf",
    ),
]

from app.services.contract_field_catalog import RU_DD_LEASE_TEMPLATE  # noqa: E402

COLUMNS: List[Dict[str, Any]] = list(RU_DD_LEASE_TEMPLATE["columns"])
OUT_PATH = REPO_ROOT / "evals" / "ru_dd_lease_3docs_manual_cols_smoke.json"
TITLE = "DD lease 3 docs — columns copied from commercial lease (not template apply)"


def _wait_files_ready(db, file_ids: List[str], *, timeout_sec: int = 3600) -> None:
    from app.models.case import File

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        rows = db.query(File).filter(File.id.in_(file_ids)).all()
        statuses = {str(f.id): f.processing_status for f in rows}
        ready = sum(1 for s in statuses.values() if s == "ready")
        failed = [fid for fid, s in statuses.items() if s == "failed"]
        print(f"  ingest progress: {ready}/{len(file_ids)} ready, failed={len(failed)}", flush=True)
        if rows and all(f.processing_status == "ready" for f in rows):
            return
        if failed:
            bad = db.query(File).filter(File.id.in_(failed)).all()
            detail = [(f.filename, (f.processing_error or "")[:200]) for f in bad]
            raise RuntimeError(f"ingest failed: {detail}")
        time.sleep(8)
    raise TimeoutError("ingest timeout")


def main() -> int:
    from app.config import config
    from app.models.case import Case, File
    from app.models.tabular_review import TabularCell, TabularColumn
    from app.models.user import User
    from app.services.bm25_case_prewarm import finalize_case_bm25_after_ingestion
    from app.services.document_processor import get_document_processor
    from app.services.file_processor_bg import process_files_background
    from app.services.tabular_review_service import TabularReviewService
    from app.utils.database import SessionLocal, ensure_schema

    ensure_schema()

    for _, src in DOCS:
        if not src.is_file():
            print(f"ERROR missing: {src}")
            return 1

    t0 = time.time()
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            print("ERROR: no users in DB")
            return 1
        user_id = str(user.id)

        case_id = str(uuid.uuid4())
        case = Case(
            id=case_id,
            user_id=user_id,
            title=TITLE,
            description="3 Desktop lease PDFs × DD commercial lease template",
            case_type="dd",
            status="processing",
            full_text="",
            num_documents=len(DOCS),
            file_names=[name for name, _ in DOCS],
        )
        db.add(case)
        db.flush()

        upload_root = Path(config.UPLOAD_DIR)
        if not upload_root.is_absolute():
            upload_root = (BACKEND_ROOT / upload_root).resolve()
        case_dir = upload_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        file_ids: List[str] = []
        for dest_name, src in DOCS:
            dest = case_dir / dest_name
            shutil.copy2(src, dest)
            fid = str(uuid.uuid4())
            rel = f"{case_id}/{dest_name}"
            ext = dest_name.rsplit(".", 1)[-1].lower()
            db.add(
                File(
                    id=fid,
                    case_id=case_id,
                    filename=dest_name[:255],
                    file_type=ext[:50],
                    original_text="",
                    file_path=rel,
                    processing_status="pending",
                )
            )
            file_ids.append(fid)
            print(f"staged {dest_name} ({src.stat().st_size / 1e6:.1f}MB) id={fid}", flush=True)

        db.commit()
        print(f"case_id={case_id}", flush=True)
        print(f"process_files_background ({len(file_ids)} files)...", flush=True)
        process_files_background(file_ids, case_id)
        _wait_files_ready(db, file_ids, timeout_sec=3600)
        db.expire_all()

        files = db.query(File).filter(File.case_id == case_id).order_by(File.filename).all()
        ingest_rows = []
        for f in files:
            n = len(f.original_text or "")
            row = {
                "file_id": str(f.id),
                "filename": f.filename,
                "status": f.processing_status,
                "chars": n,
                "dd_doc_type": getattr(f, "dd_doc_type", None),
                "dd_doc_type_confidence": getattr(f, "dd_doc_type_confidence", None),
            }
            ingest_rows.append(row)
            print(
                f"  ingested {f.filename}: chars={n} status={f.processing_status} "
                f"dd={row['dd_doc_type']}",
                flush=True,
            )

        finalize_case_bm25_after_ingestion(case_id, get_document_processor())
        case = db.query(Case).filter(Case.id == case_id).one()
        case.status = "completed"
        case.num_documents = len(files)
        db.commit()

        service = TabularReviewService(db)
        review = service.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name="DD аренда — ручные колонки (копия commercial lease)",
            description=(
                "Колонки добавлены вручную копированием из RU_DD_LEASE_TEMPLATE, "
                "без apply_template"
            ),
            selected_file_ids=file_ids,
        )
        review_id = str(review.id)
        print(f"review_id={review_id}", flush=True)

        created_cols = []
        for spec in COLUMNS:
            col = service.add_column(
                review_id=review_id,
                column_label=spec["column_label"],
                column_type=spec["column_type"],
                prompt=spec["prompt"],
                user_id=user_id,
                column_config=spec.get("column_config"),
            )
            created_cols.append(
                {
                    "id": str(col.id),
                    "label": col.column_label,
                    "column_type": col.column_type,
                    "column_config": spec.get("column_config"),
                }
            )
            print(f"  + column {col.column_label} id={col.id}", flush=True)

        async def _run_all_columns() -> List[Dict[str, Any]]:
            runs: List[Dict[str, Any]] = []
            for col_meta in created_cols:
                print(f"RUN column {col_meta['label']}...", flush=True)
                t_col = time.time()
                result = await service.run_column_extraction(
                    review_id=review_id,
                    column_id=col_meta["id"],
                    user_id=user_id,
                )
                elapsed_col = round(time.time() - t_col, 1)
                runs.append(
                    {
                        **col_meta,
                        "elapsed_sec": elapsed_col,
                        "result": {
                            "status": result.get("status"),
                            "saved_count": result.get("saved_count"),
                            "filled_count": result.get("filled_count"),
                            "error_count": result.get("error_count"),
                        },
                    }
                )
                print(
                    f"  done {col_meta['label']} in {elapsed_col}s "
                    f"saved={result.get('saved_count')} filled={result.get('filled_count')} "
                    f"errors={result.get('error_count')}",
                    flush=True,
                )
            return runs

        column_runs = asyncio.run(_run_all_columns())

        cells = (
            db.query(TabularCell, TabularColumn, File)
            .join(TabularColumn, TabularCell.column_id == TabularColumn.id)
            .join(File, TabularCell.file_id == File.id)
            .filter(TabularCell.tabular_review_id == review_id)
            .all()
        )
        table: Dict[str, Dict[str, Any]] = {}
        for cell, col, f in cells:
            fname = f.filename or str(f.id)
            table.setdefault(fname, {"_dd": getattr(f, "dd_doc_type", None)})
            val = (cell.cell_value or "").strip()
            if len(val) > 220:
                val = val[:217] + "..."
            table[fname][col.column_label] = val or "—"

        filled = sum(
            1
            for _, cols in table.items()
            for k, v in cols.items()
            if k != "_dd" and v and v not in {"—", "N/A", "n/a", "NA", "«—»"}
        )
        total = sum(1 for _, cols in table.items() for k in cols if k != "_dd")
        payload = {
            "case_id": case_id,
            "review_id": review_id,
            "elapsed_sec": round(time.time() - t0, 1),
            "ingest": ingest_rows,
            "column_runs": [
                {
                    "label": r["label"],
                    "elapsed_sec": r["elapsed_sec"],
                    "status": (r.get("result") or {}).get("status"),
                    "saved": (r.get("result") or {}).get("saved_count"),
                    "filled": (r.get("result") or {}).get("filled_count"),
                    "errors": (r.get("result") or {}).get("error_count"),
                }
                for r in column_runs
            ],
            "table_snapshot": table,
            "stats": {
                "files": len(table),
                "columns": len(COLUMNS),
                "cells_total": total,
                "cells_filled": filled,
                "fill_rate": round(filled / total, 3) if total else 0.0,
            },
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {OUT_PATH}", flush=True)
        print(json.dumps(payload["stats"], ensure_ascii=False), flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
