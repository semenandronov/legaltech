"""Second-pass document completion: gap detection + LLM supplementation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.draft_agent.review import review_draft_html
from app.services.draft_pipeline.schemas import ExtractedFacts


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _prayer_section_html(html: str) -> str:
    """Extract prayer section text (heading through next major section or end)."""
    source = html or ""
    m = re.search(
        r"(<h2[^>]*>\s*просительн\w*[^<]*</h2>.*?)(?=<h2[^>]*>|$)",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1)
    m = re.search(
        r"(просительн\w*.{0,1200})",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def _prayer_has_actionable_demands(html: str) -> bool:
    block = _prayer_section_html(html).lower()
    if not block:
        return False
    if re.search(r"\[формулировка\s+требован", block):
        return False
    if re.search(r"<li[^>]*>\s*</li>", block):
        return False
    if "прошу суд" in block or "прошу" in block:
        if re.search(r"взыск", block) and re.search(r"\d", block):
            return True
        if re.search(r"<li[^>]*>[^<]*взыск[^<]*\d", block, flags=re.IGNORECASE):
            return True
    return False


@dataclass(frozen=True)
class DocumentCompletionPlan:
    """What the second LLM pass must fix."""

    run_completion: bool
    gap_labels: List[str] = field(default_factory=list)
    financial_claim: bool = False

    @property
    def summary(self) -> str:
        if not self.gap_labels:
            return "финальная проверка и дозаполнение"
        return "; ".join(self.gap_labels[:8])


def build_document_completion_plan(
    html: str,
    *,
    facts: ExtractedFacts,
    financial_claim: bool,
) -> DocumentCompletionPlan:
    """
    Decide whether second LLM pass is required and list gaps to fix.
    Financial claims always get a completion pass (просительная + суммы из калькулятора).
    """
    verified = facts.financial.verified
    expected_amounts: List[str] = []
    if verified:
        for val in (
            verified.principal_outstanding,
            verified.penalty_amount,
            verified.total_claim,
            verified.state_duty,
        ):
            if val:
                expected_amounts.append(str(val))

    lint = review_draft_html(
        html,
        expected_amounts=expected_amounts or None,
        financial_claim=financial_claim,
        verified_penalty=str(verified.penalty_amount) if verified else None,
        verified_total=str(verified.total_claim) if verified else None,
        verified_state_duty=str(verified.state_duty) if verified else None,
    )

    gaps: List[str] = []
    issue_labels = {
        "prayer_section_unfilled": "просительная часть не заполнена",
        "penalty_amount_missing": "в тексте нет суммы неустойки из калькулятора",
        "total_claim_missing": "в тексте нет итоговой суммы иска из калькулятора",
        "state_duty_missing": "не указана госпошлина из калькулятора",
    }
    for issue in lint.get("issues") or []:
        key = str(issue).split(":")[0]
        gaps.append(issue_labels.get(key, str(issue)))

    if financial_claim and not _prayer_has_actionable_demands(html):
        if "просительная часть не заполнена" not in gaps:
            gaps.append("просительная часть не заполнена")

    if verified and verified.state_duty:
        duty_digits = _digits_only(verified.state_duty)
        if len(duty_digits) >= 3 and duty_digits not in _digits_only(html):
            if "не указана госпошлина из калькулятора" not in gaps:
                gaps.append("не указана госпошлина из калькулятора")

    if lint.get("gap_count", 0) > 0:
        gaps.append(f"незаполненные поля: {lint['gap_count']}")

    run = bool(financial_claim or gaps or lint.get("issues"))
    return DocumentCompletionPlan(
        run_completion=run,
        gap_labels=list(dict.fromkeys(gaps)),
        financial_claim=financial_claim,
    )


def build_completion_gap_report(plan: DocumentCompletionPlan) -> str:
    if not plan.gap_labels:
        return (
            "Проверь документ целиком. Для иска с денежными требованиями обязательно:\n"
            "- просительная часть с пунктами «взыскать…»;\n"
            "- суммы только из блока КАЛЬКУЛЯТОР;\n"
            "- госпошлина в блоке «Цена иска», если рассчитана."
        )
    lines = ["Исправь только перечисленное (остальной текст не переписывай):"]
    for idx, label in enumerate(plan.gap_labels, start=1):
        lines.append(f"{idx}. {label}")
    return "\n".join(lines)
