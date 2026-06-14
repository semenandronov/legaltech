"""Сборка запросов RAG для Draft (общий контекст по делу)."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from app.services.draft_template_schemas import TemplateFieldSpec

if TYPE_CHECKING:
    from app.services.draft_template_questions import TemplateFillQuestion


def build_bulk_rag_query(
    *,
    user_context: str = "",
    question: str = "",
    template_label: str = "",
    field_specs: Optional[List[TemplateFieldSpec]] = None,
    unique_questions: Optional[List["TemplateFillQuestion"]] = None,
    placeholder_lines: str = "",
    headings: Optional[List[str]] = None,
) -> str:
    """
    Один запрос к RAG: суть задачи + шаблон + уникальные вопросы для заполнения.
    """
    bits: List[str] = []
    ctx = (user_context or question or "").strip()
    if ctx:
        bits.append(ctx[:4000])
    if template_label.strip():
        bits.append(f"Выбранный шаблон: {template_label.strip()}")
    if headings:
        bits.append("Заголовки/блоки в шаблоне: " + "; ".join(headings[:24]))
    if placeholder_lines.strip():
        bits.append("Плейсхолдеры в шаблоне:\n" + placeholder_lines.strip()[:6000])
    elif unique_questions:
        lines = [f"- {q.fill_question}" for q in unique_questions[:48]]
        if lines:
            bits.append("Вопросы для заполнения шаблона:\n" + "\n".join(lines))
    elif field_specs:
        seen: set[str] = set()
        lines: List[str] = []
        for spec in field_specs[:48]:
            fq = (spec.fill_question or spec.what_to_find or spec.semantic_label or spec.marker).strip()
            if not fq or fq in seen:
                continue
            seen.add(fq)
            lines.append(f"- {fq}")
        if lines:
            bits.append("Вопросы для заполнения шаблона:\n" + "\n".join(lines))
    return "\n".join(x for x in bits if x).strip()[:8000]
