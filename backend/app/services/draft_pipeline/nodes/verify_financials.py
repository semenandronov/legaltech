"""Node: deterministic financial verification after LLM fact passport."""
from __future__ import annotations

import logging

from app.config import config
from app.services.draft_pipeline.financial_calculator import apply_verified_financials
from app.services.draft_pipeline.schemas import ExtractedFacts

logger = logging.getLogger(__name__)


def run_verify_financials(facts: ExtractedFacts) -> ExtractedFacts:
    """
    Apply Python RF calendar calculator to penalty terms.

    When verification succeeds, overwrites ``financial.*`` with verified amounts
    and sets ``financial.verified`` trace for audit.
    """
    if not bool(getattr(config, "DRAFT_FINANCIAL_CALCULATOR_ENABLED", True)):
        return facts

    updated = apply_verified_financials(facts)
    if updated.financial.verified:
        logger.info(
            "[draft_pipeline.verify_financials] applied verified total=%s days=%s",
            updated.financial.total_to_claim[:40],
            updated.financial.verified.penalty_days,
        )
    else:
        logger.info("[draft_pipeline.verify_financials] skipped — insufficient structured terms")
    return updated
