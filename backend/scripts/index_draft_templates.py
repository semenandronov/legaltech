#!/usr/bin/env python3
"""Backfill draft_template_field_catalog for bankruptcy HTML and admin DB templates."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# backend/ on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _print_audit(audit) -> None:
    print(f"\n{'=' * 72}")
    print(f"Шаблон: {audit.template_title}")
    print(f"Ключ:   {audit.template_key}")
    print(f"Полей: {audit.occurrences} → уникальных вопросов: {audit.unique_questions}")
    for i, q in enumerate(audit.questions, 1):
        print(f"  {i:2}. {q}")
    if audit.warnings:
        print("  ⚠ Предупреждения:")
        for w in audit.warnings:
            print(f"     - {w}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Индексация Draft-шаблонов (вопросы v2)")
    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Путь для JSON-отчёта по вопросам",
    )
    parser.add_argument(
        "--template-id",
        type=str,
        default="",
        help="Индексировать только один bankruptcy template id",
    )
    args = parser.parse_args()

    from app.models.document_template import DocumentTemplate
    from app.services.bankruptcy_templates import _load_manifest_raw, load_system_template_body
    from app.services.draft_admin_template_service import ADMIN_DRAFT_SOURCE
    from app.services.draft_template_indexer import index_template_html
    from app.services.draft_template_keys import template_key_for_bankruptcy, template_key_for_db_template
    from app.services.draft_template_questions import audit_template_questions
    from app.utils.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    ok = 0
    fail = 0
    audits = []
    try:
        for item in _load_manifest_raw():
            if not isinstance(item, dict):
                continue
            tid = item.get("id")
            fname = item.get("file") or ""
            if not tid or not str(fname).lower().endswith((".html", ".htm")):
                continue
            from app.services.bankruptcy_templates import get_manifest_placeholders

            if not get_manifest_placeholders(str(tid)):
                logger.warning(
                    "skip bankruptcy %s: нет placeholders в manifest.json",
                    tid,
                )
                fail += 1
                continue
            if args.template_id and str(tid) != args.template_id:
                continue
            text, title = load_system_template_body(str(tid))
            if not text:
                logger.warning("skip bankruptcy %s: empty body", tid)
                fail += 1
                continue
            key = template_key_for_bankruptcy(str(tid))
            snap, status = index_template_html(
                db,
                template_key=key,
                html=text,
                template_title=str(title or tid),
                force=True,
            )
            audit = audit_template_questions(
                template_key=key,
                template_title=str(title or tid),
                specs=snap.field_specs,
            )
            audits.append(audit)
            _print_audit(audit)
            logger.info(
                "bankruptcy %s -> %s (%s) fields=%s questions=%s",
                tid,
                key,
                status,
                audit.occurrences,
                audit.unique_questions,
            )
            ok += 1

        if not args.template_id:
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
                snap, status = index_template_html(
                    db,
                    template_key=key,
                    html=rec.content,
                    template_title=rec.title,
                    force=True,
                )
                audit = audit_template_questions(
                    template_key=key,
                    template_title=str(rec.title or rec.id),
                    specs=snap.field_specs,
                )
                audits.append(audit)
                _print_audit(audit)
                logger.info("db template %s -> %s (%s)", rec.id, key, status)
                ok += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "template_key": a.template_key,
                "template_title": a.template_title,
                "occurrences": a.occurrences,
                "unique_questions": a.unique_questions,
                "questions": list(a.questions),
                "warnings": list(a.warnings),
            }
            for a in audits
        ]
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("report saved: %s", report_path)

    logger.info("done ok=%s fail=%s", ok, fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
