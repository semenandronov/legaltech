"""Fact coverage assessment for bounded draft retrieval retries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from app.services.draft_pipeline.schemas import DraftTaskPlan, ExtractedFacts

DraftTemplateMode = Literal["catalog_fill", "template_guide", "scratch"]


@dataclass(frozen=True)
class FactGap:
    gap_id: str
    label: str
    suggested_query: str
    priority: int = 1


@dataclass
class CoverageAssessment:
    gaps: List[FactGap] = field(default_factory=list)
    sufficient: bool = True
    score: float = 1.0

    def to_state_list(self) -> List[dict]:
        return [
            {
                "gap_id": g.gap_id,
                "label": g.label,
                "suggested_query": g.suggested_query,
                "priority": g.priority,
            }
            for g in self.gaps
        ]


def _prompt_low(user_prompt: str) -> str:
    return (user_prompt or "").strip().lower()


def _has_inn(identifiers: dict, parties: dict) -> bool:
    blob = " ".join(list(identifiers.values()) + list(parties.values())).lower()
    return bool(re.search(r"\bинн\b", blob) or re.search(r"\d{10,12}", blob))


def _mentions_financials(prompt: str) -> bool:
    low = _prompt_low(prompt)
    return any(
        token in low
        for token in (
            "долг",
            "задолжен",
            "неусто",
            "взыск",
            "оплат",
            "сумм",
            "руб",
            "пен",
            "процент",
        )
    )


def _mentions_partial_payments(prompt: str) -> bool:
    low = _prompt_low(prompt)
    return any(token in low for token in ("частич", "погаш", "оплат", "платёж", "платеж"))


def _mentions_requisites(prompt: str) -> bool:
    low = _prompt_low(prompt)
    return any(token in low for token in ("инн", "огрн", "реквизит", "адрес", "егрюл"))


def _party_count(facts: ExtractedFacts) -> int:
    return len([v for v in (facts.parties or {}).values() if str(v).strip()])


def assess_fact_coverage(
    *,
    user_prompt: str,
    facts: ExtractedFacts,
    task_plan: Optional[DraftTaskPlan] = None,
    template_mode: DraftTemplateMode = "template_guide",
) -> CoverageAssessment:
    """
    Decide whether extracted facts are enough to write the document.

    Returns prioritized gaps for at most one bounded targeted retrieval round.
    """
    prompt = (user_prompt or "").strip()
    gaps: List[FactGap] = []
    plan_type = (task_plan.target_document_type if task_plan else "") or facts.document_type or ""

    if _party_count(facts) < 2:
        gaps.append(
            FactGap(
                gap_id="parties",
                label="Стороны спора",
                suggested_query=f"{prompt[:120]} истец ответчик наименование стороны договор",
                priority=1,
            )
        )

    if _mentions_requisites(prompt) and not _has_inn(facts.identifiers, facts.parties):
        gaps.append(
            FactGap(
                gap_id="requisites",
                label="ИНН/реквизиты сторон",
                suggested_query=f"{prompt[:120]} ИНН ОГРН адрес наименование реквизиты выписка ЕГРЮЛ",
                priority=1,
            )
        )

    if _mentions_financials(prompt) and not facts.amounts:
        gaps.append(
            FactGap(
                gap_id="amounts",
                label="Суммы задолженности",
                suggested_query=f"{prompt[:120]} сумма долг цена договора акт УПД задолженность",
                priority=1,
            )
        )

    if _mentions_financials(prompt):
        terms = facts.penalty_terms
        needs_penalty = "неусто" in _prompt_low(prompt) or "процент" in _prompt_low(prompt)
        if needs_penalty and terms is None:
            gaps.append(
                FactGap(
                    gap_id="penalty_terms",
                    label="Условия неустойки",
                    suggested_query=f"{prompt[:120]} неустойка процент за день срок оплаты условия договора",
                    priority=2,
                )
            )

    if _mentions_partial_payments(prompt) and not facts.financial.partial_payments:
        gaps.append(
            FactGap(
                gap_id="partial_payments",
                label="Частичные оплаты",
                suggested_query=f"{prompt[:120]} платёжное поручение частичная оплата погашение сумма дата",
                priority=2,
            )
        )

    if not facts.dates and any(token in _prompt_low(prompt) for token in ("дата", "срок", "акт", "договор")):
        gaps.append(
            FactGap(
                gap_id="dates",
                label="Ключевые даты",
                suggested_query=f"{prompt[:120]} дата договора акт приёмки срок оплаты",
                priority=3,
            )
        )

    if template_mode == "scratch" and "иск" in _prompt_low(prompt) and not plan_type:
        gaps.append(
            FactGap(
                gap_id="document_type",
                label="Тип документа",
                suggested_query=f"{prompt[:120]} исковое заявление предмет требования",
                priority=3,
            )
        )

    gaps.sort(key=lambda g: g.priority)
    critical = [g for g in gaps if g.priority <= 2]
    sufficient = len(critical) == 0

    total_checks = 6
    failed = len(gaps)
    score = max(0.0, (total_checks - failed) / total_checks)

    return CoverageAssessment(gaps=gaps, sufficient=sufficient, score=score)
