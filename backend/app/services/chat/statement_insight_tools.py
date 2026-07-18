"""
Analytical (insight) tools for the statement table agent.

These complement the deterministic query tools with whole-statement analysis a
lawyer needs: an overview profile, monthly cash flow, risk/anomaly heuristics and
a per-counterparty profile. Every number comes from ``statement_analytics`` (pure,
auditable code) — the model only selects tools and frames the findings.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Sequence

from langchain_core.tools import tool

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_analytics import (
    AnomalyFinding,
    AnomalyThresholds,
    CategoryBucket,
    CounterpartyProfile,
    MonthBucket,
    StatementOverview,
    compute_category_breakdown,
    compute_counterparty_profile,
    compute_monthly,
    compute_overview,
    filter_by_date_range,
    format_amount_rub,
    parse_ru_date,
    suspicion_windows,
)
from app.services.chat.statement_analytics import (
    detect_anomalies as run_anomaly_detection,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    get_statement_table_session,
)

logger = logging.getLogger(__name__)

_TOP_N = 5

INSIGHT_TOOL_NAMES = frozenset(
    {
        "statement_overview",
        "monthly_breakdown",
        "detect_anomalies",
        "counterparty_profile",
        "suspicion_period_analysis",
        "category_breakdown",
    }
)


def _record_tool(name: str) -> None:
    session = get_statement_table_session()
    session.tool_calls.append(name)


# Single source of truth for default values is AnomalyThresholds; config only overrides.
_DEFAULT_THRESHOLDS = AnomalyThresholds()


def _thresholds() -> AnomalyThresholds:
    return AnomalyThresholds(
        large_amount=Decimal(
            str(getattr(config, "STATEMENT_ANALYTICS_LARGE_AMOUNT_RUB", _DEFAULT_THRESHOLDS.large_amount))
        ),
        round_step=Decimal(
            str(getattr(config, "STATEMENT_ANALYTICS_ROUND_STEP_RUB", _DEFAULT_THRESHOLDS.round_step))
        ),
        round_min=Decimal(
            str(getattr(config, "STATEMENT_ANALYTICS_ROUND_MIN_RUB", _DEFAULT_THRESHOLDS.round_min))
        ),
        structuring_min_ops=int(
            getattr(config, "STATEMENT_ANALYTICS_STRUCTURING_MIN_OPS", _DEFAULT_THRESHOLDS.structuring_min_ops)
        ),
        structuring_window_days=int(
            getattr(config, "STATEMENT_ANALYTICS_STRUCTURING_WINDOW_DAYS", _DEFAULT_THRESHOLDS.structuring_window_days)
        ),
        spike_multiplier=float(
            getattr(config, "STATEMENT_ANALYTICS_SPIKE_MULTIPLIER", _DEFAULT_THRESHOLDS.spike_multiplier)
        ),
        max_finding_rows=int(
            getattr(config, "STATEMENT_ANALYTICS_MAX_FINDING_ROWS", _DEFAULT_THRESHOLDS.max_finding_rows)
        ),
        transit_window_days=int(
            getattr(config, "STATEMENT_ANALYTICS_TRANSIT_WINDOW_DAYS", _DEFAULT_THRESHOLDS.transit_window_days)
        ),
        transit_min_amount=Decimal(
            str(getattr(config, "STATEMENT_ANALYTICS_TRANSIT_MIN_AMOUNT_RUB", _DEFAULT_THRESHOLDS.transit_min_amount))
        ),
        transit_ratio=float(
            getattr(config, "STATEMENT_ANALYTICS_TRANSIT_RATIO", _DEFAULT_THRESHOLDS.transit_ratio)
        ),
        recurring_min_ops=int(
            getattr(config, "STATEMENT_ANALYTICS_RECURRING_MIN_OPS", _DEFAULT_THRESHOLDS.recurring_min_ops)
        ),
    )


def _period_label(d_from: Any, d_to: Any) -> str:
    if d_from and d_to:
        return f"период {_date_text(d_from)} — {_date_text(d_to)}"
    if d_from:
        return f"с {_date_text(d_from)}"
    if d_to:
        return f"до {_date_text(d_to)}"
    return "весь период выписки"


def _scoped_rows(
    session: StatementTableSession,
    date_from: str = "",
    date_to: str = "",
) -> tuple:
    """Load statement rows and optionally scope to a date window (DD.MM.YYYY).

    Returns (rows, period_label). Date scoping powers suspicion-period analysis and
    any «за такой-то период» question without changing the deterministic core.
    """
    rows = session.load_all_rows()
    d_from = parse_ru_date(date_from)
    d_to = parse_ru_date(date_to)
    if d_from is not None or d_to is not None:
        rows = filter_by_date_range(rows, d_from, d_to)
    return rows, _period_label(d_from, d_to)


def _truncation_note(session: StatementTableSession) -> str:
    """Warning appended to analytics output when the statement exceeds the scope cap."""
    if not session.rows_truncated:
        return ""
    total = session.total_row_count or 0
    analyzed = session.analyzed_row_count or 0
    return (
        f"⚠️ Внимание: в выписке {total} операций, анализ выполнен по первым "
        f"{analyzed} — суммы и находки могут быть неполными. Сузьте период фильтрами."
    )


def _apply_truncation(payload: Dict[str, Any], session: StatementTableSession) -> None:
    note = _truncation_note(session)
    if note:
        payload["truncated"] = True
        payload["total_row_count"] = session.total_row_count
        payload["warning"] = note
        session.analysis_findings.append(note)


def _date_text(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _row_brief(row: CaseFileTransaction) -> Dict[str, Any]:
    return {
        "row": int(row.global_row_index or 0) + 1,
        "date": str(row.operation_datetime_text or row.operation_date or "—"),
        "amount": str(row.amount_raw or row.amount_rub or "—"),
        "description": str(row.description or "—").strip()[:160],
        "page": int(row.page_start) if row.page_start else None,
    }


def _empty_scope_payload(session_label: str) -> str:
    return json.dumps(
        {"ok": False, "reason": "no_rows", "file_label": session_label},
        ensure_ascii=False,
    )


def _overview_summary(ov: StatementOverview) -> str:
    lines = [
        f"Профиль выписки: {ov.operation_count} операций, "
        f"период {_date_text(ov.date_min)} — {_date_text(ov.date_max)}.",
        f"Поступления: {format_amount_rub(ov.flow.inflow_sum)} ({ov.flow.inflow_count} оп.); "
        f"списания: {format_amount_rub(ov.flow.outflow_sum)} ({ov.flow.outflow_count} оп.); "
        f"сальдо: {format_amount_rub(ov.flow.net_sum)}.",
    ]
    if ov.cash_out_count:
        lines.append(
            f"Снятия наличных: {ov.cash_out_count} оп. на {format_amount_rub(ov.cash_out_sum)}."
        )
    if ov.top_outflow_counterparties:
        top = ov.top_outflow_counterparties[0]
        lines.append(
            f"Крупнейший получатель списаний: {top.description} — "
            f"{format_amount_rub(top.abs_sum)} ({top.op_count} оп.)."
        )
    return " ".join(lines)


@tool
def statement_overview(date_from: str = "", date_to: str = "") -> str:
    """
    Полный профиль выписки для открытых вопросов («что в выписке», «на что обратить внимание»).

    Возвращает: число операций, период, суммы поступлений/списаний/сальдо,
    крупнейших контрагентов по обороту, крупнейшие операции, объём снятий наличных.
    Все суммы посчитаны детерминированно. Вызови в начале анализа выписки.

    Args:
        date_from: необязательно, начало периода в формате DD.MM.YYYY
        date_to: необязательно, конец периода в формате DD.MM.YYYY
    """
    _record_tool("statement_overview")
    session = get_statement_table_session()
    rows, period = _scoped_rows(session, date_from, date_to)
    if not rows:
        return _empty_scope_payload(session.file_label)

    ov = compute_overview(rows, top_n=_TOP_N)
    session.add_citation_rows(ov.largest_operations)
    summary = f"[{period}] {_overview_summary(ov)}"
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "period": period,
        "operation_count": ov.operation_count,
        "date_min": _date_text(ov.date_min),
        "date_max": _date_text(ov.date_max),
        "inflow_sum": format_amount_rub(ov.flow.inflow_sum),
        "inflow_count": ov.flow.inflow_count,
        "outflow_sum": format_amount_rub(ov.flow.outflow_sum),
        "outflow_count": ov.flow.outflow_count,
        "net_sum": format_amount_rub(ov.flow.net_sum),
        "cash_out_count": ov.cash_out_count,
        "cash_out_sum": format_amount_rub(ov.cash_out_sum),
        "top_outflow_counterparties": [
            {
                "description": s.description,
                "op_count": s.op_count,
                "abs_sum": format_amount_rub(s.abs_sum),
            }
            for s in ov.top_outflow_counterparties
        ],
        "top_inflow_counterparties": [
            {
                "description": s.description,
                "op_count": s.op_count,
                "abs_sum": format_amount_rub(s.abs_sum),
            }
            for s in ov.top_inflow_counterparties
        ],
        "largest_operations": [_row_brief(r) for r in ov.largest_operations],
        "summary": summary,
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] overview file=%s ops=%s truncated=%s",
        session.file_id,
        ov.operation_count,
        session.rows_truncated,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def monthly_breakdown(date_from: str = "", date_to: str = "") -> str:
    """
    Динамика по месяцам: поступления, списания, сальдо и число операций за каждый месяц.

    Используй для вопросов о трендах, «куда уходят деньги», сравнения периодов.

    Args:
        date_from: необязательно, начало периода в формате DD.MM.YYYY
        date_to: необязательно, конец периода в формате DD.MM.YYYY
    """
    _record_tool("monthly_breakdown")
    session = get_statement_table_session()
    rows, period = _scoped_rows(session, date_from, date_to)
    if not rows:
        return _empty_scope_payload(session.file_label)

    buckets: List[MonthBucket] = compute_monthly(rows)
    if not buckets:
        return json.dumps({"ok": False, "reason": "no_dated_rows"}, ensure_ascii=False)

    summary = (
        f"Помесячная динамика ({len(buckets)} мес.): "
        + "; ".join(
            f"{b.label}: приток {format_amount_rub(b.inflow_sum)}, "
            f"отток {format_amount_rub(b.outflow_sum)}, сальдо {format_amount_rub(b.net_sum)}"
            for b in buckets
        )
    )
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "period": period,
        "months": [
            {
                "month": b.label,
                "inflow_sum": format_amount_rub(b.inflow_sum),
                "outflow_sum": format_amount_rub(b.outflow_sum),
                "net_sum": format_amount_rub(b.net_sum),
                "op_count": b.op_count,
            }
            for b in buckets
        ],
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] monthly file=%s months=%s", session.file_id, len(buckets)
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _anomaly_payload(finding: AnomalyFinding) -> Dict[str, Any]:
    return {
        "code": finding.code,
        "title": finding.title,
        "severity": finding.severity,
        "summary": finding.summary,
        "examples": [_row_brief(r) for r in finding.rows],
    }


@tool
def detect_anomalies(date_from: str = "", date_to: str = "") -> str:
    """
    Поиск подозрительных паттернов в выписке (детерминированные эвристики).

    Проверяет: дробление платежей одному получателю, транзит (пришло и сразу ушло),
    крупные снятия наличных, крупные и круглые переводы, систематические переводы
    одному получателю, дни с аномальным оттоком. Вызови на вопросы «что
    подозрительного», «есть ли вывод активов», «на что обратить внимание».
    Не выносит юридических выводов — только помечает операции для проверки.

    Args:
        date_from: необязательно, начало периода в формате DD.MM.YYYY (например, для окна подозрительности)
        date_to: необязательно, конец периода в формате DD.MM.YYYY
    """
    _record_tool("detect_anomalies")
    session = get_statement_table_session()
    rows, period = _scoped_rows(session, date_from, date_to)
    if not rows:
        return _empty_scope_payload(session.file_label)

    findings = run_anomaly_detection(rows, thresholds=_thresholds())
    for finding in findings:
        session.add_citation_rows(finding.rows)

    if not findings:
        summary = f"[{period}] Явных подозрительных паттернов по эвристикам не выявлено."
        session.analysis_findings.append(summary)
        empty_payload: Dict[str, Any] = {
            "ok": True,
            "period": period,
            "findings": [],
            "summary": summary,
        }
        _apply_truncation(empty_payload, session)
        return json.dumps(empty_payload, ensure_ascii=False)

    summary = f"[{period}] Выявлены зоны внимания: " + "; ".join(
        f"{f.title} ({f.severity})" for f in findings
    )
    session.analysis_findings.append(summary)
    session.analysis_findings.extend(f.summary for f in findings)

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "period": period,
        "findings": [_anomaly_payload(f) for f in findings],
        "summary": summary,
        "disclaimer": (
            "Эвристики помечают операции для ручной проверки, а не доказывают нарушение."
        ),
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] anomalies file=%s findings=%s",
        session.file_id,
        [f.code for f in findings],
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _counterparty_summary(profile: CounterpartyProfile) -> str:
    return (
        f"Контрагент «{profile.token}»: {profile.op_count} оп. "
        f"за {_date_text(profile.date_min)} — {_date_text(profile.date_max)}; "
        f"поступления {format_amount_rub(profile.inflow_sum)}, "
        f"списания {format_amount_rub(profile.outflow_sum)}, "
        f"сальдо {format_amount_rub(profile.net_sum)}."
    )


@tool
def counterparty_profile(token: str, date_from: str = "", date_to: str = "") -> str:
    """
    Карточка одного контрагента/назначения: сколько операций, суммы, период, примеры.

    Args:
        token: имя/фрагмент контрагента или назначения платежа из вопроса юриста
        date_from: необязательно, начало периода в формате DD.MM.YYYY
        date_to: необязательно, конец периода в формате DD.MM.YYYY
    """
    _record_tool("counterparty_profile")
    session = get_statement_table_session()
    needle = (token or "").strip()
    if not needle:
        return json.dumps(
            {"ok": False, "reason": "empty_token"}, ensure_ascii=False
        )

    rows, period = _scoped_rows(session, date_from, date_to)
    if not rows:
        return _empty_scope_payload(session.file_label)

    profile = compute_counterparty_profile(rows, needle)
    if not profile.matched:
        return json.dumps(
            {
                "ok": True,
                "matched": False,
                "token": needle,
                "hint": "Операций по этому контрагенту не найдено — уточни токен.",
            },
            ensure_ascii=False,
        )

    max_rows = int(getattr(config, "STATEMENT_ANALYTICS_MAX_FINDING_ROWS", 10))
    example_rows = _sort_examples(profile.rows)[:max_rows]
    session.add_citation_rows(example_rows)
    summary = _counterparty_summary(profile)
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "matched": True,
        "token": needle,
        "period": period,
        "op_count": profile.op_count,
        "inflow_sum": format_amount_rub(profile.inflow_sum),
        "outflow_sum": format_amount_rub(profile.outflow_sum),
        "net_sum": format_amount_rub(profile.net_sum),
        "date_min": _date_text(profile.date_min),
        "date_max": _date_text(profile.date_max),
        "examples": [_row_brief(r) for r in example_rows],
        "summary": summary,
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] counterparty file=%s token=%r ops=%s",
        session.file_id,
        needle,
        profile.op_count,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def suspicion_period_analysis(petition_date: str) -> str:
    """
    Разбор выписки по периодам подозрительности банкротства относительно даты принятия
    заявления (ст. 61.2 / 61.3 № 127-ФЗ): 1 месяц и 6 месяцев (предпочтение), 1 год
    (неравноценность), 3 года (вред кредиторам).

    Для каждого окна: приток/отток/сальдо, число операций и краткий список
    подозрительных паттернов. Вызови, когда юрист указал дату принятия заявления или
    спрашивает про «подозрительный период», «за год/три года до банкротства».

    Args:
        petition_date: дата принятия заявления о банкротстве в формате DD.MM.YYYY
    """
    _record_tool("suspicion_period_analysis")
    session = get_statement_table_session()
    anchor = parse_ru_date(petition_date)
    if anchor is None:
        return json.dumps(
            {"ok": False, "reason": "bad_petition_date", "hint": "Ожидается дата DD.MM.YYYY."},
            ensure_ascii=False,
        )

    all_rows = session.load_all_rows()
    if not all_rows:
        return _empty_scope_payload(session.file_label)

    thr = _thresholds()
    windows_out: List[Dict[str, Any]] = []
    summary_parts: List[str] = []
    for code, label, d_from, d_to in suspicion_windows(anchor):
        scoped = filter_by_date_range(all_rows, d_from, d_to)
        ov = compute_overview(scoped, top_n=3) if scoped else None
        findings = run_anomaly_detection(scoped, thresholds=thr) if scoped else []
        for finding in findings:
            session.add_citation_rows(finding.rows)
        window_summary = (
            f"{label}: {len(scoped)} оп., "
            f"отток {format_amount_rub(ov.flow.outflow_sum) if ov else format_amount_rub(0)}"
            + (f"; зоны внимания: {', '.join(f.title for f in findings)}" if findings else "; зон внимания нет")
        )
        summary_parts.append(window_summary)
        windows_out.append(
            {
                "basis": code,
                "label": label,
                "date_from": _date_text(d_from),
                "date_to": _date_text(d_to),
                "operation_count": len(scoped),
                "inflow_sum": format_amount_rub(ov.flow.inflow_sum) if ov else format_amount_rub(0),
                "outflow_sum": format_amount_rub(ov.flow.outflow_sum) if ov else format_amount_rub(0),
                "net_sum": format_amount_rub(ov.flow.net_sum) if ov else format_amount_rub(0),
                "findings": [
                    {"code": f.code, "title": f.title, "severity": f.severity}
                    for f in findings
                ],
            }
        )

    summary = f"Периоды подозрительности от {_date_text(anchor)}. " + " | ".join(summary_parts)
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "petition_date": _date_text(anchor),
        "windows": windows_out,
        "summary": summary,
        "disclaimer": (
            "Окна и суммы детерминированы; юридическую квалификацию сделок делает юрист."
        ),
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] suspicion file=%s petition=%s", session.file_id, _date_text(anchor)
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _category_summary(buckets: Sequence[CategoryBucket], period: str) -> str:
    parts = [
        f"{b.label}: {b.op_count} оп., отток {format_amount_rub(b.outflow_sum)}"
        for b in buckets
        if b.outflow_sum > Decimal("0") or b.inflow_sum > Decimal("0")
    ]
    return f"[{period}] Структура операций — " + "; ".join(parts)


@tool
def category_breakdown(date_from: str = "", date_to: str = "") -> str:
    """
    Разбивка операций по категориям назначения: наличные, займы/кредиты, налоги и
    взносы, ЖКХ/связь/аренда, зарплата, переводы физлицам, покупки, прочее.

    Помогает отделить рутину от значимого («покажи только займы и переводы физлицам»,
    «сколько ушло наличными и физлицам»).

    Args:
        date_from: необязательно, начало периода в формате DD.MM.YYYY
        date_to: необязательно, конец периода в формате DD.MM.YYYY
    """
    _record_tool("category_breakdown")
    session = get_statement_table_session()
    rows, period = _scoped_rows(session, date_from, date_to)
    if not rows:
        return _empty_scope_payload(session.file_label)

    buckets = compute_category_breakdown(rows)
    summary = _category_summary(buckets, period)
    session.analysis_findings.append(summary)

    # Register a few representative rows per category so the answer links to the PDF.
    for b in buckets:
        session.add_citation_rows(_sort_examples(b.rows)[:2])

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "period": period,
        "categories": [
            {
                "category": b.category,
                "label": b.label,
                "op_count": b.op_count,
                "inflow_sum": format_amount_rub(b.inflow_sum),
                "outflow_sum": format_amount_rub(b.outflow_sum),
                "examples": [_row_brief(r) for r in _sort_examples(b.rows)[:2]],
            }
            for b in buckets
        ],
        "summary": summary,
    }
    _apply_truncation(payload, session)
    logger.info(
        "[StatementInsight] categories file=%s buckets=%s", session.file_id, len(buckets)
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _sort_examples(rows: Sequence[CaseFileTransaction]) -> List[CaseFileTransaction]:
    return sorted(
        rows,
        key=lambda r: (abs(r.amount_rub) if r.amount_rub is not None else Decimal("0")),
        reverse=True,
    )


def build_statement_insight_tools() -> list:
    """Analytical tools for create_agent (bound via the same ContextVar session)."""
    return [
        statement_overview,
        monthly_breakdown,
        detect_anomalies,
        counterparty_profile,
        suspicion_period_analysis,
        category_breakdown,
    ]
