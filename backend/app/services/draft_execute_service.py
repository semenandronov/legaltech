"""Оркестрация заполнения шаблона Draft по каталогу полей."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_field_fill import (
    apply_field_values,
    extract_fields_batch,
    extract_fields_unified,
    fields_needing_targeted_retry,
)
from app.services.draft_field_retrieval import (
    retrieve_bulk_document_context,
    retrieve_fields_parallel,
    retrieve_fields_retry_lightweight,
)
from app.services.draft_rag_query import build_bulk_rag_query
from app.services.draft_template_catalog import content_sha256, load_catalog_snapshot
from app.services.draft_template_indexer import index_template_html
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec

logger = logging.getLogger(__name__)


def catalog_from_state(raw: Any) -> Optional[TemplateFieldCatalogSnapshot]:
    if not raw:
        return None
    if isinstance(raw, TemplateFieldCatalogSnapshot):
        return raw
    if isinstance(raw, dict):
        specs = [
            TemplateFieldSpec.from_dict(x)
            for x in (raw.get("field_specs") or [])
            if isinstance(x, dict)
        ]
        return TemplateFieldCatalogSnapshot(
            template_key=str(raw.get("template_key") or ""),
            content_sha256=str(raw.get("content_sha256") or ""),
            field_specs=specs,
            indexed_html=str(raw.get("indexed_html") or ""),
            indexer_version=str(raw.get("indexer_version") or "1"),
        )
    return None


def catalog_to_state_dict(snap: TemplateFieldCatalogSnapshot) -> Dict[str, Any]:
    return {
        "template_key": snap.template_key,
        "content_sha256": snap.content_sha256,
        "field_specs": [s.model_dump() for s in snap.field_specs],
        "indexed_html": snap.indexed_html,
        "indexer_version": snap.indexer_version,
    }


def ensure_catalog(
    db: Session,
    *,
    template_key: Optional[str],
    template_html: str,
    template_label: Optional[str] = None,
    force_reindex: bool = False,
) -> Optional[TemplateFieldCatalogSnapshot]:
    if not template_key or not (template_html or "").strip():
        return None
    sha = content_sha256(template_html)
    if not force_reindex:
        snap = load_catalog_snapshot(db, template_key, require_sha256=sha)
        if snap and snap.field_specs:
            return snap
    snap, status = index_template_html(
        db,
        template_key=template_key,
        html=template_html,
        template_title=template_label or template_key,
        force=force_reindex,
    )
    logger.info("[draft_execute] catalog ensure key=%s status=%s fields=%s", template_key, status, len(snap.field_specs))
    return snap if snap.field_specs else snap


def build_placeholder_fill_plan_from_catalog(
    snap: TemplateFieldCatalogSnapshot,
    status_by_field_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    status_by_field_id = status_by_field_id or {}
    plan: List[Dict[str, Any]] = []
    for spec in snap.field_specs:
        st = status_by_field_id.get(spec.field_id, "missing")
        plan.append(spec.to_placeholder_plan_item(st))
    return plan


def _bulk_fill_enabled() -> bool:
    return bool(getattr(config, "DRAFT_BULK_FILL_ENABLED", True))


def _per_field_fill_enabled() -> bool:
    return bool(getattr(config, "DRAFT_PER_FIELD_RAG_ENABLED", True))


def _targeted_retry_enabled() -> bool:
    return bool(getattr(config, "DRAFT_BULK_TARGETED_RETRY_ENABLED", True))


def execute_catalog_field_fill_bulk(
    *,
    rag_service,
    case_id: str,
    catalog: TemplateFieldCatalogSnapshot,
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
    corpus_size: int = 0,
    user_context: str = "",
    template_label: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Быстрый путь: один RAG по делу → один LLM на все поля → точечный дожим для пустых.
    """
    stats: Dict[str, Any] = {
        "fields_total": len(catalog.field_specs),
        "fields_filled": 0,
        "fields_missing": 0,
        "replacement_ops": 0,
        "used_field_catalog": True,
        "fill_mode": "bulk",
    }
    fields = catalog.field_specs
    if not fields:
        stats["status"] = "no_fields"
        return catalog.indexed_html or "", stats

    bulk_query = build_bulk_rag_query(
        user_context=user_context,
        template_label=template_label,
        field_specs=fields,
    )
    shared_ctx, bulk_meta = retrieve_bulk_document_context(
        rag_service=rag_service,
        case_id=case_id,
        query=bulk_query,
        db=db,
        attached_file_ids=attached_file_ids,
    )
    stats["bulk_rag"] = bulk_meta

    values, confidences = extract_fields_unified(
        fields,
        shared_ctx,
        user_context=user_context,
    )
    stats["bulk_extract_fields"] = sum(1 for v in values.values() if v)

    retry_fields: List[TemplateFieldSpec] = []
    if _targeted_retry_enabled() and _per_field_fill_enabled():
        retry_fields = fields_needing_targeted_retry(fields, values, confidences)
    stats["retry_fields"] = len(retry_fields)

    if retry_fields:
        retry_ctx = shared_ctx
        min_ctx = int(getattr(config, "DRAFT_BULK_RETRY_MIN_SHARED_CHARS", 800) or 800)
        use_light_rag = bool(getattr(config, "DRAFT_BULK_RETRY_LIGHT_RAG_ENABLED", True))
        if len((shared_ctx or "").strip()) < min_ctx and use_light_rag and _per_field_fill_enabled():
            extra = retrieve_fields_retry_lightweight(
                rag_service=rag_service,
                case_id=case_id,
                fields=retry_fields,
                db=db,
                attached_file_ids=attached_file_ids,
            )
            parts = [shared_ctx] if shared_ctx.strip() else []
            for f in retry_fields:
                bit = (extra.get(f.field_id) or "").strip()
                if bit:
                    parts.append(f"[{f.semantic_label or f.field_id}]\n{bit}")
            retry_ctx = "\n\n".join(parts)[:20000]
            stats["retry_mode"] = "light_rag"
        else:
            stats["retry_mode"] = "shared_context_only"

        retry_values, retry_conf = extract_fields_unified(
            retry_fields,
            retry_ctx,
            user_context=user_context,
        )
        for fid, val in retry_values.items():
            if val and str(val).strip():
                values[fid] = val
                confidences[fid] = max(float(retry_conf.get(fid) or 0.0), 0.6)
        stats["retry_filled"] = sum(1 for f in retry_fields if values.get(f.field_id))

    filled_count = sum(1 for v in values.values() if v)
    stats["fields_filled"] = filled_count
    stats["fields_missing"] = len(fields) - filled_count
    stats["field_status"] = {
        f.field_id: ("found_in_case" if values.get(f.field_id) else "missing")
        for f in fields
    }

    html_out, rep_ops = apply_field_values(catalog.indexed_html, values)
    stats["replacement_ops"] = rep_ops
    stats["template_chars"] = len(catalog.indexed_html or "")
    stats["out_chars"] = len(html_out or "")
    stats["status"] = "ok"
    logger.info(
        "[draft_execute] bulk fill case=%s fields=%s filled=%s retry=%s",
        case_id,
        len(fields),
        filled_count,
        len(retry_fields),
    )
    return html_out, stats


