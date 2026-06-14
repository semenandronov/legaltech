"""Заполнение шаблона: параллельный RAG по вопросам + единый LLM-extract."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_calculator_for_fill import attach_calculator_context_for_fill
from app.services.draft_field_fill import apply_field_values
from app.services.draft_field_retrieval import (
    retrieve_fields_parallel,
    retrieve_fields_retry_lightweight,
)
from app.services.draft_template_questions import (
    TemplateFillQuestion,
    build_unique_fill_questions,
    extract_fill_question_answers,
    extract_variable_answers,
    propagate_answers_to_fields,
    questions_needing_retry,
    _is_variable_keyed_questions,
)
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec

logger = logging.getLogger(__name__)


def _context_max_chars() -> int:
    return max(4000, int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 7000) or 7000))


def _per_question_context_budget(question_count: int) -> int:
    total = _context_max_chars()
    if question_count <= 0:
        return total
    return min(600, max(220, total // question_count))


def _targeted_retry_enabled() -> bool:
    return bool(getattr(config, "DRAFT_BULK_TARGETED_RETRY_ENABLED", True))


def _per_field_rag_enabled() -> bool:
    return bool(getattr(config, "DRAFT_PER_FIELD_RAG_ENABLED", True))


def representative_fields_for_questions(
    unique_questions: List[TemplateFillQuestion],
    fields: List[TemplateFieldSpec],
) -> List[TemplateFieldSpec]:
    """Одно поле-представитель на уникальный вопрос (для параллельного RAG)."""
    by_id = {f.field_id: f for f in fields}
    out: List[TemplateFieldSpec] = []
    seen: set[str] = set()
    for q in unique_questions:
        if not q.field_ids:
            continue
        fid = q.field_ids[0]
        if fid in seen:
            continue
        spec = by_id.get(fid)
        if spec is None:
            continue
        out.append(spec)
        seen.add(fid)
    return out


def merge_question_rag_context(
    unique_questions: List[TemplateFillQuestion],
    rag_by_field_id: Dict[str, str],
) -> Tuple[str, Dict[str, Any]]:
    """Склеить per-question RAG-контексты с метками для единого LLM-extract."""
    per_q = _per_question_context_budget(len(unique_questions))
    max_total = _context_max_chars()
    parts: List[str] = []
    with_context = 0

    for q in unique_questions:
        if not q.field_ids:
            continue
        raw = (rag_by_field_id.get(q.field_ids[0]) or "").strip()
        if not raw:
            continue
        label = q.question_key
        if label.startswith("q_"):
            label = q.fill_question
        parts.append(f"[{label}]\n{raw[:per_q]}")
        with_context += 1

    merged = "\n\n".join(parts)[:max_total]
    meta = {
        "mode": "labeled_merge",
        "questions_total": len(unique_questions),
        "questions_with_context": with_context,
        "chars": len(merged),
        "per_question_budget": per_q,
        "status": "ok" if merged else "no_snippets",
    }
    return merged, meta


def _build_auto_defaults(
    unique_questions: List[TemplateFillQuestion],
) -> Dict[str, str]:
    """Детерминированные значения без RAG/LLM (например, дата документа)."""
    keys = {q.question_key for q in unique_questions}
    defaults: Dict[str, str] = {}
    if "doc_date" in keys:
        defaults["doc_date"] = date.today().strftime("%d.%m.%Y")
    return defaults


def overlay_deterministic_answers(
    answers: Dict[str, Optional[str]],
    confidences: Dict[str, float],
    *,
    calculator_variables: Dict[str, str],
    auto_defaults: Dict[str, str],
) -> None:
    """Калькулятор и авто-поля перекрывают LLM (in-place)."""
    for key, val in auto_defaults.items():
        if val and str(val).strip() and not (answers.get(key) or "").strip():
            answers[key] = str(val).strip()
            confidences[key] = max(float(confidences.get(key) or 0.0), 0.9)
    for key, val in calculator_variables.items():
        if val and str(val).strip():
            answers[key] = str(val).strip()
            confidences[key] = max(float(confidences.get(key) or 0.0), 0.95)


def _resolve_docx_path(catalog: TemplateFieldCatalogSnapshot):
    from pathlib import Path

    from app.services.bankruptcy_templates import get_docx_path
    from app.services.draft_template_keys import parse_template_key

    if catalog.docx_file:
        draft_dir = Path(__file__).resolve().parent.parent / "templates" / "draft"
        path = draft_dir / catalog.docx_file
        if path.is_file():
            return path
    kind, ident = parse_template_key(catalog.template_key)
    if kind == "bankruptcy" and ident:
        return get_docx_path(ident)
    return None


def _is_docxtpl_catalog(catalog: TemplateFieldCatalogSnapshot) -> bool:
    if (catalog.engine or "").strip().lower() == "docxtpl":
        return True
    return bool(catalog.field_specs) and all(
        (s.variable or "").strip() for s in catalog.field_specs
    )


def finalize_catalog_render(
    catalog: TemplateFieldCatalogSnapshot,
    unique_questions: List[TemplateFillQuestion],
    answers: Dict[str, Optional[str]],
    values: Dict[str, Optional[str]],
) -> Tuple[str, Dict[str, Any]]:
    """docxtpl или HTML spans + fill_context для stats."""
    render_stats: Dict[str, Any] = {}
    fill_context: Dict[str, str] = {}
    for q in unique_questions:
        val = answers.get(q.question_key)
        if val and str(val).strip():
            fill_context[q.question_key] = str(val).strip()
    render_stats["fill_context"] = fill_context

    docx_path = _resolve_docx_path(catalog) if _is_docxtpl_catalog(catalog) else None
    if docx_path and fill_context:
        from app.services.draft_docxtpl_service import render_docxtpl, rendered_docx_to_html

        try:
            docx_bytes = render_docxtpl(docx_path, fill_context)
            html_out = rendered_docx_to_html(docx_bytes)
            render_stats["replacement_ops"] = len(fill_context)
            render_stats["render_engine"] = "docxtpl"
            return html_out, render_stats
        except Exception as e:
            logger.warning("[draft_fill_pipeline] docxtpl render failed: %s — HTML fallback", e)

    html_out, rep_ops = apply_field_values(catalog.indexed_html, values)
    render_stats["replacement_ops"] = rep_ops
    render_stats["render_engine"] = "html_spans"
    return html_out, render_stats


def execute_parallel_unified_fill(
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
    Приоритет: запрос юриста → параллельный RAG по уникальным вопросам → один LLM → дожим.
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
        "fill_mode": "parallel_unified",
        "template_label": (template_label or "").strip() or None,
    }
    if not fields:
        stats["status"] = "no_fields"
        return catalog.indexed_html or "", stats

    # 1. Калькулятор и факты из запроса юриста (без RAG)
    fill_user_context, calc_meta = attach_calculator_context_for_fill(
        user_context=user_context,
        rag_context="",
        field_specs=fields,
    )
    stats["calculator"] = dict(calc_meta)
    calculator_variables: Dict[str, str] = dict(calc_meta.get("calculator_variables") or {})
    auto_defaults = _build_auto_defaults(unique_questions)

    # 2. Параллельный RAG — один поиск на уникальный вопрос
    rep_fields = representative_fields_for_questions(unique_questions, fields)
    rag_results: Dict[str, str] = {}
    parallel_meta: Dict[str, Any] = {"fields_requested": len(rep_fields)}
    if rep_fields and _per_field_rag_enabled():
        raw_results = retrieve_fields_parallel(
            rag_service=rag_service,
            case_id=case_id,
            fields=rep_fields,
            db=db,
            attached_file_ids=attached_file_ids,
            corpus_size=corpus_size,
        )
        rag_results = {fid: (ctx or "").strip() for fid, (ctx, _m) in raw_results.items()}
        parallel_meta["fields_with_snippets"] = sum(1 for v in rag_results.values() if v)
    else:
        parallel_meta["status"] = "skipped"
    stats["parallel_rag"] = parallel_meta

    merged_ctx, merge_meta = merge_question_rag_context(unique_questions, rag_results)
    stats["rag_merge"] = merge_meta

    # 3. Калькулятор с материалами дела, если первый проход не дал цифр
    if not calculator_variables and merged_ctx.strip():
        fill_user_context, calc_meta_rag = attach_calculator_context_for_fill(
            user_context=user_context,
            rag_context=merged_ctx,
            field_specs=fields,
        )
        stats["calculator"].update(calc_meta_rag)
        if calc_meta_rag.get("calculator_variables"):
            calculator_variables = dict(calc_meta_rag["calculator_variables"])

    # 4. Единый LLM-extract
    use_structured = _is_variable_keyed_questions(unique_questions)
    if use_structured:
        answers, confidences = extract_variable_answers(
            unique_questions,
            merged_ctx,
            user_context=fill_user_context,
        )
        stats["extract_mode"] = "structured_variables"
    else:
        answers, confidences = extract_fill_question_answers(
            unique_questions,
            merged_ctx,
            user_context=fill_user_context,
        )
        stats["extract_mode"] = "question_unified"

    overlay_deterministic_answers(
        answers,
        confidences,
        calculator_variables=calculator_variables,
        auto_defaults=auto_defaults,
    )
    stats["questions_filled"] = sum(1 for v in answers.values() if v)

    # 5. Точечный дожим пустых вопросов
    retry_questions: List[TemplateFillQuestion] = []
    if _targeted_retry_enabled():
        retry_questions = questions_needing_retry(unique_questions, answers, confidences)
    stats["retry_questions"] = len(retry_questions)

    if retry_questions and _per_field_rag_enabled():
        retry_fields = [
            next(s for s in fields if s.field_id == q.field_ids[0])
            for q in retry_questions
            if q.field_ids
        ]
        extra = retrieve_fields_retry_lightweight(
            rag_service=rag_service,
            case_id=case_id,
            fields=retry_fields,
            db=db,
            attached_file_ids=attached_file_ids,
        )
        retry_parts = [merged_ctx] if merged_ctx.strip() else []
        for q, f in zip(retry_questions, retry_fields):
            bit = (extra.get(f.field_id) or "").strip()
            if bit:
                label = q.question_key if not q.question_key.startswith("q_") else q.fill_question
                retry_parts.append(f"[{label}]\n{bit}")
        retry_ctx = "\n\n".join(retry_parts)[:_context_max_chars()]
        stats["retry_mode"] = "light_rag"

        retry_answers, retry_conf = (
            extract_variable_answers(retry_questions, retry_ctx, user_context=fill_user_context)
            if use_structured
            else extract_fill_question_answers(
                retry_questions, retry_ctx, user_context=fill_user_context
            )
        )
        for qk, val in retry_answers.items():
            if val and str(val).strip():
                answers[qk] = val
                confidences[qk] = max(float(retry_conf.get(qk) or 0.0), 0.65)
        overlay_deterministic_answers(
            answers,
            confidences,
            calculator_variables=calculator_variables,
            auto_defaults=auto_defaults,
        )
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

    html_out, render_stats = finalize_catalog_render(catalog, unique_questions, answers, values)
    stats.update(render_stats)
    stats["template_chars"] = len(catalog.indexed_html or "")
    stats["out_chars"] = len(html_out or "")
    stats["status"] = "ok"
    logger.info(
        "[draft_fill_pipeline] parallel fill case=%s questions=%s/%s fields=%s/%s retry=%s",
        case_id,
        stats["questions_filled"],
        len(unique_questions),
        filled_count,
        len(fields),
        len(retry_questions),
    )
    return html_out, stats
