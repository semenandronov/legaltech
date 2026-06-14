"""Build writer instruction from extracted facts and user brief."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.services.draft_agent.brief_intent import DraftBriefIntent
from app.services.draft_pipeline.schemas import ExtractedFacts


def apply_brief_to_facts(facts: ExtractedFacts, intent: Optional[DraftBriefIntent]) -> ExtractedFacts:
    """Seed parties and document type from lawyer brief before RAG consolidation gaps."""
    if intent is None:
        return facts

    parties = dict(facts.parties or {})
    for role, name in (intent.parties_from_brief or {}).items():
        if name and not str(parties.get(role) or "").strip():
            parties[role] = name

    doc_type = (facts.document_type or intent.document_type_hint or "").strip()
    if not doc_type and intent.document_type_hint:
        doc_type = intent.document_type_hint

    if parties == (facts.parties or {}) and doc_type == (facts.document_type or ""):
        return facts

    return facts.model_copy(update={"parties": parties, "document_type": doc_type})


def build_verified_amounts_block(facts: ExtractedFacts) -> str:
    """Authoritative calculator output — LLM must use these numbers verbatim."""
    verified = facts.financial.verified
    if not verified:
        return ""
    lines = [
        "КАЛЬКУЛЯТОР (единственный источник цифр — не пересчитывать и не менять):",
        f"- Основной долг: {verified.principal_outstanding}",
        f"- Неустойка: {verified.penalty_amount}",
        f"- Итого к взысканию: {verified.total_claim}",
    ]
    if verified.state_duty:
        lines.append(f"- Госпошлина: {verified.state_duty}")
    lines.extend(
        [
            f"- Период неустойки: {verified.penalty_start_date} — {verified.penalty_end_date} "
            f"({verified.penalty_days} дн.)",
        ]
    )
    if verified.computation_trace:
        lines.append(f"- Трассировка: {verified.computation_trace[:1200]}")
    return "\n".join(lines)


def financial_claim_writer_notes(intent: Optional[DraftBriefIntent]) -> str:
    if intent is None or not intent.requires_financial_calc:
        return ""
    return (
        "ОБЯЗАТЕЛЬНО для иска с денежными требованиями:\n"
        "- Заполни блок «Просительная часть»: взыскать основной долг и неустойку "
        "(суммы — только из верифицированного расчёта).\n"
        "- Госпошлину укажи в «Цена иска» — только из калькулятора.\n"
        "- Укажи истца и ответчика из паспорта фактов (не оставляй плейсхолдеры).\n"
        "- Для ООО указывай ОГРН (не ОГРНИП), если реквизит есть в материалах.\n"
        "- В правовом обосновании ссылайся на ст. 309, 310, 393, 395 ГК РФ, "
        "если иные нормы не указаны в материалах."
    )


def build_document_instruction(
    *,
    user_question: str,
    facts: ExtractedFacts,
    rag_context: str = "",
    extra_notes: Optional[str] = None,
    brief_intent: Optional[DraftBriefIntent] = None,
) -> str:
    """Structured instruction for template_guide / scratch writers."""
    parts = [
        "ЗАДАНИЕ ЮРИСТА:",
        (user_question or "").strip(),
        "",
        "ПАСПОРТ ФАКТОВ (единственный источник правды):",
        json.dumps(facts.to_prompt_json(), ensure_ascii=False, indent=2),
    ]

    verified = facts.financial.verified
    amounts_block = build_verified_amounts_block(facts)
    if amounts_block:
        parts.extend(["", amounts_block])
    elif verified:
        parts.extend(
            [
                "",
                "ВЕРИФИЦИРОВАННЫЙ РАСЧЁТ (использовать в документе как есть):",
                f"- Основной долг: {verified.principal_outstanding}",
                f"- Неустойка: {verified.penalty_amount}",
                f"- Итого к взысканию: {verified.total_claim}",
                f"- Период неустойки: {verified.penalty_start_date} — {verified.penalty_end_date} ({verified.penalty_days} дн.)",
            ]
        )
        if verified.computation_trace:
            parts.append(f"- Трассировка: {verified.computation_trace[:1500]}")

    rag = (rag_context or "").strip()
    if rag:
        parts.extend(["", "ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ИЗ МАТЕРИАЛОВ ДЕЛА:", rag[:12000]])

    financial_notes = financial_claim_writer_notes(brief_intent)
    if financial_notes:
        parts.extend(["", financial_notes])

    if extra_notes:
        parts.extend(["", "ПРИМЕЧАНИЯ:", extra_notes.strip()])

    parts.extend(
        [
            "",
            "ПРАВИЛА:",
            "- Используй только факты выше; отсутствующие данные — маркер [поле].",
            "- Не пересчитывай неустойку, если есть верифицированный расчёт.",
            "- Сохрани структуру шаблона (если передан отдельно).",
            "- Просительная часть должна содержать конкретные суммы, если расчёт верифицирован.",
        ]
    )
    return "\n".join(parts)


def merge_extracted_facts(base: ExtractedFacts, incoming: ExtractedFacts) -> ExtractedFacts:
    """Merge two fact passports, preferring non-empty incoming values."""

    def _merge_dict(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, str]:
        out = dict(a or {})
        for k, v in (b or {}).items():
            if str(v).strip():
                out[k] = str(v).strip()
        return out

    parties = _merge_dict(base.parties, incoming.parties)
    amounts = _merge_dict(base.amounts, incoming.amounts)
    dates = _merge_dict(base.dates, incoming.dates)
    identifiers = _merge_dict(base.identifiers, incoming.identifiers)
    other = _merge_dict(base.other, incoming.other)

    financial = base.financial
    if incoming.financial.verified and not financial.verified:
        financial = incoming.financial
    elif incoming.financial.partial_payments and not financial.partial_payments:
        financial = incoming.financial

    penalty_terms = base.penalty_terms
    if incoming.penalty_terms is not None:
        if penalty_terms is None:
            penalty_terms = incoming.penalty_terms
        else:
            merged = penalty_terms.model_dump()
            for key, val in incoming.penalty_terms.model_dump().items():
                if val not in (None, "", [], 0):
                    merged[key] = val
            from app.services.draft_pipeline.schemas import PenaltyTerms

            penalty_terms = PenaltyTerms.model_validate(merged)

    doc_type = (incoming.document_type or base.document_type or "").strip()

    return ExtractedFacts(
        document_type=doc_type,
        parties=parties,
        amounts=amounts,
        dates=dates,
        identifiers=identifiers,
        other=other,
        financial=financial,
        penalty_terms=penalty_terms,
    )


def build_chat_summary(
    *,
    document_title: str,
    document_id: str,
    case_id: str,
    fill_mode: str,
    coverage_gaps: Optional[list] = None,
    fill_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """User-visible chat response after document creation."""
    editor_path = f"/cases/{case_id}/editor/{document_id}"
    lines = [f'✅ Документ «{document_title}» создан.', f"Открыть в редакторе: {editor_path}"]

    if fill_mode == "catalog_fill" and fill_stats:
        filled = fill_stats.get("fields_filled")
        total = fill_stats.get("fields_total")
        if filled is not None and total is not None:
            lines.append(f"Заполнено полей: {filled}/{total}.")

    gaps = coverage_gaps or []
    if gaps:
        labels = [str(g.get("label") or g.get("gap_id") or "") for g in gaps if isinstance(g, dict)]
        labels = [x for x in labels if x]
        if labels:
            lines.append(
                "Не удалось подтвердить в материалах: "
                + ", ".join(labels[:5])
                + ". В документе отмечены квадратными скобками."
            )

    return "\n".join(lines)
