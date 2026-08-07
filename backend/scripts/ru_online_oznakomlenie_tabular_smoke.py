#!/usr/bin/env python3
"""
Lawyer-like smoke: upload Online-oznakomlenie docs via production ingest,
create tabular review, add mixed-difficulty columns, run each column.
"""
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

BASE = Path("/Users/semyon_andronov04/Downloads/01. Онлайн ознакомление")

# Mixed complexity: text-layer DS/APP + scanned leases + all Word docs in folder
DOCS: List[Tuple[str, Path]] = [
    ("01_ds1_arenda.pdf", BASE / "04. Август 2024/16.08.2024_ИПК/4/DS є1 ot 25.07.22 g k Dogovoru arendy na 2 l.pdf"),
    ("02_ds2_arenda.pdf", BASE / "03. Июль 2024/14.07.2024_ИПК/Dopolnitelnoe soglashenie є2 k dogovoru arendy є03-03-2022-1 ot 03.03.2022 na 2 l.pdf"),
    ("03_app_arenda_20.pdf", BASE / "10. Февраль 2025/12.02.2024_СС/07. APP k dogovoru arendy 20-01-22 3l.pdf"),
    ("04_dogovor_arendy_20.pdf", BASE / "10. Февраль 2025/12.02.2024_СС/06. dogovor arendy 20-01-22 9l.pdf"),
    ("05_dogovor_arendy_30.pdf", BASE / "10. Февраль 2025/12.02.2024_СС/10. dogovor arendy 30-03-22 10l.pdf"),
    ("06_dogovor_arendy_chikisheva.pdf", BASE / "09. Январь 2025/12.01.2024_ИПК/Dogovor arendy pomeschenija Chikisheva 6 l.pdf"),
    ("07_dogovor_arendy_20_scan.pdf", BASE / "03. Июль 2024/14.07.2024_ИПК/Dogovor arendy dvizhimogo imuschestva s pravom vykupa є20-01-2022-1 ot 20.01.2022 g na 9 l.pdf"),
    ("08_dogovor_arendy_03_scan.pdf", BASE / "03. Июль 2024/14.07.2024_ИПК/Dogovor arendy dvizhimogo imuschestva s pravom vykupa є03-03-2022-1 ot 03.03.2022 g na 10 l.pdf"),
    ("09_isk.docx", BASE / "10. Февраль 2025/12.02.2024_ИПК/Isk Krasnoshtanova O.B..OOO Smart Siti 6 l.docx"),
    ("10_uvelichenie_isk.docx", BASE / "08. Декабрь 2024/02.12.2024_ИПК/Uvelichenie iskovyh trebovanij na 22 l.docx"),
    ("11_hodatajstvo.docx", BASE / "03. Июль 2024/31.07.2024_СС/00. hod-vo istrebovanie SS h IP KOB na 2l.docx"),
]

COLUMNS: List[Dict[str, Any]] = [
    {
        "difficulty": "easy",
        "column_label": "Дата документа",
        "column_type": "date",
        "prompt": "Дата подписания или составления этого документа (YYYY-MM-DD).",
        "column_config": {"field_id": "doc_date", "column_kind": "fact"},
    },
    {
        "difficulty": "easy",
        "column_label": "Номер договора",
        "column_type": "text",
        "prompt": "Укажи номер договора / дополнительного соглашения.",
        "column_config": {"field_id": "doc_number", "column_kind": "fact"},
    },
    {
        "difficulty": "medium",
        "column_label": "Арендная плата",
        "column_type": "currency",
        "prompt": "Ключевая сумма арендной платы. Если документа не про аренду — N/A.",
        "column_config": {"field_id": "rent_amount", "column_kind": "fact"},
    },
    {
        "difficulty": "medium",
        "column_label": "Право выкупа",
        "column_type": "yes_no",
        "prompt": "Предусмотрено ли право выкупа? Да / Нет / N/A.",
        "column_config": {"field_id": "buyout_right", "column_kind": "fact"},
    },
    {
        "difficulty": "medium",
        "column_label": "Арендодатель",
        "column_type": "text",
        "prompt": "Кто арендодатель? Если документ не договор аренды — N/A.",
        "column_config": {"field_id": "landlord", "column_kind": "fact"},
    },
    {
        "difficulty": "hard",
        "column_label": "Объект аренды",
        "column_type": "text",
        "prompt": "Что передаётся в аренду? Кратко. Если не аренда — N/A.",
        "column_config": {"field_id": "leased_object", "column_kind": "fact"},
    },
    {
        "difficulty": "hard",
        "column_label": "Неустойка",
        "column_type": "text",
        "prompt": "Условия неустойки / пени по документу. Если нет — N/A.",
        "column_config": {"field_id": "penalty", "column_kind": "fact"},
    },
    {
        "difficulty": "hard",
        "column_label": "Ключевые риски",
        "column_type": "text",
        "prompt": (
            "Перечисли ключевые риски этого документа для due diligence "
            "(ответственность, расторжение, неустойка, оплата). Краткий маркированный список. "
            "Если это не договор — кратко суть процессуального документа."
        ),
        "column_config": {"column_kind": "risk_analysis"},
    },
]

