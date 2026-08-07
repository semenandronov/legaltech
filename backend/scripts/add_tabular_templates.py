#!/usr/bin/env python3
"""Seed / replace system tabular review templates with the 3 RU DD packs."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.tabular_review import TabularColumnTemplate
from app.services.contract_field_catalog import RU_DD_SCHEMA_TEMPLATES
from app.utils.database import get_db

# Only these three system templates remain for lawyers.
DEFAULT_TEMPLATES = list(RU_DD_SCHEMA_TEMPLATES)
WANTED_NAMES = {t["name"] for t in DEFAULT_TEMPLATES}


def upsert_dd_templates(*, replace_all_system: bool = True) -> None:
    """Upsert the three DD templates; optionally delete other system templates."""
    db = next(get_db())
    try:
        removed = 0
        if replace_all_system:
            stale = (
                db.query(TabularColumnTemplate)
                .filter(
                    TabularColumnTemplate.is_system == True,  # noqa: E712
                    ~TabularColumnTemplate.name.in_(WANTED_NAMES),
                )
                .all()
            )
            for row in stale:
                db.delete(row)
                removed += 1

        added = 0
        updated = 0
        for template_data in DEFAULT_TEMPLATES:
            exists = (
                db.query(TabularColumnTemplate)
                .filter(TabularColumnTemplate.name == template_data["name"])
                .first()
            )
            if exists:
                exists.description = template_data["description"]
                exists.category = template_data["category"]
                exists.tags = template_data["tags"]
                exists.is_system = True
                exists.is_public = True
                exists.is_featured = bool(template_data.get("is_featured", True))
                exists.columns = template_data["columns"]
                updated += 1
                continue

            db.add(
                TabularColumnTemplate(
                    user_id=None,
                    name=template_data["name"],
                    description=template_data["description"],
                    columns=template_data["columns"],
                    is_public=True,
                    is_system=True,
                    is_featured=bool(template_data.get("is_featured", True)),
                    category=template_data["category"],
                    tags=template_data["tags"],
                    usage_count=0,
                    created_at=datetime.utcnow(),
                )
            )
            added += 1

        db.commit()
        print(
            f"DD templates upserted: added={added}, updated={updated}, "
            f"removed_stale_system={removed}, kept={len(DEFAULT_TEMPLATES)}"
        )
        for t in DEFAULT_TEMPLATES:
            print(f"  - {t['name']} ({len(t['columns'])} columns)")
    except Exception as e:
        db.rollback()
        print(f"Error upserting DD templates: {e}")
        raise
    finally:
        db.close()


def add_default_templates() -> None:
    """Backward-compatible entry: always upsert the three DD packs."""
    upsert_dd_templates(replace_all_system=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replace system tabular templates with 3 RU DD packs"
    )
    parser.add_argument(
        "--keep-other-system",
        action="store_true",
        help="Do not delete other system templates (only upsert the 3 DD packs)",
    )
    parser.add_argument(
        "--bankruptcy-only",
        action="store_true",
        help="Deprecated no-op (bankruptcy presets removed; use default upsert)",
    )
    args = parser.parse_args()
    if args.bankruptcy_only:
        print("Note: --bankruptcy-only is deprecated; upserting DD templates instead.")
    upsert_dd_templates(replace_all_system=not args.keep_other_system)
