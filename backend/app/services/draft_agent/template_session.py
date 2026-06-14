"""Resolve system/user templates for Draft Agent session."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Literal, Optional

from sqlalchemy.orm import Session

from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_execute_service import ensure_catalog
from app.services.draft_template_catalog import content_sha256
from app.services.draft_template_indexer import (
    index_template_html,
    scan_docxtpl_placeholder_occurrences,
    scan_placeholder_occurrences,
)
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot
from app.services.draft_agent.brief_intent import DraftBriefIntent, parse_draft_brief
from app.services.draft_agent.writer import resolve_template_for_draft

logger = logging.getLogger(__name__)

DraftTemplateMode = Literal["catalog_fill", "template_guide", "scratch"]


@dataclass(frozen=True)
class ResolvedDraftTemplate:
    """Template resolution result bound to one draft session."""

    mode: DraftTemplateMode
    template_html: str = ""
    template_label: Optional[str] = None
    template_key: Optional[str] = None
    placeholders: tuple[str, ...] = ()
    field_count: int = 0
    catalog: Optional[TemplateFieldCatalogSnapshot] = None
    brief_intent: Optional[DraftBriefIntent] = None

    @property
    def has_template(self) -> bool:
        """Шаблон найден: fill по полям или guide по структуре."""
        return self.mode in ("catalog_fill", "template_guide") and bool(self.template_html)

    @property
    def skips_legal_tools(self) -> bool:
        """Справочник и практика не нужны — каркас/нормы уже в шаблоне."""
        return self.mode in ("catalog_fill", "template_guide")

    def placeholder_summary(self) -> str:
        if not self.placeholders:
            return ""
        shown = list(self.placeholders[:12])
        tail = len(self.placeholders) - len(shown)
        parts = ", ".join(shown)
        if tail > 0:
            parts += f" … (+{tail})"
        return parts

    def agent_context_block(self) -> str:
        if self.mode == "scratch":
            return (
                "РЕЖИМ: scratch (шаблон не найден).\n"
                "Составь документ с нуля: факты из дела, нормы, практика при споре, расчёты при суммах."
            )
        label = self.template_label or "шаблон"
        if self.mode == "catalog_fill":
            return (
                f"РЕЖИМ: catalog_fill (шаблон «{label}» с плейсхолдерами).\n"
                f"Полей: {self.field_count}. Плейсхолдеры: {self.placeholder_summary() or '—'}.\n"
                "ЗАДАЧА: только подставить значения в поля. Не менять структуру и готовые формулировки.\n"
                "Не вызывай draft_legal_search и draft_court_practice_search.\n"
                "draft_case_search — при необходимости уточнить факт для поля.\n"
                "draft_calculator — при суммах/неустойке; система также подставляет авторасчёт в контекст заполнения."
            )
        return (
            f"РЕЖИМ: template_guide (шаблон «{label}» без размеченных полей).\n"
            "ЗАДАЧА: взять шаблон за основу — сохранить разделы, порядок и стиль; "
            "заменить примерный/пустой текст фактами из дела.\n"
            "Не добавляй новые разделы и не переписывай готовые нормативные блоки шаблона.\n"
            "Не вызывай draft_legal_search и draft_court_practice_search.\n"
            "draft_case_search — собрать факты для адаптации текста под дело.\n"
            "draft_calculator — если в задании есть денежные требования."
        )


def _collect_placeholders_from_catalog(catalog: TemplateFieldCatalogSnapshot) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for spec in catalog.field_specs:
        marker = (spec.marker or "").strip()
        if marker and marker not in seen:
            seen.add(marker)
            out.append(marker)
    return out


def _try_build_field_catalog(
    db: Session,
    *,
    template_key: str,
    raw_html: str,
    label: Optional[str],
    catalog: Optional[TemplateFieldCatalogSnapshot],
) -> tuple[Optional[TemplateFieldCatalogSnapshot], List[str]]:
    placeholders: List[str] = []
    if catalog and catalog.field_specs:
        return catalog, _collect_placeholders_from_catalog(catalog)

    seen: set[str] = set()
    for occ in scan_docxtpl_placeholder_occurrences(raw_html) or scan_placeholder_occurrences(raw_html):
        if occ.marker not in seen:
            seen.add(occ.marker)
            placeholders.append(occ.marker)

    if not placeholders:
        return catalog, []

    indexed, status = index_template_html(
        db,
        template_key=template_key,
        html=raw_html,
        template_title=label or template_key,
        force=True,
    )
    logger.info(
        "[draft_agent.template] indexed key=%s status=%s fields=%s",
        template_key,
        status,
        len(indexed.field_specs) if indexed else 0,
    )
    if indexed and indexed.field_specs:
        return indexed, _collect_placeholders_from_catalog(indexed)
    return catalog, placeholders


def _finalize_template_mode(
    *,
    base_mode: DraftTemplateMode,
    intent: DraftBriefIntent,
    template_key: str,
    label: Optional[str],
) -> DraftTemplateMode:
    effective = intent.effective_template_mode(base_mode)
    if effective != base_mode:
        logger.info(
            "[draft_agent.template] mode override %s -> %s reason=%s key=%s",
            base_mode,
            effective,
            intent.routing_reason or "brief_intent",
            template_key,
        )
    return effective


def resolve_template_session(
    db: Session,
    *,
    ctx: DraftAgentContext,
    user_question: str,
) -> ResolvedDraftTemplate:
    """Resolve template and execution mode from brief + catalog."""
    intent = parse_draft_brief(user_question)
    html, label, template_key = resolve_template_for_draft(
        db,
        template_file_id=ctx.template_file_id,
        template_file_content=ctx.template_file_content,
        user_question=user_question,
    )
    raw_html = (html or "").strip()
    if not raw_html:
        logger.info("[draft_agent.template] no template matched case=%s", ctx.case_id)
        return ResolvedDraftTemplate(mode="scratch", brief_intent=intent)

    key = (template_key or "").strip() or f"adhoc:{content_sha256(raw_html)}"
    catalog = ensure_catalog(
        db,
        template_key=key,
        template_html=raw_html,
        template_label=label,
    )
    catalog, placeholders = _try_build_field_catalog(
        db,
        template_key=key,
        raw_html=raw_html,
        label=label,
        catalog=catalog,
    )

    if catalog and catalog.field_specs:
        base_mode: DraftTemplateMode = "catalog_fill"
        effective = _finalize_template_mode(
            base_mode=base_mode,
            intent=intent,
            template_key=key,
            label=label,
        )
        logger.info(
            "[draft_agent.template] %s key=%s label=%s fields=%s pipeline=%s",
            effective,
            key,
            label,
            len(catalog.field_specs),
            intent.requires_materials_pipeline,
        )
        return ResolvedDraftTemplate(
            mode=effective,
            template_html=raw_html,
            template_label=label,
            template_key=key,
            placeholders=tuple(placeholders),
            field_count=len(catalog.field_specs),
            catalog=catalog,
            brief_intent=intent,
        )

    logger.info(
        "[draft_agent.template] template_guide key=%s label=%s (no indexable placeholders)",
        key,
        label,
    )
    return ResolvedDraftTemplate(
        mode="template_guide",
        template_html=raw_html,
        template_label=label,
        template_key=key,
        placeholders=(),
        field_count=0,
        catalog=None,
        brief_intent=intent,
    )
