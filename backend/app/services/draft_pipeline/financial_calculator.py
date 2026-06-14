"""Deterministic financial verification for draft pipeline (no LLM math)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from app.services.draft_pipeline.rf_business_calendar import (
    count_penalty_days,
    payment_deadline_and_penalty_start,
)
from app.services.draft_pipeline.schemas import (
    ExtractedFacts,
    FinancialLineItem,
    PenaltyTerms,
    VerifiedCalculations,
)

logger = logging.getLogger(__name__)

_RU_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def parse_money(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    # Drop currency words and keep digits
    cleaned = re.sub(r"[^\d,.\s]", " ", text)
    cleaned = cleaned.replace("\u00a0", " ").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def format_money_rub(amount: Decimal) -> str:
    q = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    s = f"{q:,}".replace(",", " ")
    return f"{s} руб."


def compute_state_duty_rub(claim_amount: Decimal) -> Decimal:
    """
    Госпошлина по имущественному иску (п. 1 ч. 1 ст. 333.19 НК РФ, общий порядок).
    """
    amount = claim_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        return Decimal("400")

    if amount <= Decimal("20000"):
        fee = (amount * Decimal("0.04")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return max(fee, Decimal("400"))
    if amount <= Decimal("100000"):
        excess = amount - Decimal("20000")
        return (Decimal("800") + excess * Decimal("0.03")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if amount <= Decimal("200000"):
        excess = amount - Decimal("100000")
        return (Decimal("3200") + excess * Decimal("0.02")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if amount <= Decimal("1000000"):
        excess = amount - Decimal("200000")
        return (Decimal("5200") + excess * Decimal("0.01")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    excess = amount - Decimal("1000000")
    fee = (Decimal("13200") + excess * Decimal("0.005")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return min(fee, Decimal("200000"))


def parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = (str(value or "")).strip()
    if not text:
        return None

    # ISO
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD.MM.YYYY
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # «02 июня 2025 года»
    low = text.lower().replace("г.", "").replace("года", "").strip()
    m = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", low)
    if m:
        day = int(m.group(1))
        month_word = m.group(2)
        year = int(m.group(3))
        for prefix, month_num in _RU_MONTHS.items():
            if month_word.startswith(prefix):
                try:
                    return date(year, month_num, day)
                except ValueError:
                    break

    return None


def _find_date_in_facts(facts: ExtractedFacts, *keys: str) -> Optional[date]:
    for key in keys:
        if key in facts.dates:
            d = parse_date(facts.dates[key])
            if d:
                return d
    for key in keys:
        for k, v in facts.dates.items():
            if key in k.lower():
                d = parse_date(v)
                if d:
                    return d
    return None


def _merge_penalty_terms(facts: ExtractedFacts) -> PenaltyTerms:
    raw = facts.penalty_terms
    if raw is None and isinstance(facts.other.get("penalty_terms"), dict):
        raw = PenaltyTerms.from_llm_dict(facts.other.get("penalty_terms"))
    terms = raw or PenaltyTerms()

    if not terms.act_date:
        found = _find_date_in_facts(
            facts,
            "act_date",
            "дата акта",
            "акт",
            "подписания акта",
        )
        if found:
            terms.act_date = found.isoformat()
    if not terms.contract_date:
        found = _find_date_in_facts(
            facts,
            "contract_date",
            "дата договора",
            "договор",
        )
        if found:
            terms.contract_date = found.isoformat()
    principal_dec: Optional[Decimal] = parse_money(terms.principal_amount)
    if principal_dec is None:
        for key in ("principal_amount", "основной долг", "сумма договора", "цена"):
            if key in facts.amounts:
                principal_dec = parse_money(facts.amounts[key])
                if principal_dec is not None:
                    break
        if principal_dec is None:
            for k, v in facts.amounts.items():
                if any(x in k.lower() for x in ("долг", "сумм", "цена", "задолжен")):
                    principal_dec = parse_money(v)
                    if principal_dec is not None:
                        break
    terms.principal_amount = str(principal_dec) if principal_dec is not None else terms.principal_amount

    rate_dec: Optional[Decimal] = None
    if terms.penalty_rate_percent_per_day:
        try:
            rate_dec = Decimal(str(terms.penalty_rate_percent_per_day).replace(",", ".").strip())
        except Exception:
            rate_dec = None

    if rate_dec is None:
        blob = " ".join(str(v) for v in facts.other.values()) + " " + str(facts.financial.computation_method)
        m = re.search(r"0[,.]1\s*%", blob)
        if m:
            rate_dec = Decimal("0.1")
        else:
            m = re.search(r"(\d+[,.]?\d*)\s*%\s*(?:от|за)\s*(?:сумм|день|проср)", blob.lower())
            if m:
                rate_dec = Decimal(m.group(1).replace(",", "."))
    if rate_dec is not None:
        terms.penalty_rate_percent_per_day = str(rate_dec)

    if not terms.partial_payments and facts.financial.partial_payments:
        terms.partial_payments = list(facts.financial.partial_payments)

    return terms


def _net_principal(
    principal: Decimal,
    payments: List[FinancialLineItem],
) -> Tuple[Decimal, List[str]]:
    notes: List[str] = []
    net = principal
    for p in payments:
        amt = parse_money(p.amount)
        if amt is None:
            continue
        net -= amt
        label = p.source or p.note or "частичная оплата"
        notes.append(f"− {format_money_rub(amt)} ({label}, {p.date or 'без даты'})")
    if net < 0:
        net = Decimal("0")
    return net, notes


def compute_verified_financials(facts: ExtractedFacts) -> Optional[VerifiedCalculations]:
    """
    Compute payment deadline, penalty period and amounts from structured terms.

    Returns None when mandatory inputs are missing (caller keeps LLM partial results).
    """
    terms = _merge_penalty_terms(facts)

    if terms.payment_term_unit != "business_days" or terms.payment_term_value <= 0:
        return None

    event_date = parse_date(terms.act_date) or parse_date(terms.contract_date)
    if not event_date:
        return None

    principal = parse_money(terms.principal_amount)
    if principal is None or principal <= 0:
        return None

    rate = parse_money(terms.penalty_rate_percent_per_day)
    if rate is None or rate <= 0:
        return None

    penalty_end = parse_date(terms.penalty_end_date) or date.today()

    deadline, penalty_start = payment_deadline_and_penalty_start(
        event_date,
        terms.payment_term_value,
        term_count_starts=terms.term_count_starts,
    )

    days = count_penalty_days(penalty_start, penalty_end)
    if days <= 0:
        return None

    net_principal, payment_notes = _net_principal(principal, terms.partial_payments)
    rate_fraction = rate / Decimal("100")
    penalty_amount = (net_principal * rate_fraction * Decimal(days)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    total = net_principal + penalty_amount
    state_duty = compute_state_duty_rub(total)

    trace_parts = [
        f"Срок оплаты: {terms.payment_term_value} рабоч. дн. с {event_date.isoformat()} "
        f"(отсчёт: {'со следующего дня' if terms.term_count_starts == 'next_day' else 'с дня события'})",
        f"Последний день оплаты: {deadline.strftime('%d.%m.%Y')}",
        f"Первый день просрочки: {penalty_start.strftime('%d.%m.%Y')}",
        f"Период неустойки: {penalty_start.strftime('%d.%m.%Y')} — {penalty_end.strftime('%d.%m.%Y')} "
        f"({days} календ. дн.)",
        f"База: {format_money_rub(net_principal)} × {rate}% × {days} дн. "
        f"= {format_money_rub(penalty_amount)}",
    ]
    if payment_notes:
        trace_parts.insert(1, "Частичные оплаты: " + "; ".join(payment_notes))

    return VerifiedCalculations(
        payment_deadline=deadline.isoformat(),
        penalty_start_date=penalty_start.isoformat(),
        penalty_end_date=penalty_end.isoformat(),
        penalty_days=days,
        principal_outstanding=format_money_rub(net_principal),
        penalty_amount=format_money_rub(penalty_amount),
        total_claim=format_money_rub(total),
        state_duty=format_money_rub(state_duty),
        penalty_rate_percent_per_day=str(rate),
        computation_trace="; ".join(trace_parts),
        source="python_rf_calendar_v1",
    )


def _resolve_penalty_start_date(facts: ExtractedFacts, terms: PenaltyTerms) -> Optional[date]:
    for candidate in (
        parse_date(terms.act_date),
        parse_date(terms.contract_date),
        _find_date_in_facts(
            facts,
            "debt_start_date",
            "дата начала",
            "начало неустойки",
            "просрочк",
            "с даты",
        ),
    ):
        if candidate:
            return candidate
    return None


def _resolve_penalty_end_date(facts: ExtractedFacts, terms: PenaltyTerms) -> date:
    for candidate in (
        parse_date(terms.penalty_end_date),
        _find_date_in_facts(
            facts,
            "debt_end_date",
            "по состоянию на",
            "дата иска",
            "на дату",
        ),
    ):
        if candidate:
            return candidate
    return date.today()


def compute_verified_financials_from_explicit_period(
    facts: ExtractedFacts,
) -> Optional[VerifiedCalculations]:
    """
    Расчёт, когда срок оплаты в рабочих днях неизвестен, но заданы ставка,
    основной долг и явный период неустойки (например «с 02.06.2025»).
    """
    terms = _merge_penalty_terms(facts)

    principal = parse_money(terms.principal_amount)
    if principal is None or principal <= 0:
        return None

    rate = parse_money(terms.penalty_rate_percent_per_day)
    if rate is None or rate <= 0:
        return None

    penalty_start = _resolve_penalty_start_date(facts, terms)
    if not penalty_start:
        return None

    penalty_end = _resolve_penalty_end_date(facts, terms)
    days = count_penalty_days(penalty_start, penalty_end)
    if days <= 0:
        return None

    net_principal, payment_notes = _net_principal(principal, terms.partial_payments)
    rate_fraction = rate / Decimal("100")
    penalty_amount = (net_principal * rate_fraction * Decimal(days)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    total = net_principal + penalty_amount
    state_duty = compute_state_duty_rub(total)

    trace_parts = [
        f"Период неустойки (явный): {penalty_start.strftime('%d.%m.%Y')} — "
        f"{penalty_end.strftime('%d.%m.%Y')} ({days} календ. дн.)",
        f"База: {format_money_rub(net_principal)} × {rate}% × {days} дн. "
        f"= {format_money_rub(penalty_amount)}",
    ]
    if payment_notes:
        trace_parts.insert(0, "Частичные оплаты: " + "; ".join(payment_notes))

    return VerifiedCalculations(
        payment_deadline="",
        penalty_start_date=penalty_start.isoformat(),
        penalty_end_date=penalty_end.isoformat(),
        penalty_days=days,
        principal_outstanding=format_money_rub(net_principal),
        penalty_amount=format_money_rub(penalty_amount),
        total_claim=format_money_rub(total),
        state_duty=format_money_rub(state_duty),
        penalty_rate_percent_per_day=str(rate),
        computation_trace="; ".join(trace_parts),
        source="python_explicit_period_v1",
    )


def apply_verified_financials(facts: ExtractedFacts) -> ExtractedFacts:
    """Run calculator and merge verified numbers into financial block."""
    verified = compute_verified_financials(facts)
    if not verified:
        verified = compute_verified_financials_from_explicit_period(facts)
    if not verified:
        return facts

    terms = _merge_penalty_terms(facts)
    financial = facts.financial.model_copy(deep=True)
    financial.verified = verified
    financial.principal_claim = verified.principal_outstanding
    financial.penalty_claim = verified.penalty_amount
    financial.total_to_claim = verified.total_claim
    financial.computation_method = verified.computation_trace
    financial.confidence = "high"

    logger.info(
        "[draft_pipeline.financial_calc] verified days=%s penalty=%s total=%s",
        verified.penalty_days,
        verified.penalty_amount,
        verified.total_claim,
    )

    return facts.model_copy(
        update={
            "financial": financial,
            "penalty_terms": terms,
            "dates": {
                **facts.dates,
                "payment_deadline": verified.payment_deadline,
                "penalty_start": verified.penalty_start_date,
            },
        }
    )
