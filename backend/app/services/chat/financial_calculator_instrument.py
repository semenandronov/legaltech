"""Financial calculator execution for draft mode (invoked by draft agent tool)."""
from __future__ import annotations

import logging
from typing import Tuple

from app.services.draft_pipeline.financial_calculator import (
    apply_verified_financials,
    compute_verified_financials,
)
from app.services.draft_pipeline.schemas import ExtractedFacts

logger = logging.getLogger(__name__)


def execute_financial_calculator(
    facts: ExtractedFacts,
    *,
    reason: str = "",
) -> Tuple[ExtractedFacts, dict]:
    """
    Run Python RF financial calculator on structured facts.

    Called only when the draft agent invokes ``compute_contract_financials`` tool.
    """
    meta: dict = {
        "applied": False,
        "computable": False,
        "agent_reason": (reason or "").strip()[:500],
        "skip_reason": "",
    }

    preview = compute_verified_financials(facts)
    meta["computable"] = preview is not None
    if not preview:
        meta["skip_reason"] = "insufficient_structured_terms"
        logger.info(
            "[financial_calculator_instrument] agent requested calc but insufficient terms reason=%s",
            meta["agent_reason"][:80],
        )
        return facts, meta

    updated = apply_verified_financials(facts)
    meta["applied"] = bool(updated.financial.verified)
    if meta["applied"]:
        verified = updated.financial.verified
        logger.info(
            "[financial_calculator_instrument] agent applied total=%s days=%s",
            (updated.financial.total_to_claim or "")[:40],
            verified.penalty_days if verified else None,
        )
    return updated, meta
