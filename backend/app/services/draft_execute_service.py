"""Оркестрация заполнения шаблона Draft по каталогу полей."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_calculator_for_fill import attach_calculator_context_for_fill
from app.services.draft_field_fill import (
    apply_field_values,
    extract_fields_batch,
)
from app.services.draft_template_questions import (
    build_unique_fill_questions,
    extract_fill_question_answers,
    extract_variable_answers,
    propagate_answers_to_fields,
    questions_needing_retry,
    _is_variable_keyed_questions,
)
from app.services.draft_field_retrieval import (
    retrieve_bulk_document_context,
    retrieve_fields_parallel,
    retrieve_fields_retry_lightweight,
)
from app.services.draft_fill_pipeline import execute_parallel_unified_fill
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
            engine=str(raw.get("engine") or "html"),
            docx_file=str(raw.get("docx_file") or ""),
        )
    return None


def catalog_to_state_dict(snap: TemplateFieldCatalogSnapshot) -> Dict[str, Any]:
    return {
        "template_key": snap.template_key,
        "content_sha256": snap.content_sha256,
        "field_specs": [s.model_dump() for s in snap.field_specs],
        "indexed_html": snap.indexed_html,
        "indexer_version": snap.indexer_version,
        "engine": snap.engine,
        "docx_file": snap.docx_file,
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
    indexer_version = str(getattr(config, "DRAFT_TEMPLATE_INDEXER_VERSION", "3") or "3")
    if not force_reindex:
        snap = load_catalog_snapshot(db, template_key, require_sha256=sha)
        if snap and snap.field_specs and str(snap.indexer_version or "") == indexer_version:
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


def _fill_strategy() -> str:
    raw = str(getattr(config, "DRAFT_FILL_STRATEGY", "parallel") or "parallel").strip().lower()
    if raw in ("parallel", "bulk", "per_field", "legacy"):
        return "per_field" if raw == "legacy" else raw
    return "parallel"


def _bulk_fill_enabled() -> bool:
    strategy = _fill_strategy()
    if strategy == "bulk":
        return True
    if strategy in ("parallel", "per_field"):
        return False
    return bool(getattr(config, "DRAFT_BULK_FILL_ENABLED", True))


def _per_field_fill_enabled() -> bool:
    return bool(getattr(config, "DRAFT_PER_FIELD_RAG_ENABLED", True))


def _targeted_retry_enabled() -> bool:
    return bool(getattr(config, "DRAFT_BULK_TARGETED_RETRY_ENABLED", True))


def _is_docxtpl_catalog(catalog: TemplateFieldCatalogSnapshot) -> bool:
    if (catalog.engine or "").strip().lower() == "docxtpl":
        return True
    return bool(catalog.field_specs) and all(
        (s.variable or "").strip() for s in catalog.field_specs
    )


def _resolve_docx_path(catalog: TemplateFieldCatalogSnapshot) -> Optional[Path]:
    from app.services.draft_template_keys import parse_template_key
    from app.services.bankruptcy_templates import get_docx_path

    if catalog.docx_file:
        draft_dir = Path(__file__).resolve().parent.parent / "templates" / "draft"
        path = draft_dir / catalog.docx_file
        if path.is_file():
            return path
    kind, ident = parse_template_key(catalog.template_key)
    if kind == "bankruptcy" and ident:
        return get_docx_path(ident)
    return None


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
    Вопросы шаблона → один RAG → LLM на уникальные вопросы → подстановка во все вхождения.
    """
    fields = catalog.field_specs
    unique_questions = build_unique_fill_questions(fields)
    stats: Dict[str, Any] = {
        "fields_total": len(fields),
        "questions_total": len(unique_questions),
        "fields_filled": 0,
        "questions_filled": 0,
        "fields_missing": 0,
        "replacement_ops": 0,
        "used_field_catalog": True,
        "fill_mode": "question_bulk",
    }
    if not fields:
        stats["status"] = "no_fields"
        return catalog.indexed_html or "", stats

    bulk_query = build_bulk_rag_query(
        user_context=user_context,
        template_label=template_label,
        field_specs=fields,
        unique_questions=unique_questions,
    )
    shared_ctx, bulk_meta = retrieve_bulk_document_context(
        rag_service=rag_service,
        case_id=case_id,
        query=bulk_query,
        db=db,
        attached_file_ids=attached_file_ids,
    )
    stats["bulk_rag"] = bulk_meta

    fill_user_context, calc_meta = attach_calculator_context_for_fill(
        user_context=user_context,
        rag_context=shared_ctx,
        field_specs=fields,
    )
    stats["calculator"] = calc_meta

    use_structured = _is_variable_keyed_questions(unique_questions)
    if use_structured:
        answers, confidences = extract_variable_answers(
            unique_questions,
            shared_ctx,
            user_context=fill_user_context,
        )
        stats["extract_mode"] = "structured_variables"
    else:
        answers, confidences = extract_fill_question_answers(
            unique_questions,
            shared_ctx,
            user_context=fill_user_context,
        )
        stats["extract_mode"] = "question_bulk"
    stats["questions_filled"] = sum(1 for v in answers.values() if v)

    retry_questions = []
    if _targeted_retry_enabled():
        retry_questions = questions_needing_retry(unique_questions, answers, confidences)
    stats["retry_questions"] = len(retry_questions)

    if retry_questions:
        retry_ctx = shared_ctx
        min_ctx = int(getattr(config, "DRAFT_BULK_RETRY_MIN_SHARED_CHARS", 800) or 800)
        use_light_rag = bool(getattr(config, "DRAFT_BULK_RETRY_LIGHT_RAG_ENABLED", True))
        if len((shared_ctx or "").strip()) < min_ctx and use_light_rag and _per_field_fill_enabled():
            from app.services.draft_template_schemas import TemplateFieldSpec

            retry_fields = [
                next(s for s in fields if s.field_id == q.field_ids[0])
                for q in retry_questions
            ]
            extra = retrieve_fields_retry_lightweight(
                rag_service=rag_service,
                case_id=case_id,
                fields=retry_fields,
                db=db,
                attached_file_ids=attached_file_ids,
            )
            parts = [shared_ctx] if shared_ctx.strip() else []
            for q, f in zip(retry_questions, retry_fields):
                bit = (extra.get(f.field_id) or "").strip()
                if bit:
                    parts.append(f"[{q.fill_question}]\n{bit}")
            retry_ctx = "\n\n".join(parts)[
                : max(4000, int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 7000) or 7000))
            ]
            stats["retry_mode"] = "light_rag"
        else:
            stats["retry_mode"] = "shared_context_only"

        retry_answers, retry_conf = (
            extract_variable_answers(retry_questions, retry_ctx, user_context=fill_user_context)
            if use_structured
            else extract_fill_question_answers(retry_questions, retry_ctx, user_context=fill_user_context)
        )
        for qk, val in retry_answers.items():
            if val and str(val).strip():
                answers[qk] = val
                confidences[qk] = max(float(retry_conf.get(qk) or 0.0), 0.6)
        stats["retry_filled"] = sum(1 for q in retry_questions if answers.get(q.question_key))
        stats["questions_filled"] = sum(1 for v in answers.values() if v)

    values, _field_conf = propagate_answers_to_fields(fields, answers, confidences)
    filled_count = sum(1 for v in values.values() if v)
    stats["fields_filled"] = filled_count
    stats["fields_missing"] = len(fields) - filled_count
    stats["field_status"] = {
        f.field_id: ("found_in_case" if values.get(f.field_id) else "missing")
        for f in fields
    }

    fill_context: Dict[str, str] = {}
    for q in unique_questions:
        val = answers.get(q.question_key)
        if val and str(val).strip():
            fill_context[q.question_key] = str(val).strip()
    stats["fill_context"] = fill_context

    docx_path = _resolve_docx_path(catalog) if _is_docxtpl_catalog(catalog) else None
    if docx_path and fill_context:
        from app.services.draft_docxtpl_service import render_docxtpl, rendered_docx_to_html

        try:
            docx_bytes = render_docxtpl(docx_path, fill_context)
            html_out = rendered_docx_to_html(docx_bytes)
            stats["replacement_ops"] = len(fill_context)
            stats["render_engine"] = "docxtpl"
        except Exception as e:
            logger.warning("[draft_execute] docxtpl render failed: %s — fallback to HTML spans", e)
            html_out, rep_ops = apply_field_values(catalog.indexed_html, values)
            stats["replacement_ops"] = rep_ops
            stats["render_engine"] = "html_spans_fallback"
    else:
        html_out, rep_ops = apply_field_values(catalog.indexed_html, values)
        stats["replacement_ops"] = rep_ops
        stats["render_engine"] = "html_spans"
    stats["template_chars"] = len(catalog.indexed_html or "")
    stats["out_chars"] = len(html_out or "")
    stats["status"] = "ok"
    logger.info(
        "[draft_execute] question fill case=%s questions=%s/%s fields=%s/%s retry=%s",
        case_id,
        stats["questions_filled"],
        len(unique_questions),
        filled_count,
        len(fields),
        len(retry_questions),
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

    По умолчанию (DRAFT_FILL_STRATEGY=parallel): параллельный RAG + unified extract.
    bulk — один общий RAG; per_field — legacy RAG+LLM на каждое поле.
    """
    if not catalog.field_specs:
        return catalog.indexed_html or "", {
            "fields_total": 0,
            "status": "no_fields",
            "used_field_catalog": True,
        }

    strategy = _fill_strategy()
    if strategy == "parallel":
        return execute_parallel_unified_fill(
            rag_service=rag_service,
            case_id=case_id,
            catalog=catalog,
            db=db,
            attached_file_ids=attached_file_ids,
            corpus_size=corpus_size,
            user_context=user_context,
            template_label=template_label,
        )

    if strategy == "per_field":
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
