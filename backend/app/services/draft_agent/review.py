"""Lightweight structural review for draft HTML (no extra agent tool call)."""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.draft_pipeline.markers import find_gap_markers, html_tag_balance_ok


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _has_unfilled_prayer(html: str) -> bool:
    low = (html or "").lower()
    if re.search(r"\[формулировка\s+требован", low):
        return True
    if re.search(r"\[фио\s+или\s+наименован", low):
        return True

    prayer_match = re.search(
        r"(<h2[^>]*>\s*просительн\w*[^<]*</h2>.*?)(?=<h2[^>]*>|$)",
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    prayer_block = prayer_match.group(1).lower() if prayer_match else low[low.find("просительн") : low.find("просительн") + 800]

    if "просительн" in low or "прошу суд" in low:
        if re.search(r"<ol[^>]*>\s*</ol>", prayer_block):
            return True
        if re.search(r"<li[^>]*>\s*\[", prayer_block):
            return True
        if "прошу" in prayer_block and "взыск" not in prayer_block:
            return True
        if "прошу" in prayer_block and "взыск" in prayer_block and not re.search(r"\d", prayer_block):
            return True
        if "прошу суд" in prayer_block and not re.search(r"<li[^>]*>[^<]{10,}", prayer_block):
            return True

    for block in re.findall(r"(просительн\w*[^<]{0,200})", low, flags=re.IGNORECASE):
        if "взыск" in block and not re.search(r"\d", block):
            return True
    return False


def review_draft_html(
    html: str,
    *,
    expected_amounts: Optional[List[str]] = None,
    financial_claim: bool = False,
    verified_penalty: Optional[str] = None,
    verified_total: Optional[str] = None,
    verified_state_duty: Optional[str] = None,
) -> dict:
    """
    Fast checks before/after persist. Gaps are warnings, not hard failures.
    """
    source = (html or "").strip()
    issues: List[str] = []
    warnings: List[str] = []

    if len(source) < 80:
        issues.append("document_too_short")
    if source and not html_tag_balance_ok(source):
        issues.append("html_structure_unbalanced")

    gaps = find_gap_markers(source)
    if gaps:
        warnings.append(f"gap_markers:{len(gaps)}")
        for label, _, _ in gaps[:8]:
            warnings.append(f"gap:{label[:80]}")

    if expected_amounts:
        combined = _digits_only(source)
        for amount in expected_amounts:
            token = _digits_only(amount)
            if len(token) >= 5 and token not in combined:
                issues.append(f"amount_not_found:{token[:12]}")

    if financial_claim:
        if _has_unfilled_prayer(source):
            issues.append("prayer_section_unfilled")
        low = source.lower()
        if "неустойк" in low and verified_penalty:
            penalty_digits = _digits_only(verified_penalty)
            if len(penalty_digits) >= 4 and penalty_digits not in _digits_only(source):
                issues.append("penalty_amount_missing")
        if verified_total:
            total_digits = _digits_only(verified_total)
            if len(total_digits) >= 5 and total_digits not in _digits_only(source):
                issues.append("total_claim_missing")
        if verified_state_duty:
            duty_digits = _digits_only(verified_state_duty)
            if len(duty_digits) >= 3 and duty_digits not in _digits_only(source):
                issues.append("state_duty_missing")

    passed = not issues
    return {
        "passed": passed,
        "issues": issues,
        "warnings": warnings,
        "gap_count": len(gaps),
        "recommendation": "accept" if passed else "review_manually",
    }
