"""Layer 2 reduce: merge isolated extractions into ExtractedFacts (Case State)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.services.draft_pipeline.financial_calculator import parse_date, parse_money
from app.services.draft_pipeline.schemas import (
    DocumentExtractionRecord,
    DraftTaskPlan,
    ExtractedFacts,
    FinancialLineItem,
    FinancialSummary,
    PenaltyTerms,
)

logger = logging.getLogger(__name__)


def _penalty_terms_populated(terms: PenaltyTerms) -> bool:
    return bool(
        terms.payment_term_value
        or terms.act_date
        or terms.contract_date
        or terms.penalty_rate_percent_per_day
        or terms.principal_amount
        or terms.partial_payments
    )


def _infer_penalty_end_date(user_prompt: str) -> str | None:
    text = (user_prompt or "").strip()
    if not text:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    if m:
        d = parse_date(m.group(1))
        return d.isoformat() if d else None
    return None


def _merge_dicts(target: Dict[str, str], source: Any, prefix: str = "") -> None:
    if not isinstance(source, dict):
        return
    for k, v in source.items():
        if v is None:
            continue
        val = str(v).strip()
        if not val:
            continue
        key = f"{prefix}{k}" if prefix else str(k)
        target[key] = val


def consolidate_extractions(
    *,
    records: List[DocumentExtractionRecord],
    task_plan: DraftTaskPlan,
    user_prompt: str,
) -> ExtractedFacts:
    """Build immutable Case State from per-document payloads."""
    parties: Dict[str, str] = {}
    amounts: Dict[str, str] = {}
    dates: Dict[str, str] = {}
    identifiers: Dict[str, str] = {}
    other: Dict[str, str] = {}
    partial_payments: List[FinancialLineItem] = []
    penalty_terms = PenaltyTerms()

    for rec in records:
        p = rec.payload or {}
        schema = rec.schema_name

        if schema == "ContractExtraction":
            _merge_dicts(parties, p.get("parties"))
            if p.get("total_price"):
                amounts["сумма договора"] = str(p["total_price"])
            if p.get("contract_date"):
                dates["дата договора"] = str(p["contract_date"])
                penalty_terms.contract_date = str(p["contract_date"])
            if p.get("contract_number"):
                other["номер договора"] = str(p["contract_number"])
            try:
                days = int(p.get("payment_term_days") or 0)
                if days > 0:
                    penalty_terms.payment_term_value = days
            except (TypeError, ValueError):
                pass
            unit = str(p.get("payment_term_unit") or "").lower()
            if unit in ("business_days", "calendar_days"):
                penalty_terms.payment_term_unit = unit  # type: ignore[assignment]
            term_from = str(p.get("payment_term_from") or "").lower()
            if term_from in ("act_signed", "contract_signed", "delivery", "other"):
                penalty_terms.payment_term_from = term_from  # type: ignore[assignment]
            rate = p.get("penalty_rate_percent_per_day")
            if rate:
                penalty_terms.penalty_rate_percent_per_day = str(rate)
            if p.get("total_price"):
                dec = parse_money(p["total_price"])
                if dec is not None:
                    penalty_terms.principal_amount = str(dec)
                else:
                    penalty_terms.principal_amount = str(p["total_price"]).replace(" ", "")

        elif schema == "ActExtraction":
            if p.get("act_date"):
                dates["дата акта"] = str(p["act_date"])
                penalty_terms.act_date = str(p["act_date"])
            if p.get("amount"):
                amounts["сумма по акту"] = str(p["amount"])
            if p.get("act_number"):
                other[f"акт {rec.filename}"] = str(p["act_number"])
            _merge_dicts(parties, p.get("parties"))

        elif schema == "PaymentExtraction":
            amt = str(p.get("amount") or "").strip()
            dt = str(p.get("payment_date") or "").strip()
            if amt:
                partial_payments.append(
                    FinancialLineItem(
                        date=dt,
                        amount=amt,
                        source=p.get("document_number") or rec.filename,
                        note=str(p.get("purpose") or "")[:200],
                    )
                )

        elif schema in ("RequisitesExtraction",):
            _merge_dicts(parties, p.get("parties"))
            _merge_dicts(identifiers, p.get("identifiers"))

        else:
            _merge_dicts(parties, p.get("parties"))
            _merge_dicts(amounts, p.get("amounts"))
            _merge_dicts(dates, p.get("dates"))
            _merge_dicts(identifiers, p.get("identifiers"))

    doc_type = (task_plan.target_document_type or "").strip()
    if not doc_type and user_prompt:
        low = user_prompt.lower()
        if "иск" in low:
            doc_type = "исковое заявление"
        elif "претенз" in low:
            doc_type = "претензия"

    penalty_terms.partial_payments = list(partial_payments)
    end_date = _infer_penalty_end_date(user_prompt)
    if end_date and not penalty_terms.penalty_end_date:
        penalty_terms.penalty_end_date = end_date

    financial = FinancialSummary(
        principal_claim=amounts.get("сумма договора", ""),
        partial_payments=partial_payments,
        confidence="partial" if parties or amounts else "missing",
    )

    facts = ExtractedFacts(
        document_type=doc_type,
        parties=parties,
        amounts=amounts,
        dates=dates,
        identifiers=identifiers,
        other=other,
        financial=financial,
        penalty_terms=penalty_terms if _penalty_terms_populated(penalty_terms) else None,
    )
    logger.info(
        "[draft_pipeline.consolidate] parties=%s amounts=%s payments=%s",
        len(parties),
        len(amounts),
        len(partial_payments),
    )
    return facts