OUT_PATH = REPO_ROOT / "evals" / "ru_online_oznakomlenie_tabular_run.json"
TITLE = "DD Онлайн ознакомление — аренда + Word (smoke)"


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
            detail = [(f.filename, (f.processing_error or "")[:120]) for f in bad]
            raise RuntimeError(f"ingest failed: {detail}")
        time.sleep(5)
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
            description="Production-path smoke: Online oznakomlenie lease + Word",
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
            print(f"staged {dest_name} ({src.stat().st_size/1e6:.1f}MB) id={fid}", flush=True)

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
            name="Аренда DD — колонки разной сложности",
            description="Smoke: easy/medium/hard + risk",
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
                column_config=spec["column_config"],
            )
            created_cols.append(
                {
                    "id": str(col.id),
                    "label": col.column_label,
                    "difficulty": spec["difficulty"],
                    "column_type": col.column_type,
                    "column_config": spec["column_config"],
                }
            )
            print(f"  + column [{spec['difficulty']}] {col.column_label} id={col.id}", flush=True)

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
                            "total_tasks": result.get("total_tasks"),
                        },
                    }
                )
                print(
                    f"  done status={result.get('status')} saved={result.get('saved_count')} "
                    f"filled={result.get('filled_count')} err={result.get('error_count')} "
                    f"in {elapsed_col}s",
                    flush=True,
                )
            return runs

        column_runs = asyncio.run(_run_all_columns())

        db.expire_all()
        # Snapshot table values
        table: Dict[str, Dict[str, str]] = {}
        for f in files:
            table[f.filename] = {}
        cols = (
            db.query(TabularColumn)
            .filter(TabularColumn.tabular_review_id == review_id)
            .order_by(TabularColumn.order_index)
            .all()
        )
        cells = (
            db.query(TabularCell)
            .filter(TabularCell.tabular_review_id == review_id)
            .all()
        )
        file_by_id = {str(f.id): f.filename for f in files}
        col_by_id = {str(c.id): c.column_label for c in cols}
        for cell in cells:
            fname = file_by_id.get(str(cell.file_id), str(cell.file_id))
            label = col_by_id.get(str(cell.column_id), str(cell.column_id))
            val = (cell.cell_value or "").strip()
            if len(val) > 180:
                val = val[:177] + "..."
            table.setdefault(fname, {})[label] = val or "—"

        non_empty = 0
        na_like = 0
        total_cells = 0
        for row in table.values():
            for v in row.values():
                total_cells += 1
                vv = (v or "").strip()
                if not vv or vv in {"—", "-", "–"}:
                    continue
                if vv.upper() in {"N/A", "NA", "Н/Д"}:
                    na_like += 1
                else:
                    non_empty += 1

        payload = {
            "case_id": case_id,
            "review_id": review_id,
            "user_id": user_id,
            "elapsed_sec": round(time.time() - t0, 1),
            "ingest": ingest_rows,
            "columns": column_runs,
            "table_snapshot": table,
            "stats": {
                "files": len(files),
                "columns": len(cols),
                "cells_total": total_cells,
                "cells_filled": non_empty,
                "cells_na": na_like,
                "fill_rate": round(non_empty / max(1, total_cells), 3),
            },
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"WROTE {OUT_PATH}", flush=True)
        print(json.dumps(payload["stats"], ensure_ascii=False, indent=2), flush=True)
        print(f"case_id={case_id}")
        print(f"review_id={review_id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
