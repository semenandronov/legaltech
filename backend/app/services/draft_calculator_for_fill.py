"""Калькулятор рядом с LLM при заполнении шаблона (catalog_fill)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import config
from app.services.draft_agent.instruction import build_verified_amounts_block
from app.services.draft_pipeline.nodes.fact_passport import extract_case_fact_passport
from app.services.draft_pipeline.nodes.verify_financials import run_verify_financials
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot, ExtractedFacts
from app.services.draft_template_schemas import TemplateFieldSpec

logger = logging.getLogger(__name__)

_AMOUNT_VARIABLES: Set[str] = frozenset(
    {
        "state_duty",
        "debt_total",
        "debt_main",
        "debt_penalty",
        "debt_start_date",
        "debt_end_date",
        "debt_confirmed",
        "debt_monetary",
        "debt_injury",
        "debt_salary",
        "debt_intellectual",
        "debt_mandatory",
        "asset_immovable",
        "asset_movable",
        "asset_intangible",
        "asset_receivable",
        "asset_total",
    }
)

_CALCULATOR_FIELD_HINTS = """
СООТВЕТСТВИЕ ПОЛЕЙ ШАБЛОНА И КАЛЬКУЛЯТОРА (если блок КАЛЬКУЛЯТОР выше заполнен — используй эти цифры):
- debt_main → основной долг (только цифры, без пробелов и «руб.»)
- debt_penalty → неустойка (только цифры)
- debt_total → итого к взысканию (только цифры)
- state_duty → госпошлина (только цифры)
- debt_start_date → дата начала периода неустойки (ДД.ММ.ГГГГ)
- debt_end_date → дата окончания периода неустойки (ДД.ММ.ГГГГ)
Если калькулятор не дал значение — бери из материалов дела; не выдумывай.
"""


def _catalog_has_amount_fields(field_specs: List[TemplateFieldSpec]) -> bool:
    variables = {(s.variable or "").strip() for s in field_specs if (s.variable or "").strip()}
    return bool(variables & _AMOUNT_VARIABLES)


def _iso_to_ru_date(value: str) -> str:
    raw = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return raw


def _digits_only_money(value: str) -> str:
    return re.sub(r"[^\d]", "", (value or "").strip())


def calculator_variable_values(facts: ExtractedFacts) -> Dict[str, str]:
    """Значения переменных docxtpl из верифицированного калькулятора."""
    verified = facts.financial.verified
    if not verified:
        return {}
    out: Dict[str, str] = {}
    if verified.principal_outstanding:
        out["debt_main"] = _digits_only_money(verified.principal_outstanding)
    if verified.penalty_amount:
        out["debt_penalty"] = _digits_only_money(verified.penalty_amount)
    if verified.total_claim:
        out["debt_total"] = _digits_only_money(verified.total_claim)
    if verified.state_duty:
        out["state_duty"] = _digits_only_money(verified.state_duty)
    if verified.penalty_start_date:
        out["debt_start_date"] = _iso_to_ru_date(verified.penalty_start_date)
    if verified.penalty_end_date:
        out["debt_end_date"] = _iso_to_ru_date(verified.penalty_end_date)
    return out


def _build_variable_hints(facts: ExtractedFacts) -> str:
    verified = facts.financial.verified
    if not verified:
        return ""
    lines = ["КОНКРЕТНЫЕ ЗНАЧЕНИЯ ДЛЯ ПОДСТАНОВКИ (из калькулятора):"]
    if verified.principal_outstanding:
        lines.append(f"- debt_main: {_digits_only_money(verified.principal_outstanding)}")
    if verified.penalty_amount:
        lines.append(f"- debt_penalty: {_digits_only_money(verified.penalty_amount)}")
    if verified.total_claim:
        lines.append(f"- debt_total: {_digits_only_money(verified.total_claim)}")
    if verified.state_duty:
        lines.append(f"- state_duty: {_digits_only_money(verified.state_duty)}")
    if verified.penalty_start_date:
        lines.append(f"- debt_start_date: {_iso_to_ru_date(verified.penalty_start_date)}")
    if verified.penalty_end_date:
        lines.append(f"- debt_end_date: {_iso_to_ru_date(verified.penalty_end_date)}")
    return "\n".join(lines)


def attach_calculator_context_for_fill(
    *,
    user_context: str,
    rag_context: str,
    field_specs: List[TemplateFieldSpec],
) -> Tuple[str, Dict[str, Any]]:
    """
    Паспорт фактов + Python-калькулятор → блок в контексте LLM при заполнении полей.

    Returns:
        (augmented_user_context, meta)
    """
    meta: Dict[str, Any] = {"calculator_attempted": False, "calculator_applied": False}
    if not bool(getattr(config, "DRAFT_CATALOG_FILL_CALCULATOR_ENABLED", True)):
        return user_context, meta
    if not bool(getattr(config, "DRAFT_FINANCIAL_CALCULATOR_ENABLED", True)):
        return user_context, meta
    if not _catalog_has_amount_fields(field_specs):
        return user_context, meta

    ctx = (rag_context or "").strip()
    user = (user_context or "").strip()
    if not user and not ctx:
        return user_context, meta

    meta["calculator_attempted"] = True
    try:
        snapshot = CaseRetrievalSnapshot(rag_context=ctx[:7000])
        facts = extract_case_fact_passport(user_prompt=user, case_retrieval=snapshot)
        facts = run_verify_financials(facts)
        amounts_block = build_verified_amounts_block(facts)
        if not amounts_block:
            logger.info("[draft_calculator_for_fill] calculator skipped — insufficient penalty terms")
            return user_context, meta

        var_hints = _build_variable_hints(facts)
        calc_vars = calculator_variable_values(facts)
        parts = [user, amounts_block, _CALCULATOR_FIELD_HINTS.strip()]
        if var_hints:
            parts.append(var_hints)
        augmented = "\n\n".join(p for p in parts if p.strip())
        meta["calculator_applied"] = True
        meta["calculator_variables"] = calc_vars
        verified = facts.financial.verified
        if verified:
            meta["calculator_total"] = verified.total_claim
            meta["calculator_penalty"] = verified.penalty_amount
        logger.info("[draft_calculator_for_fill] calculator applied for catalog fill")
        return augmented, meta
    except Exception as e:
        logger.warning("[draft_calculator_for_fill] failed: %s", e)
        meta["calculator_error"] = str(e)[:200]
        return user_context, meta
