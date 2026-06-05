#!/usr/bin/env python3
"""Reset case files to pending and schedule background processing."""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.services.file_processor_bg import process_files_background
from app.utils.database import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    args = parser.parse_args()
    case_id = args.case_id.strip()
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT id, filename, processing_status FROM files WHERE case_id = :c ORDER BY filename"),
            {"c": case_id},
        ).fetchall()
        if not rows:
            print(f"No files for case {case_id}")
            return 1
        print("before:", rows)
        ids = [r[0] for r in rows]
        db.execute(
            text(
                "UPDATE files SET processing_status = 'pending', processing_error = NULL, "
                "processing_started_at = NULL WHERE case_id = :c"
            ),
            {"c": case_id},
        )
        db.commit()
    finally:
        db.close()
    process_files_background(ids, case_id)
    print(f"requeued and processing {len(ids)} files for case {case_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
