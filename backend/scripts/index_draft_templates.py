#!/usr/bin/env python3
"""Backfill draft_template_field_catalog for bankruptcy HTML and admin DB templates."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# backend/ on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    from app.models.document_template import DocumentTemplate
    from app.services.bankruptcy_templates import _load_manifest_raw, load_system_template_body
    from app.services.draft_admin_template_service import ADMIN_DRAFT_SOURCE
    from app.services.draft_template_indexer import index_template_html
    from app.services.draft_template_keys import template_key_for_bankruptcy, template_key_for_db_template
    from app.utils.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    ok = 0
    fail = 0
    try:
        for item in _load_manifest_raw():
            if not isinstance(item, dict):
                continue
            tid = item.get("id")
            fname = item.get("file") or ""
            if not tid or not str(fname).lower().endswith((".html", ".htm")):
                continue
            text, title = load_system_template_body(str(tid))
            if not text:
                logger.warning("skip bankruptcy %s: empty body", tid)
                fail += 1
                continue
            key = template_key_for_bankruptcy(str(tid))
            _, status = index_template_html(
                db,
                template_key=key,
                html=text,
                template_title=str(title or tid),
                force=True,
            )
            logger.info("bankruptcy %s -> %s (%s)", tid, key, status)
            ok += 1

        rows = (
            db.query(DocumentTemplate)
            .filter(DocumentTemplate.source == ADMIN_DRAFT_SOURCE)
            .all()
        )
        for rec in rows:
            if not (rec.content or "").strip():
                fail += 1
                continue
            key = template_key_for_db_template(str(rec.id))
            _, status = index_template_html(
                db,
                template_key=key,
                html=rec.content,
                template_title=rec.title,
                force=True,
            )
            logger.info("db template %s -> %s (%s)", rec.id, key, status)
            ok += 1
    finally:
        db.close()

    logger.info("done ok=%s fail=%s", ok, fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
