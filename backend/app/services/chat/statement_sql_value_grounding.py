"""
Value grounding for statement SQL description filters.

Grounds LLM plan tokens against real values in the current statement
(description / row_columns). No merchant allowlists — only data-driven matches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional, Protocol, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_validate import (
    extract_content_tokens,
    is_description_filter_noise,
    sanitize_description_contains,
)
from app.services.transaction_description_match import description_token_match

logger = logging.getLogger(__name__)

MatchCountFn = Callable[[str], int]


class DescriptionMatchProbe(Protocol):
    def count(self, needle: str) -> int: ...


@dataclass(frozen=True)
class DbDescriptionMatchProbe:
    db: Session
    case_id: str
    file_id: str
    on_date: Optional[date] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    def count(self, needle: str) -> int:
        text = (needle or "").strip()
        if not text:
            return 0
        page = CaseFileTransactionService.query_page(
            self.db,
            case_id=self.case_id,
            file_id=self.file_id,
            on_date=self.on_date,
            date_from=self.date_from,
            date_to=self.date_to,
            description_contains=text,
            limit=1,
            offset=0,
        )
        return int(page.total or 0)


@dataclass(frozen=True)
class RowsDescriptionMatchProbe:
    rows: Sequence[CaseFileTransaction]

    def count(self, needle: str) -> int:
        text = (needle or "").strip()
        if not text:
            return 0
        hits = 0
        for row in self.rows:
            hay = " ".join(
                filter(
                    None,
                    [
                        str(row.description or ""),
                        str(row.operation_datetime_text or ""),
                        str(row.row_columns or ""),
                        str(row.amount_raw or ""),
                    ],
                )
            )
            if description_token_match(hay, text):
                hits += 1
        return hits


def _parse_plan_date(value: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        d, m, y = raw.split(".")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _score_candidate(token: str, hits: int) -> tuple[int, int, int]:
    """Prefer more hits, then longer tokens (more specific substrings)."""
    return (hits, len(token), -ord(token[0]) if token else 0)


def _best_grounded_token(
    candidates: Sequence[str],
    probe: DescriptionMatchProbe,
) -> str:
    best_token = ""
    best_score: tuple[int, int, int] = (0, 0, 0)
    for raw in candidates:
        token = (raw or "").strip()
        if not token or is_description_filter_noise(token):
            continue
        hits = probe.count(token)
        if hits <= 0:
            continue
        score = _score_candidate(token, hits)
        if score > best_score:
            best_score = score
            best_token = token
    return best_token


def ground_description_filter(
    plan: StatementSqlPlan,
    *,
    question: str,
    probe: DescriptionMatchProbe,
) -> StatementSqlPlan:
    """
    Ensure description_contains is either empty or matches real statement text.

    Priority:
    1. Keep plan needle if it already matches data.
    2. Else try content tokens from the plan needle.
    3. Else try content tokens from the user question that match data.
    """
    plan = sanitize_description_contains(plan)
    needle = (plan.description_contains or "").strip()

    if needle and probe.count(needle) > 0:
        return plan

    candidates: list[str] = []
    if needle:
        candidates.extend(extract_content_tokens(needle))
        # Keep original needle as last resort after token split (already failed count).
    candidates.extend(extract_content_tokens(question))

    # Preserve order, unique case-insensitively.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)

    grounded = _best_grounded_token(ordered, probe)
    if grounded and grounded.lower() != needle.lower():
        logger.info(
            "[StatementSqlValueGrounding] description_contains %r → %r",
            needle or None,
            grounded,
        )
        return plan.model_copy(update={"description_contains": grounded})

    if needle and probe.count(needle) == 0:
        logger.info(
            "[StatementSqlValueGrounding] clearing unmatched description_contains=%r",
            needle,
        )
        return plan.model_copy(update={"description_contains": ""})

    return plan


def refine_statement_sql_plan(
    plan: StatementSqlPlan,
    *,
    question: str,
    probe: DescriptionMatchProbe,
) -> StatementSqlPlan:
    """Validate + value-ground description filter before execution."""
    return ground_description_filter(plan, question=question, probe=probe)


def refine_plan_with_db(
    db: Session,
    *,
    case_id: str,
    plan: StatementSqlPlan,
    question: str,
    file_id: str,
) -> StatementSqlPlan:
    on_date = _parse_plan_date(plan.on_date)
    date_from = _parse_plan_date(plan.date_from)
    date_to = _parse_plan_date(plan.date_to)
    # When multi-day range is set, ignore on_date for probing (same as executor).
    if date_from and date_to and date_to > date_from:
        on_date = None
    probe = DbDescriptionMatchProbe(
        db=db,
        case_id=case_id,
        file_id=file_id,
        on_date=on_date,
        date_from=date_from,
        date_to=date_to,
    )
    return refine_statement_sql_plan(plan, question=question, probe=probe)


def refine_plan_with_rows(
    plan: StatementSqlPlan,
    *,
    question: str,
    rows: Sequence[CaseFileTransaction],
) -> StatementSqlPlan:
    probe = RowsDescriptionMatchProbe(rows=rows)
    return refine_statement_sql_plan(plan, question=question, probe=probe)
