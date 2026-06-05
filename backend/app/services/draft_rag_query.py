"""Сборка запросов RAG для Draft (общий контекст по делу)."""
from __future__ import annotations

from typing import List, Optional

from app.services.draft_template_schemas import TemplateFieldSpec


def build_bulk_rag_query(
    *,
    user_context: str = "",
    question: str = "",
    template_label: str = "",
    field_specs: Optional[List[TemplateFieldSpec]] = None,
    placeholder_lines: str = "",
    headings: Optional[List[str]] = None,
) -> str:
    """
    Один запрос к RAG: суть задачи + шаблон + все поля/плейсхолдеры.

    Используется для bulk-fill и для этапа плана (generate_draft_plan).
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
    elif field_specs:
        lines: List[str] = []
        for spec in field_specs[:48]:
            label = (spec.semantic_label or spec.marker or spec.field_id).strip()
            hint = (spec.what_to_find or spec.retrieval_query or "").strip()
            if hint:
                lines.append(f"- {label}: {hint}")
            elif label:
                lines.append(f"- {label}")
        if lines:
            bits.append("Поля шаблона для заполнения:\n" + "\n".join(lines))
    return "\n".join(x for x in bits if x).strip()[:8000]
