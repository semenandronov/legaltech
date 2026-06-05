"""CRUD каталога полей шаблона Draft."""
from __future__ import annotations

import hashlib
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.draft_template_field_catalog import DraftTemplateFieldCatalog
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec

logger = logging.getLogger(__name__)


def content_sha256(html: str) -> str:
    return hashlib.sha256((html or "").encode("utf-8")).hexdigest()


def load_catalog_snapshot(
    db: Session,
    template_key: str,
    *,
    require_sha256: Optional[str] = None,
) -> Optional[TemplateFieldCatalogSnapshot]:
    if not template_key or not str(template_key).strip():
        return None
    row = (
        db.query(DraftTemplateFieldCatalog)
        .filter(DraftTemplateFieldCatalog.template_key == template_key.strip())
        .first()
    )
    if not row:
        return None
    if require_sha256 and row.content_sha256 != require_sha256:
        logger.info(
            "[draft_template_catalog] stale catalog template_key=%s sha=%s != %s",
            template_key,
            row.content_sha256,
            require_sha256,
        )
        return None
    return TemplateFieldCatalogSnapshot.from_db_row(row)


def upsert_catalog(
    db: Session,
    *,
    template_key: str,
    html: str,
    field_specs: List[TemplateFieldSpec],
    indexed_html: str,
    indexer_version: str,
) -> TemplateFieldCatalogSnapshot:
    key = template_key.strip()
    sha = content_sha256(html)
    specs_json = [s.model_dump() for s in field_specs]
    row = (
        db.query(DraftTemplateFieldCatalog)
        .filter(DraftTemplateFieldCatalog.template_key == key)
        .first()
    )
    if row:
        row.content_sha256 = sha
        row.field_specs = specs_json
        row.indexed_html = indexed_html
        row.indexer_version = indexer_version
    else:
        row = DraftTemplateFieldCatalog(
            template_key=key,
            content_sha256=sha,
            field_specs=specs_json,
            indexed_html=indexed_html,
            indexer_version=indexer_version,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "[draft_template_catalog] upsert template_key=%s fields=%s sha=%s",
        key,
        len(field_specs),
        sha[:12],
    )
    return TemplateFieldCatalogSnapshot.from_db_row(row)


def delete_catalog(db: Session, template_key: str) -> bool:
    row = (
        db.query(DraftTemplateFieldCatalog)
        .filter(DraftTemplateFieldCatalog.template_key == template_key.strip())
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
