#!/usr/bin/env python3
"""Backfill case_file_summaries from files.doc_summary_short for existing cases."""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill file summary index")
    parser.add_argument("--case-id", dest="case_id", default="", help="Single case UUID")
    parser.add_argument("--limit", type=int, default=500, help="Max cases when no case-id")
    args = parser.parse_args()

    from app.utils.database import SessionLocal
    from app.services.file_summary_index import ensure_case_summaries_indexed

    db = SessionLocal()
    try:
        if args.case_id:
            n = ensure_case_summaries_indexed(db, args.case_id.strip())
            logger.info("Indexed %s file summaries for case %s", n, args.case_id)
            return 0

        from sqlalchemy import text

        rows = db.execute(
            text(
                """
                SELECT DISTINCT case_id FROM files
                WHERE doc_summary_short IS NOT NULL
                  AND TRIM(doc_summary_short) <> ''
                LIMIT :lim
                """
            ),
            {"lim": max(1, args.limit)},
        ).fetchall()
        total = 0
        for (cid,) in rows:
            total += ensure_case_summaries_indexed(db, str(cid))
        logger.info("Backfill complete: %s summary rows upserted across %s cases", total, len(rows))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
