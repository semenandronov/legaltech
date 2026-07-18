"""
Deterministic analytics over one bank statement's transaction rows.

Pure functions only — no DB, no LLM. Every number the assistant reports about a
statement (overview profile, monthly cash flow, anomaly/risk heuristics,
counterparty profile) is produced here, so answers stay auditable and reproducible.

Sign convention (matches CaseFileTransaction.amount_rub and the SQL executor):
    amount_rub > 0  → поступление (credit / inflow)
    amount_rub < 0  → списание (debit / outflow)

Analytics always reads amounts via ``effective_amount_rub`` so legacy rows that
were stored as unsigned positives are recovered from ``amount_raw`` / ``flow_direction``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from app.models.case_file_transaction import CaseFileTransaction
from app.services.transaction_amount_sign import effective_amount_rub
from app.services.transaction_description_match import (
    any_field_description_token_match,
    description_token_match,
)

_ZERO = Decimal("0")

# Cash withdrawal / cash-out narrative markers (whole-word-ish, case-insensitive).
_CASH_RE = re.compile(
    r"(нал\w*деньг|снят\w*|выдач\w*\s+нал|банкомат|atm|cash\b|обналич\w*|"
    r"выдача\s+наличн\w*|получени\w*\s+наличн\w*)",
    re.IGNORECASE,
)

# Operation categories map narrative to what matters legally: separating routine
# spend from loans, cash and person-to-person transfers. Classification is layered
# (see classify_operation): keyword categories → individual transfer → card spend →
# other. Codes are stable (API/tests); labels are shown to the lawyer.

# Keyword categories, checked first, in order (first match wins). Case-insensitive.
_PRIMARY_CATEGORIES: Tuple[Tuple[str, str, "re.Pattern[str]"], ...] = (
    (
        "cash",
        "Наличные",
        _CASH_RE,
    ),
    (
        "loan",
        "Займы и кредиты",
        re.compile(
            r"(за[её]м|займ\w*|ссуд\w*|кредит\w*|цесси\w*|вексел\w*|"
            r"возврат\w*\s+за[её]м|погашени\w*\s+кредит)",
            re.IGNORECASE,
        ),
    ),
    (
        "tax",
        "Налоги, взносы, штрафы",
        re.compile(
            r"(налог\w*|\bндфл\b|\bндс\b|страхов\w*\s+взнос|взнос\w*|фнс|"
            r"госпошлин\w*|штраф\w*|пени|исполнительн\w*\s+сбор|судебн\w*\s+пристав|фссп)",
            re.IGNORECASE,
        ),
    ),
    (
        "utilities",
        "ЖКХ, связь, аренда",
        re.compile(
            r"(жкх|коммунальн\w*|электроэнерг\w*|газоснабж\w*|водоснабж\w*|"
            r"отоплени\w*|аренд\w*|связ[ьи]|интернет|мобильн\w*|телефон)",
            re.IGNORECASE,
        ),
    ),
    (
        "salary",
        "Зарплата и выплаты сотрудникам",
        re.compile(
            r"(зарплат\w*|заработн\w*\s+плат|аванс|оплат\w*\s+труд|"
            r"отпускн\w*|преми\w*|расчет\w*\s+при\s+увольн)",
            re.IGNORECASE,
        ),
    ),
)

# Card / retail spend, checked after the person-transfer test.
_CARD_SPEND_RE = re.compile(
    r"(оплат\w*\s+товар|покупк\w*|розничн\w*|\bpos\b|магазин|"
    r"супермаркет|кафе|ресторан|аптек|\bазс\b|топливо)",
    re.IGNORECASE,
)

# Legal-entity markers — if present, the operation is NOT a transfer to a natural
# person (guards against classifying company names as physical persons).
_ORG_MARKER_RE = re.compile(
    r"(\bООО\b|\bОАО\b|\bПАО\b|\bЗАО\b|\bАО\b|\bИП\b|\bНКО\b|\bПАО\b|\bГУП\b|\bМУП\b|"
    r"общест\w*|компани\w*|\bбанк\w*|завод\w*|фабрик\w*|дорог\w*|фонд\w*|"
    r"учрежден\w*|департамент\w*|министерств\w*|инспекц\w*|служб\w*|"
    r"корпораци\w*|холдинг\w*|групп\w*|предприяти\w*|организаци\w*)",
    re.IGNORECASE,
)

# Explicit person-to-person transfer markers (case-insensitive on purpose).
_PERSON_MARKER_RE = re.compile(
    r"(перевод\w*\s+физ|физическ\w+\s+лиц|\bфизлиц\w*|на\s+карт\w*|"
    r"по\s+сбп|\bсбп\b|\bc2c\b|\bс2с\b|\bp2p\b|\bр2р\b)",
    re.IGNORECASE,
)

# ФИО patterns — CASE-SENSITIVE (capitalization is the signal). Two robust forms:
#   1) фамилия + инициалы:  «Иванов И.И.» / «Иванов И. И.» / «И.И. Иванов»
#   2) фамилия + имя + отчество: отчество опознаём по суффиксу (-ович/-евич/-ич/
#      -овна/-евна/-ична/-инична), что почти не даёт ложных совпадений с юрлицами.
_FIO_INITIALS_RE = re.compile(
    r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+"
)
_FIO_FULL_RE = re.compile(
    r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]*"
    r"(?:ович|евич|ьич|ич|овна|евна|инична|ична)\b"
)

_CATEGORY_LABELS: Dict[str, str] = {code: label for code, label, _ in _PRIMARY_CATEGORIES}
_CATEGORY_LABELS["individual_transfer"] = "Переводы физлицам"
_CATEGORY_LABELS["card_spend"] = "Покупки и оплата товаров/услуг"
_CATEGORY_LABELS["other"] = "Прочее"


def _looks_like_person(text: str) -> bool:
    """True when the narrative names a natural person (and no legal-entity marker)."""
    if _ORG_MARKER_RE.search(text):
        return False
    if _PERSON_MARKER_RE.search(text):
        return True
    return bool(_FIO_INITIALS_RE.search(text) or _FIO_FULL_RE.search(text))


def parse_ru_date(value: Optional[str]) -> Optional[date]:
    """Parse a date the LLM passes as a tool argument. Accepts DD.MM.YYYY / YYYY-MM-DD / DD/MM/YYYY."""
    raw = (value or "").strip()
    if not raw:
        return None
    for splitter in (".", "/"):  # DD.MM.YYYY or DD/MM/YYYY
        if splitter in raw:
            try:
                d, m, y = raw.split(splitter)
                return date(int(y), int(m), int(d))
            except (ValueError, TypeError):
                pass
    if "-" in raw:  # ISO YYYY-MM-DD
        try:
            y, m, d = raw.split("-")
            return date(int(y), int(m), int(d))
        except (ValueError, TypeError):
            return None
    return None


def filter_by_date_range(
    rows: Sequence[CaseFileTransaction],
    date_from: Optional[date],
    date_to: Optional[date],
) -> List[CaseFileTransaction]:
    """Rows with operation_date within [date_from, date_to] (inclusive). Undated rows are dropped when scoping."""
    if date_from is None and date_to is None:
        return list(rows)
    out: List[CaseFileTransaction] = []
    for row in rows:
        d = row.operation_date
        if d is None:
            continue
        if date_from is not None and d < date_from:
            continue
        if date_to is not None and d > date_to:
            continue
        out.append(row)
    return out


# Legal suspicion windows anchored to the petition-acceptance date (дата принятия
# заявления). Each entry: code -> (label, lookback). Ranges are [petition - lookback,
# petition]. Bases mirror ст. 61.2/61.3 Закона о банкротстве (№ 127-ФЗ).
_SUSPICION_WINDOWS: Tuple[Tuple[str, str, int], ...] = (
    ("preference_1m", "1 месяц (предпочтение, 61.3 п.2)", 30),
    ("preference_6m", "6 месяцев (предпочтение, 61.3 п.3)", 182),
    ("unequal_1y", "1 год (неравноценность, 61.2 п.1)", 365),
    ("harm_3y", "3 года (вред кредиторам, 61.2 п.2)", 365 * 3),
)


def suspicion_windows(petition_date: date) -> List[Tuple[str, str, date, date]]:
    """Return legal look-back windows as (code, label, date_from, date_to=petition_date)."""
    return [
        (code, label, petition_date - timedelta(days=days), petition_date)
        for code, label, days in _SUSPICION_WINDOWS
    ]


def classify_operation(row: CaseFileTransaction) -> str:
    """Deterministic, layered category by narrative. Explainable and precision-first.

    Order: keyword categories (cash/loan/tax/utilities/salary) → transfer to a natural
    person → card/retail spend → other. Person detection is case-sensitive (ФИО) and
    excludes legal-entity names, so companies are never mislabelled as individuals.
    """
    text = str(row.description or "")
    if not text.strip():
        return "other"
    for code, _label, pattern in _PRIMARY_CATEGORIES:
        if pattern.search(text):
            return code
    if _looks_like_person(text):
        return "individual_transfer"
    if _CARD_SPEND_RE.search(text):
        return "card_spend"
    return "other"


def category_label(code: str) -> str:
    return _CATEGORY_LABELS.get(code, code)


def format_amount_rub(value: Decimal | float | int | None) -> str:
    """Human-readable RUB amount: '1 234 567,89 ₽'. Single source for analytics text."""
    if value is None:
        return "—"
    try:
        dec = Decimal(str(value))
    except Exception:
        return str(value)
    formatted = f"{dec:,.2f}".replace(",", "\u00a0").replace(".", ",")
    return f"{formatted} ₽"


@dataclass(frozen=True)
class MoneyFlow:
    inflow_sum: Decimal
    outflow_sum: Decimal  # positive magnitude of debits
    net_sum: Decimal
    inflow_count: int
    outflow_count: int


@dataclass(frozen=True)
class CounterpartyStat:
    description: str
    op_count: int
    abs_sum: Decimal
    net_sum: Decimal


@dataclass(frozen=True)
class StatementOverview:
    operation_count: int
    date_min: Optional[date]
    date_max: Optional[date]
    flow: MoneyFlow
    top_outflow_counterparties: List[CounterpartyStat]
    top_inflow_counterparties: List[CounterpartyStat]
    largest_operations: List[CaseFileTransaction]
    cash_out_count: int
    cash_out_sum: Decimal


@dataclass(frozen=True)
class MonthBucket:
    year: int
    month: int
    inflow_sum: Decimal
    outflow_sum: Decimal
    net_sum: Decimal
    op_count: int

    @property
    def label(self) -> str:
        return f"{self.month:02d}.{self.year}"


@dataclass(frozen=True)
class CategoryBucket:
    category: str  # stable code, see classify_operation / _CATEGORY_LABELS
    label: str  # human-readable Russian label
    op_count: int
    inflow_sum: Decimal
    outflow_sum: Decimal  # positive magnitude of debits
    rows: List[CaseFileTransaction] = field(default_factory=list)


@dataclass(frozen=True)
class RecurringTransfer:
    description: str
    op_count: int
    total_sum: Decimal
    date_min: Optional[date]
    date_max: Optional[date]
    avg_interval_days: float
    rows: List[CaseFileTransaction] = field(default_factory=list)


@dataclass(frozen=True)
class AnomalyFinding:
    code: str
    title: str
    severity: str  # 'high' | 'medium' | 'low'
    summary: str
    rows: List[CaseFileTransaction] = field(default_factory=list)


@dataclass(frozen=True)
class CounterpartyProfile:
    token: str
    matched: bool
    op_count: int
    inflow_sum: Decimal
    outflow_sum: Decimal
    net_sum: Decimal
    date_min: Optional[date]
    date_max: Optional[date]
    rows: List[CaseFileTransaction]


@dataclass(frozen=True)
class AnomalyThresholds:
    large_amount: Decimal = Decimal("100000")
    round_step: Decimal = Decimal("10000")
    round_min: Decimal = Decimal("50000")
    structuring_min_ops: int = 3
    structuring_window_days: int = 3
    spike_multiplier: float = 5.0
    max_finding_rows: int = 10
    transit_window_days: int = 3
    transit_min_amount: Decimal = Decimal("100000")
    transit_ratio: float = 0.8
    recurring_min_ops: int = 4


def _amount(row: CaseFileTransaction) -> Optional[Decimal]:
    """Signed amount for analytics. Recovers sign from flow/raw on legacy rows."""
    return effective_amount_rub(
        row.amount_rub,
        amount_raw=row.amount_raw,
        flow_direction=getattr(row, "flow_direction", None),
    )


def _norm_desc(row: CaseFileTransaction) -> str:
    return str(row.description or "").strip() or "—"


def _row_dates(rows: Sequence[CaseFileTransaction]) -> List[date]:
    return [r.operation_date for r in rows if r.operation_date is not None]


def compute_money_flow(rows: Sequence[CaseFileTransaction]) -> MoneyFlow:
    inflow = _ZERO
    outflow = _ZERO
    inflow_count = 0
    outflow_count = 0
    for row in rows:
        amt = _amount(row)
        if amt is None or amt == _ZERO:
            continue
        if amt > 0:
            inflow += amt
            inflow_count += 1
        else:
            outflow += -amt
            outflow_count += 1
    return MoneyFlow(
        inflow_sum=inflow,
        outflow_sum=outflow,
        net_sum=inflow - outflow,
        inflow_count=inflow_count,
        outflow_count=outflow_count,
    )


def _counterparty_stats(
    rows: Sequence[CaseFileTransaction],
    *,
    direction: str,  # 'inflow' | 'outflow'
    top_n: int,
) -> List[CounterpartyStat]:
    buckets: Dict[str, List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        amt = _amount(row)
        if amt is None or amt == _ZERO:
            continue
        if direction == "inflow" and amt <= 0:
            continue
        if direction == "outflow" and amt >= 0:
            continue
        buckets[_norm_desc(row)].append(row)

    stats: List[CounterpartyStat] = []
    for description, bucket in buckets.items():
        abs_sum = sum((abs(_amount(r)) for r in bucket if _amount(r) is not None), _ZERO)
        net_sum = sum((_amount(r) for r in bucket if _amount(r) is not None), _ZERO)
        stats.append(
            CounterpartyStat(
                description=description,
                op_count=len(bucket),
                abs_sum=abs_sum,
                net_sum=net_sum,
            )
        )
    stats.sort(key=lambda s: (s.abs_sum, s.op_count), reverse=True)
    return stats[: max(1, top_n)]


def _sort_by_abs_amount(rows: Sequence[CaseFileTransaction]) -> List[CaseFileTransaction]:
    return sorted(
        rows,
        key=lambda r: (
            -(abs(_amount(r)) if _amount(r) is not None else _ZERO),
            r.operation_date or date.max,
            int(r.global_row_index or 0),
        ),
    )


def compute_overview(
    rows: Sequence[CaseFileTransaction],
    *,
    top_n: int = 5,
) -> StatementOverview:
    dates = _row_dates(rows)
    cash_rows = [
        r
        for r in rows
        if (_amount(r) is not None and _amount(r) < 0) and _CASH_RE.search(_norm_desc(r))
    ]
    cash_out_sum = sum((abs(_amount(r)) for r in cash_rows if _amount(r) is not None), _ZERO)
    return StatementOverview(
        operation_count=len(rows),
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        flow=compute_money_flow(rows),
        top_outflow_counterparties=_counterparty_stats(rows, direction="outflow", top_n=top_n),
        top_inflow_counterparties=_counterparty_stats(rows, direction="inflow", top_n=top_n),
        largest_operations=_sort_by_abs_amount(rows)[: max(1, top_n)],
        cash_out_count=len(cash_rows),
        cash_out_sum=cash_out_sum,
    )


def compute_monthly(rows: Sequence[CaseFileTransaction]) -> List[MonthBucket]:
    buckets: Dict[tuple[int, int], List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        if row.operation_date is None:
            continue
        buckets[(row.operation_date.year, row.operation_date.month)].append(row)

    out: List[MonthBucket] = []
    for (year, month), bucket in sorted(buckets.items()):
        flow = compute_money_flow(bucket)
        out.append(
            MonthBucket(
                year=year,
                month=month,
                inflow_sum=flow.inflow_sum,
                outflow_sum=flow.outflow_sum,
                net_sum=flow.net_sum,
                op_count=len(bucket),
            )
        )
    return out


def compute_counterparty_profile(
    rows: Sequence[CaseFileTransaction],
    token: str,
) -> CounterpartyProfile:
    needle = (token or "").strip()
    matched_rows: List[CaseFileTransaction] = []
    if needle:
        for row in rows:
            haystacks = (
                str(row.description or ""),
                str(row.operation_datetime_text or ""),
                str(row.amount_raw or ""),
                str(row.row_columns or ""),
            )
            if any_field_description_token_match(haystacks, needle) or description_token_match(
                str(row.description or ""), needle
            ):
                matched_rows.append(row)

    flow = compute_money_flow(matched_rows)
    dates = _row_dates(matched_rows)
    return CounterpartyProfile(
        token=needle,
        matched=bool(matched_rows),
        op_count=len(matched_rows),
        inflow_sum=flow.inflow_sum,
        outflow_sum=flow.outflow_sum,
        net_sum=flow.net_sum,
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        rows=matched_rows,
    )


def compute_category_breakdown(
    rows: Sequence[CaseFileTransaction],
) -> List[CategoryBucket]:
    """Group operations by narrative category (cash / loans / taxes / transfers / ...)."""
    buckets: Dict[str, List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        buckets[classify_operation(row)].append(row)

    out: List[CategoryBucket] = []
    for code, bucket in buckets.items():
        flow = compute_money_flow(bucket)
        out.append(
            CategoryBucket(
                category=code,
                label=category_label(code),
                op_count=len(bucket),
                inflow_sum=flow.inflow_sum,
                outflow_sum=flow.outflow_sum,
                rows=bucket,
            )
        )
    # Order by economic weight (turnover), so the lawyer sees the biggest flows first.
    out.sort(key=lambda b: (b.inflow_sum + b.outflow_sum), reverse=True)
    return out


def _is_round(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        return False
    return value % step == 0


def _detect_large_cash_out(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    hits = [
        r
        for r in rows
        if _amount(r) is not None
        and _amount(r) < 0
        and abs(_amount(r)) >= thr.large_amount
        and _CASH_RE.search(_norm_desc(r))
    ]
    if not hits:
        return None
    hits = _sort_by_abs_amount(hits)
    total = sum((abs(_amount(r)) for r in hits if _amount(r) is not None), _ZERO)
    return AnomalyFinding(
        code="large_cash_out",
        title="Крупные снятия наличных",
        severity="high",
        summary=(
            f"{len(hits)} операций снятия наличных на сумму {format_amount_rub(total)}. "
            "Крупные снятия перед банкротством требуют объяснения назначения."
        ),
        rows=hits[: thr.max_finding_rows],
    )


def _detect_round_large_debits(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    hits = [
        r
        for r in rows
        if _amount(r) is not None
        and _amount(r) < 0
        and abs(_amount(r)) >= thr.round_min
        and _is_round(abs(_amount(r)), thr.round_step)
        and not _CASH_RE.search(_norm_desc(r))
    ]
    if not hits:
        return None
    hits = _sort_by_abs_amount(hits)
    total = sum((abs(_amount(r)) for r in hits if _amount(r) is not None), _ZERO)
    return AnomalyFinding(
        code="round_large_debit",
        title="Круглые крупные списания",
        severity="medium",
        summary=(
            f"{len(hits)} списаний ровными суммами (кратно {format_amount_rub(thr.round_step)}) "
            f"на {format_amount_rub(total)}. Ровные суммы часто указывают на переводы, а не на оплату товаров/услуг."
        ),
        rows=hits[: thr.max_finding_rows],
    )


def _detect_structuring(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    """Repeated debits to the same counterparty in a short rolling window."""
    debit_by_desc: Dict[str, List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        amt = _amount(row)
        if amt is None or amt >= 0 or row.operation_date is None:
            continue
        debit_by_desc[_norm_desc(row)].append(row)

    flagged: List[CaseFileTransaction] = []
    groups_flagged = 0
    for desc, bucket in debit_by_desc.items():
        if desc == "—" or len(bucket) < thr.structuring_min_ops:
            continue
        ordered = sorted(bucket, key=lambda r: r.operation_date or date.max)
        window: List[CaseFileTransaction] = []
        group_hit = False
        for row in ordered:
            window.append(row)
            while (
                window
                and window[0].operation_date is not None
                and row.operation_date is not None
                and (row.operation_date - window[0].operation_date).days > thr.structuring_window_days
            ):
                window.pop(0)
            if len(window) >= thr.structuring_min_ops:
                group_hit = True
        if group_hit:
            groups_flagged += 1
            flagged.extend(ordered)

    if not flagged:
        return None
    flagged = _sort_by_abs_amount(flagged)
    total = sum((abs(_amount(r)) for r in flagged if _amount(r) is not None), _ZERO)
    return AnomalyFinding(
        code="structuring",
        title="Дробление платежей одному получателю",
        severity="high",
        summary=(
            f"{groups_flagged} получател(я/ей) с частыми списаниями "
            f"(≥{thr.structuring_min_ops} за {thr.structuring_window_days} дн.), всего {format_amount_rub(total)}. "
            "Дробление близких по времени переводов может маскировать вывод средств."
        ),
        rows=flagged[: thr.max_finding_rows],
    )


def _detect_large_transfers(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    hits = [
        r
        for r in rows
        if _amount(r) is not None
        and _amount(r) < 0
        and abs(_amount(r)) >= thr.large_amount
        and not _CASH_RE.search(_norm_desc(r))
    ]
    if not hits:
        return None
    hits = _sort_by_abs_amount(hits)
    total = sum((abs(_amount(r)) for r in hits if _amount(r) is not None), _ZERO)
    return AnomalyFinding(
        code="large_transfer",
        title="Крупные списания и переводы",
        severity="medium",
        summary=(
            f"{len(hits)} списаний от {format_amount_rub(thr.large_amount)} на общую сумму "
            f"{format_amount_rub(total)}. Проверьте получателей на аффилированность."
        ),
        rows=hits[: thr.max_finding_rows],
    )


def _median(values: List[Decimal]) -> Decimal:
    if not values:
        return _ZERO
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _detect_outflow_spikes(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    by_day: Dict[date, Decimal] = defaultdict(lambda: _ZERO)
    day_rows: Dict[date, List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        amt = _amount(row)
        if amt is None or amt >= 0 or row.operation_date is None:
            continue
        by_day[row.operation_date] += -amt
        day_rows[row.operation_date].append(row)

    if len(by_day) < 3:
        return None
    median_day = _median(list(by_day.values()))
    if median_day <= _ZERO:
        return None
    threshold = median_day * Decimal(str(thr.spike_multiplier))
    spike_days = [
        d
        for d, total in by_day.items()
        if total >= threshold and total >= thr.large_amount
    ]
    if not spike_days:
        return None
    spike_days.sort(key=lambda d: by_day[d], reverse=True)
    flagged: List[CaseFileTransaction] = []
    for d in spike_days:
        flagged.extend(_sort_by_abs_amount(day_rows[d]))
    total = sum((by_day[d] for d in spike_days), _ZERO)
    return AnomalyFinding(
        code="outflow_spike",
        title="Дни с аномальным оттоком",
        severity="medium",
        summary=(
            f"{len(spike_days)} дн. с оттоком выше обычного (медиана дня — {format_amount_rub(median_day)}), "
            f"суммарно {format_amount_rub(total)}. Резкие всплески списаний стоит проверить отдельно."
        ),
        rows=flagged[: thr.max_finding_rows],
    )


def _detect_transit(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    """Large inflow quickly followed by comparable outflow (pass-through of funds).

    For each significant credit, sum the debits within the next transit_window_days.
    If those debits cover most of the credit (>= transit_ratio), the day looks like a
    pass-through — a classic subsidiary-liability / tax red flag.
    """
    credits = [
        r
        for r in rows
        if _amount(r) is not None
        and _amount(r) > 0
        and _amount(r) >= thr.transit_min_amount
        and r.operation_date is not None
    ]
    # Only significant debits count toward transit — routine small spend after an
    # inflow (groceries, subscriptions) must not look like a pass-through.
    debit_floor = min(thr.large_amount, thr.transit_min_amount)
    debits = [
        r
        for r in rows
        if _amount(r) is not None
        and _amount(r) < 0
        and abs(_amount(r)) >= debit_floor
        and r.operation_date is not None
    ]
    if not credits or not debits:
        return None

    flagged: List[CaseFileTransaction] = []
    seen_ids: set = set()
    matches = 0
    transit_total = _ZERO
    for credit in credits:
        c_amt = _amount(credit)
        if c_amt is None:
            continue
        window_end = credit.operation_date + timedelta(days=thr.transit_window_days)
        window_debits = [
            d
            for d in debits
            if credit.operation_date <= d.operation_date <= window_end
        ]
        debit_total = sum((abs(_amount(d)) for d in window_debits if _amount(d) is not None), _ZERO)
        if debit_total >= c_amt * Decimal(str(thr.transit_ratio)):
            matches += 1
            transit_total += c_amt
            for r in [credit, *window_debits]:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    flagged.append(r)

    if matches == 0:
        return None
    flagged = _sort_by_abs_amount(flagged)
    return AnomalyFinding(
        code="transit",
        title="Транзит средств (пришло и сразу ушло)",
        severity="high",
        summary=(
            f"{matches} эпизод(ов): крупные поступления (от {format_amount_rub(thr.transit_min_amount)}) "
            f"почти сразу уходят дальше в течение {thr.transit_window_days} дн. "
            f"Транзитный характер потоков — признак вывода средств через цепочку."
        ),
        rows=flagged[: thr.max_finding_rows],
    )


def detect_recurring_transfers(
    rows: Sequence[CaseFileTransaction],
    *,
    min_ops: int = 4,
) -> List["RecurringTransfer"]:
    """Systematic debits to the same payee across time (affiliation / alimony marker)."""
    by_desc: Dict[str, List[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        amt = _amount(row)
        if amt is None or amt >= 0 or row.operation_date is None:
            continue
        by_desc[_norm_desc(row)].append(row)

    out: List[RecurringTransfer] = []
    for desc, bucket in by_desc.items():
        if desc == "—" or len(bucket) < max(2, min_ops):
            continue
        ordered = sorted(bucket, key=lambda r: r.operation_date or date.max)
        months = {(r.operation_date.year, r.operation_date.month) for r in ordered}
        if len(months) < 2:
            continue  # bunched in one month is structuring, not "regular over time"
        gaps = [
            (ordered[i].operation_date - ordered[i - 1].operation_date).days
            for i in range(1, len(ordered))
        ]
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        total = sum((abs(_amount(r)) for r in ordered if _amount(r) is not None), _ZERO)
        out.append(
            RecurringTransfer(
                description=desc,
                op_count=len(ordered),
                total_sum=total,
                date_min=ordered[0].operation_date,
                date_max=ordered[-1].operation_date,
                avg_interval_days=round(avg_gap, 1),
                rows=ordered,
            )
        )
    out.sort(key=lambda t: (t.op_count, t.total_sum), reverse=True)
    return out


def _detect_recurring(
    rows: Sequence[CaseFileTransaction],
    thr: AnomalyThresholds,
) -> Optional[AnomalyFinding]:
    recurring = detect_recurring_transfers(rows, min_ops=thr.recurring_min_ops)
    if not recurring:
        return None
    top = recurring[0]
    flagged: List[CaseFileTransaction] = []
    for t in recurring:
        flagged.extend(t.rows)
    flagged = _sort_by_abs_amount(flagged)
    return AnomalyFinding(
        code="recurring_transfer",
        title="Систематические переводы одному получателю",
        severity="medium",
        summary=(
            f"{len(recurring)} получател(я/ей) с регулярными списаниями "
            f"(≥{thr.recurring_min_ops} оп. в разные месяцы). Крупнейший: {top.description} — "
            f"{top.op_count} оп. на {format_amount_rub(top.total_sum)} "
            f"(в среднем раз в {top.avg_interval_days} дн.). "
            "Систематичность может указывать на аффилированность или регулярные обязательства."
        ),
        rows=flagged[: thr.max_finding_rows],
    )


def detect_anomalies(
    rows: Sequence[CaseFileTransaction],
    *,
    thresholds: Optional[AnomalyThresholds] = None,
) -> List[AnomalyFinding]:
    """Run all explainable risk heuristics; return findings ordered by severity."""
    thr = thresholds or AnomalyThresholds()
    detectors = (
        _detect_structuring,
        _detect_transit,
        _detect_large_cash_out,
        _detect_large_transfers,
        _detect_round_large_debits,
        _detect_recurring,
        _detect_outflow_spikes,
    )
    findings: List[AnomalyFinding] = []
    for detector in detectors:
        finding = detector(rows, thr)
        if finding is not None:
            findings.append(finding)

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank.get(f.severity, 3))
    return findings
