#!/usr/bin/env python3
"""Smoke: column «о чём документ кратко» on a bank statement file."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

PDF_PATH = Path("/Users/semyon_andronov04/Downloads/funds_movement.pdf")


async def main() -> int:
    from sqlalchemy import func

    from app import config as config_module
    from app.models.case import Case, File
    from app.models.case_file_transaction import CaseFileTransaction
    from app.models.tabular_review import TabularColumn, TabularReview
    from app.models.user import User
    from app.services.case_file_transaction_service import CaseFileTransactionService
    from app.services.document_indexing import build_index_chunks
    from app.services.tabular_review_service import TabularReviewService
    from app.utils.database import SessionLocal

    config_module.config.CASE_FILE_TRANSACTIONS_ENABLED = True
    config_module.config.TABULAR_CELL_DATA_ROUTER_ENABLED = True

    db = SessionLocal()
    created_review_id = None
    created_column_id = None
    try:
        # Prefer existing statement with SQL rows
        row = (
            db.query(CaseFileTransaction.file_id, CaseFileTransaction.case_id, func.count())
            .group_by(CaseFileTransaction.file_id, CaseFileTransaction.case_id)
            .order_by(func.count().desc())
            .first()
        )

        file: File | None = None
        if row:
            file = db.query(File).filter(File.id == row[0]).first()
            print(f"Using existing statement file: {file.filename if file else row[0]} (tx rows: {row[2]})")
        elif PDF_PATH.is_file():
            print("No indexed statements in DB — ingesting funds_movement.pdf into temp case…")
            user = db.query(User).first()
            if not user:
                print("ERROR: no users in DB")
                return 1
            case = Case(
                user_id=user.id,
                title="Smoke tabular statement",
                description="auto",
                full_text="",
                file_names=["funds_movement.pdf"],
                num_documents=1,
            )
            db.add(case)
            db.flush()
            docs = build_index_chunks(
                content_bytes=PDF_PATH.read_bytes(),
                filename="funds_movement.pdf",
                base_metadata={"doc_id": "smoke-fm", "file_id": "smoke-fm", "case_id": case.id},
                loader_native_text=True,
            )
            header_text = ""
            for d in docs[:3]:
                header_text += (d.page_content or "")[:2000]
            file = File(
                id="smoke-fm",
                case_id=case.id,
                filename="funds_movement.pdf",
                file_type="pdf",
                original_text=header_text or "bank statement",
                processing_status="ready",
            )
            db.add(file)
            db.flush()
            count = CaseFileTransactionService.sync_from_documents(
                db,
                case_id=case.id,
                file_id=file.id,
                filename=file.filename,
                documents=docs,
            )
            db.commit()
            print(f"Ingested {count} transaction rows for {file.id}")
        else:
            print("ERROR: no statement files in DB and funds_movement.pdf missing")
            return 1

        if not file:
            print("ERROR: file not found")
            return 1

        case = db.query(Case).filter(Case.id == file.case_id).first()
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            print("ERROR: case owner not found")
            return 1

        has_tx = CaseFileTransactionService.case_has_transactions(db, case.id, [file.id])
        print(f"case_id={case.id} file_id={file.id} has_transactions={has_tx}")

        service = TabularReviewService(db)
        if not service.llm:
            print("ERROR: LLM not configured — cannot run extraction")
            return 1

        review = service.create_tabular_review(
            case_id=case.id,
            user_id=user.id,
            name="Smoke: выписка summary",
            description="auto smoke test",
            selected_file_ids=[file.id],
        )
        created_review_id = review.id
        db.commit()

        column = service.add_column(
            review_id=review.id,
            column_label="О чём документ",
            column_type="text",
            prompt="О чём документ кратко? Одно короткое предложение — тип документа и суть.",
            user_id=user.id,
        )
        created_column_id = column.id
        db.commit()
        print(f"Created column: {column.column_label} ({column.id})")

        result = await service.extract_cell_value_improved(file=file, column=column)
        print("\n=== EXTRACTION RESULT ===")
        print(json.dumps(
            {
                "cell_value": result.get("cell_value"),
                "reasoning": (result.get("reasoning") or "")[:300],
                "extraction_method": result.get("extraction_method"),
                "confidence_score": result.get("confidence_score"),
                "error": result.get("error"),
                "needs_review": result.get("needs_review"),
            },
            ensure_ascii=False,
            indent=2,
        ))

        filled = bool((result.get("cell_value") or "").strip()) and not result.get("error")
        print(f"\nFILLED={'YES' if filled else 'NO'}")
        return 0 if filled else 2
    finally:
        if created_review_id and created_column_id:
            try:
                db.query(TabularColumn).filter(TabularColumn.id == created_column_id).delete()
                db.query(TabularReview).filter(TabularReview.id == created_review_id).delete()
                db.commit()
            except Exception:
                db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
