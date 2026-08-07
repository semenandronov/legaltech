#!/usr/bin/env python3
"""Production smoke: outline + section router + DD lease extract on one Desktop PDF."""
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

PDF_SRC = Path("/Users/semyon_andronov04/Desktop/03. договор от 16.04.2024 на 14л.pdf")
DEST_NAME = "03_dogovor_16-04-2024_14l.pdf"
OUT_PATH = REPO_ROOT / "evals" / "ru_outline_route_14l_smoke.json"
TITLE = "Outline route smoke — 03. договор 16.04.2024 14л"

ROUTE_PROBES: List[Tuple[str, str, str]] = [
    ("Арендодатель", "Кто арендодатель по договору?", "text"),
    ("Арендная плата", "Каков размер арендной платы?", "text"),
    ("Срок аренды", "На какой срок заключен договор аренды?", "text"),
    ("Неустойка", "Какая неустойка предусмотрена за просрочку?", "text"),
    ("Расторжение", "Каковы условия расторжения договора?", "text"),
    ("Объект аренды", "Что является объектом аренды?", "text"),
]


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
    from app.services.contract_field_catalog import RU_DD_LEASE_TEMPLATE
    from app.services.document_processor import get_document_processor
    from app.services.file_document_outline import load_outline_payload_from_file
    from app.services.file_processor_bg import process_files_background
    from app.services.tabular_document_context import (
        build_file_context_package,
        prepare_file_context_packages,
    )
    from app.services.tabular_review_service import TabularReviewService
    from app.services.tabular_section_router import route_column_to_sections
    from app.utils.database import SessionLocal, ensure_schema

    ensure_schema()

    if not PDF_SRC.is_file():
        print(f"ERROR missing: {PDF_SRC}")
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
            description="Outline + section router production smoke",
            case_type="dd",
            status="processing",
            full_text="",
            num_documents=1,
            file_names=[DEST_NAME],
        )
        db.add(case)
        db.flush()

        upload_root = Path(config.UPLOAD_DIR)
        if not upload_root.is_absolute():
            upload_root = (BACKEND_ROOT / upload_root).resolve()
        case_dir = upload_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        dest = case_dir / DEST_NAME
        shutil.copy2(PDF_SRC, dest)
        file_id = str(uuid.uuid4())
        db.add(
            File(
                id=file_id,
                case_id=case_id,
                filename=DEST_NAME[:255],
                file_type="pdf",
                original_text="",
                file_path=f"{case_id}/{DEST_NAME}",
                processing_status="pending",
            )
        )
        db.commit()
        print(f"case_id={case_id} file_id={file_id}", flush=True)
        print(f"prod ingest {DEST_NAME} ({PDF_SRC.stat().st_size / 1e6:.1f}MB)...", flush=True)

        process_files_background([file_id], case_id)
        _wait_files_ready(db, [file_id], timeout_sec=3600)
        db.expire_all()

        fm = db.query(File).filter(File.id == file_id).one()
        chars = len(fm.original_text or "")
        outline_payload = load_outline_payload_from_file(fm) or {}
        outline_rows = outline_payload.get("outline") or []
        print(
            f"ingested chars={chars} status={fm.processing_status} "
            f"outline_sections={len(outline_rows)}",
            flush=True,
        )
        for i, row in enumerate(outline_rows[:40], 1):
            label = (row.get("section_label") or row.get("section_title") or "")[:80]
            print(f"  [{i}] {row.get('section_number') or '—'} {label}", flush=True)

        finalize_case_bm25_after_ingestion(case_id, get_document_processor())
        case = db.query(Case).filter(Case.id == case_id).one()
        case.status = "completed"
        db.commit()

        packages = prepare_file_context_packages(
            db,
            case_id=case_id,
            file_ids=[file_id],
            vector_store=getattr(get_document_processor(), "vector_store", None),
        )
        pkg = packages.get(file_id) or build_file_context_package(
            file_row=fm, outline_payload=outline_payload
        )

        route_results: List[Dict[str, Any]] = []
        for label, question, col_type in ROUTE_PROBES:
            plan = route_column_to_sections(
                file_context=pkg,
                semantic_query=question,
                lexical_terms=tuple(w for w in label.lower().split() if len(w) > 2),
                exact_query="",
                column_type=col_type,
                column_label=label,
            )
            titles = []
            for sid in plan.section_root_ids:
                for entry in pkg.outline:
                    if entry.section_root_id == sid:
                        titles.append(entry.section_label or entry.section_title)
                        break
            route_results.append(
                {
                    "column_label": label,
                    "question": question,
                    "route_method": plan.route_method,
                    "confidence": round(plan.confidence, 3),
                    "section_titles": titles,
                    "rationale": plan.rationale,
                }
            )
            print(
                f"ROUTE {label}: method={plan.route_method} conf={plan.confidence:.2f} "
                f"→ {titles[:3] or ['(full_file)']}",
                flush=True,
            )

        columns = list(RU_DD_LEASE_TEMPLATE["columns"])
        service = TabularReviewService(db)
        review = service.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name="DD: коммерческая аренда — outline smoke 14л",
            description=RU_DD_LEASE_TEMPLATE.get("description"),
            selected_file_ids=[file_id],
        )
        review_id = str(review.id)
        print(f"review_id={review_id}", flush=True)

        created_cols: List[Dict[str, Any]] = []
        for spec in columns:
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
                }
            )

        async def _run_all() -> List[Dict[str, Any]]:
            runs: List[Dict[str, Any]] = []
            for col_meta in created_cols:
                print(f"RUN {col_meta['label']}...", flush=True)
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
                        "saved": result.get("saved_count"),
                        "filled": result.get("filled_count"),
                        "errors": result.get("error_count"),
                        "status": result.get("status"),
                    }
                )
                print(
                    f"  done {col_meta['label']} {elapsed_col}s "
                    f"filled={result.get('filled_count')} err={result.get('error_count')}",
                    flush=True,
                )
            return runs

        column_runs = asyncio.run(_run_all())

        cells = (
            db.query(TabularCell, TabularColumn)
            .join(TabularColumn, TabularCell.column_id == TabularColumn.id)
            .filter(TabularCell.tabular_review_id == review_id)
            .all()
        )
        answers: Dict[str, Any] = {}
        for cell, col in cells:
            val = (cell.cell_value or "").strip()
            if len(val) > 280:
                val = val[:277] + "..."
            answers[col.column_label] = val or "—"

        filled = sum(
            1
            for v in answers.values()
            if v and v not in {"—", "N/A", "n/a", "NA", "«—»"}
        )
        payload = {
            "case_id": case_id,
            "review_id": review_id,
            "file_id": file_id,
            "source_pdf": str(PDF_SRC),
            "elapsed_sec": round(time.time() - t0, 1),
            "ingest": {
                "chars": chars,
                "status": fm.processing_status,
                "outline_sections": len(outline_rows),
                "outline": [
                    {
                        "number": r.get("section_number"),
                        "title": r.get("section_title"),
                        "label": r.get("section_label"),
                    }
                    for r in outline_rows
                ],
            },
            "route_probes": route_results,
            "column_runs": column_runs,
            "answers": answers,
            "stats": {
                "columns": len(columns),
                "cells_filled": filled,
                "fill_rate": round(filled / len(columns), 3) if columns else 0.0,
                "dcp_enabled": bool(getattr(config, "TABULAR_DCP_ENABLED", True)),
                "section_router_enabled": bool(
                    getattr(config, "TABULAR_SECTION_ROUTER_ENABLED", True)
                ),
            },
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {OUT_PATH}", flush=True)
        print(json.dumps(payload["stats"], ensure_ascii=False), flush=True)
        print(json.dumps(answers, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