def execute_catalog_field_fill_legacy(
    *,
    rag_service,
    case_id: str,
    catalog: TemplateFieldCatalogSnapshot,
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
    corpus_size: int = 0,
    user_context: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Прежний путь: RAG + LLM на каждое поле."""
    stats: Dict[str, Any] = {
        "fields_total": len(catalog.field_specs),
        "fields_filled": 0,
        "fields_missing": 0,
        "replacement_ops": 0,
        "used_field_catalog": True,
        "fill_mode": "per_field",
    }
    if not catalog.field_specs:
        stats["status"] = "no_fields"
        return catalog.indexed_html or "", stats

    rag_results = retrieve_fields_parallel(
        rag_service=rag_service,
        case_id=case_id,
        fields=catalog.field_specs,
        db=db,
        attached_file_ids=attached_file_ids,
        corpus_size=corpus_size,
    )
    rag_by_field: Dict[str, str] = {fid: ctx for fid, (ctx, _meta) in rag_results.items()}

    values = extract_fields_batch(
        catalog.field_specs,
        rag_by_field,
        user_context=user_context,
    )
    filled_count = sum(1 for v in values.values() if v)
    stats["fields_filled"] = filled_count
    stats["fields_missing"] = len(catalog.field_specs) - filled_count

    html_out, rep_ops = apply_field_values(catalog.indexed_html, values)
    stats["replacement_ops"] = rep_ops
    stats["template_chars"] = len(catalog.indexed_html or "")
    stats["out_chars"] = len(html_out or "")
    stats["status"] = "ok"
    return html_out, stats


def execute_catalog_field_fill(
    *,
    rag_service,
    case_id: str,
    catalog: TemplateFieldCatalogSnapshot,
    db: Optional[Session],
    attached_file_ids: Optional[List[str]] = None,
    corpus_size: int = 0,
    user_context: str = "",
    template_label: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Заполнение шаблона по каталогу полей.

    По умолчанию: bulk RAG + unified extract + точечный дожим.
    При DRAFT_BULK_FILL_ENABLED=false — legacy per-field RAG (если включён).
    """
    if not catalog.field_specs:
        return catalog.indexed_html or "", {
            "fields_total": 0,
            "status": "no_fields",
            "used_field_catalog": True,
        }

    if _bulk_fill_enabled():
        return execute_catalog_field_fill_bulk(
            rag_service=rag_service,
            case_id=case_id,
            catalog=catalog,
            db=db,
            attached_file_ids=attached_file_ids,
            corpus_size=corpus_size,
            user_context=user_context,
            template_label=template_label,
        )

    if not _per_field_fill_enabled():
        return catalog.indexed_html or "", {
            "fields_total": len(catalog.field_specs),
            "status": "fill_disabled",
            "used_field_catalog": True,
        }

    return execute_catalog_field_fill_legacy(
        rag_service=rag_service,
        case_id=case_id,
        catalog=catalog,
        db=db,
        attached_file_ids=attached_file_ids,
        corpus_size=corpus_size,
        user_context=user_context,
    )
