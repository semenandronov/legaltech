"""
Lawyer-grade statement toolkit — eight complementary tools for the Operations agent.

Design (one mental model for the LLM):
  context → (calendar | flow | risk) → entity → query → evidence

Each tool maps to a step experienced bankruptcy counsel takes; internals stay
deterministic (statement_analytics + StatementSqlPlan executor). Legacy granular
tools (inspect_statement, statement_overview, …) remain for tests and eval scripts.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from langchain_core.tools import tool

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat import statement_insight_tools as insight
from app.services.chat.statement_analytics import (
    compute_category_breakdown,
    compute_counterparty_profile,
    compute_monthly,
    compute_money_flow,
    compute_overview,
    filter_by_date_range,
    format_amount_rub,
    parse_ru_date,
    suspicion_windows,
)
from app.services.chat.statement_analytics import (
    detect_anomalies as run_anomaly_detection,
)
from app.services.chat.statement_entity_grounding import (
    entity_needle_candidates,
    select_best_entity_token,
    stem_probe_variants,
)
from app.services.chat.statement_sql_value_grounding import (
    DbDescriptionMatchProbe,
    RowsDescriptionMatchProbe,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    get_statement_table_session,
)
from app.services.chat.statement_table_tools import (
    AmountCompare,
    AmountSemantics,
    GroupOrder,
    StatementToolOperation,
    _sample_descriptions,
    run_statement_query,
)
from app.services.chat.statement_entity_grounding import (
    entity_needle_candidates,
    stem_probe_variants,
)
from app.services.chat.statement_lawyer_tool_registry import (
    ANALYTICAL_LAWYER_TOOL_NAMES,
    ENTITY_LAWYER_TOOL_NAMES,
    LAWYER_TOOL_WORKFLOWS,
    QUERY_LAWYER_TOOL_NAMES,
    STATEMENT_LAWYER_TOOL_NAMES,
)
from app.services.transaction_description_match import (
    any_field_description_token_match,
    description_token_match,
    iter_description_tokens,
)

logger = logging.getLogger(__name__)


def _record_tool(name: str) -> None:
    session = get_statement_table_session()
    session.tool_calls.append(name)


def _rows_probe(session: StatementTableSession) -> RowsDescriptionMatchProbe | DbDescriptionMatchProbe:
    if session.uses_in_memory_rows:
        return RowsDescriptionMatchProbe(rows=list(session.rows or []))
    assert session.db is not None
    return DbDescriptionMatchProbe(
        db=session.db,
        case_id=session.case_id,
        file_id=session.file_id,
    )


def _suggest_tokens(rows: Sequence[CaseFileTransaction], hint: str, limit: int = 8) -> List[Dict[str, Any]]:
    hint_l = (hint or "").strip().lower()
    if not hint_l or len(hint_l) < 2:
        return []
    counter: Counter[str] = Counter()
    for row in rows:
        hay = str(row.description or "")
        if not hay.strip():
            continue
        matched = False
        for token in iter_description_tokens(hay):
            tl = token.lower()
            if len(tl) < 3:
                continue
            if hint_l in tl or tl.startswith(hint_l[: min(4, len(hint_l))]):
                counter[token] += 1
                matched = True
        if not matched and description_token_match(hay, hint):
            counter[hint.strip()] += 1

    out: List[Dict[str, Any]] = []
    for token, count in counter.most_common(limit):
        out.append({"token": token, "match_count": count})
    return out


@tool
def statement_context() -> str:
    """
    Шаг 1 — контекст: файл, период, сколько операций в области (в т.ч. фильтры UI),
    примеры описаний. Вызови первым, если не уверен в scope или формате выписки.
    """
    _record_tool("statement_context")
    session = get_statement_table_session()

    if session.uses_in_memory_rows:
        rows = list(session.rows or [])
        dates = [r.operation_date for r in rows if r.operation_date is not None]
        date_min = min(dates).strftime("%d.%m.%Y") if dates else "—"
        date_max = max(dates).strftime("%d.%m.%Y") if dates else "—"
        total_in_file = len(rows)
    else:
        assert session.db is not None
        page = CaseFileTransactionService.query_page(
            session.db,
            case_id=session.case_id,
            file_id=session.file_id,
            limit=1,
            offset=0,
        )
        total_in_file = int(page.total or 0)
        summaries = CaseFileTransactionService.list_available_files(session.db, session.case_id)
        match = next((s for s in summaries if s.file_id == session.file_id), None)
        date_min = match.date_min.strftime("%d.%m.%Y") if match and match.date_min else "—"
        date_max = match.date_max.strftime("%d.%m.%Y") if match and match.date_max else "—"

    samples = _sample_descriptions()

    summary = (
        f"Выписка «{session.file_label}»: {total_in_file} операций в области, "
        f"период {date_min} — {date_max}."
    )
    if session.scope_note.strip():
        summary += f" {session.scope_note.strip()}"
    session.analysis_findings.append(summary)

    payload: Dict[str, Any] = {
        "ok": True,
        "file_id": session.file_id,
        "file_label": session.file_label,
        "operation_count": total_in_file,
        "date_min": date_min,
        "date_max": date_max,
        "scope_note": session.scope_note or None,
        "sample_descriptions": samples,
        "summary": summary,
        "next_steps_hint": (
            "Открытый разбор → flow_profile + risk_scan. "
            "Контрагент → resolve_entity. Факт → transactions_query."
        ),
    }
    insight._apply_truncation(payload, session)
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def resolve_entity(hint: str, question: str = "") -> str:
    """
    Найди, как имя/контрагент из вопроса пишется в текстах операций.

    Возвращает: проверку hint, лучший grounded token, подсказки-autocomplete,
    примеры строк. Вызови ПЕРЕД transactions_query/counterparty_dossier, если в
    вопросе ФИО, ИП, ООО или фрагмент назначения.

    Args:
        hint: фамилия, бренд или фрагмент из вопроса юриста
        question: полный вопрос (необязательно; улучшает grounding ФИО)
    """
    _record_tool("resolve_entity")
    session = get_statement_table_session()
    needle = (hint or "").strip()
    q = (question or session.question or "").strip()
    rows = session.load_all_rows()
    if not rows:
        return insight._empty_scope_payload(session.file_label)

    probe = _rows_probe(session)
    candidates = entity_needle_candidates(q or needle)
    if needle and needle not in candidates:
        for v in stem_probe_variants(needle):
            if v not in candidates:
                candidates.insert(0, v)

    grounded = select_best_entity_token(
        q or needle,
        rows=rows,
        db=session.db,
        case_id=session.case_id,
        file_id=session.file_id,
    )
    direct_count = probe.count(needle) if needle else 0
    suggestions = _suggest_tokens(rows, needle or q, limit=8)

    examples: List[str] = []
    use_token = grounded or (needle if direct_count else "")
    if use_token:
        for row in rows[:400]:
            haystacks = (
                str(row.description or ""),
                str(row.operation_datetime_text or ""),
                str(row.amount_raw or ""),
            )
            if any_field_description_token_match(haystacks, use_token):
                text = str(row.description or "").strip()
                if text and text not in examples:
                    examples.append(text[:160])
                if len(examples) >= 5:
                    break

    best = grounded or (needle if direct_count else "")
    best_count = probe.count(best) if best else 0
    ok = best_count > 0

    summary = (
        f"Поиск «{needle or q[:40]}»: "
        + (f"лучший token «{best}» — {best_count} оп." if ok else "совпадений нет")
    )
    session.analysis_findings.append(summary)

    payload = {
        "ok": ok,
        "hint": needle,
        "grounded_token": best or None,
        "match_count": best_count,
        "suggestions": suggestions,
        "examples": examples,
        "summary": summary,
        "next_steps_hint": (
            "Если ok — counterparty_dossier(grounded_token) или "
            "transactions_query с description_contains=grounded_token. "
            "Если нет — уточни hint или покажи suggestions юристу."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def transactions_query(
    operation: StatementToolOperation,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    time_hint: str = "",
    description_contains: str = "",
    amount_semantics: AmountSemantics = "any",
    amount_compare: AmountCompare = "none",
    amount_min: str = "",
    amount_max: str = "",
    result_limit: str = "",
    group_order: GroupOrder = "abs_sum",
    group_min_count: str = "",
) -> str:
    """
    Скальpel — точные факты: count/sum/list/find/top/group по таблице операций.

    После resolve_entity используй grounded_token в description_contains.
    Даты DD.MM.YYYY; credit=поступления, debit=списания.
    """
    return run_statement_query(
        record_as="transactions_query",
        operation=operation,
        on_date=on_date,
        date_from=date_from,
        date_to=date_to,
        time_hint=time_hint,
        description_contains=description_contains,
        amount_semantics=amount_semantics,
        amount_compare=amount_compare,
        amount_min=amount_min,
        amount_max=amount_max,
        result_limit=result_limit,
        group_order=group_order,
        group_min_count=group_min_count,
    )


@tool
def flow_profile(date_from: str = "", date_to: str = "") -> str:
    """
    Картина денег: приток/отток/сальdo, топ контрагентов, крупные операции,
    помесячная динамика за период. Для «что в выписке», «куда уходят деньги».
    """
    _record_tool("flow_profile")
    session = get_statement_table_session()
    rows, period = insight._scoped_rows(session, date_from, date_to)
    if not rows:
        return insight._empty_scope_payload(session.file_label)

    ov = compute_overview(rows, top_n=insight._TOP_N)
    session.add_citation_rows(ov.largest_operations)
    months = compute_monthly(rows)

    overview_summary = insight._overview_summary(ov)
    monthly_part = "; ".join(
        f"{b.label}: отток {format_amount_rub(b.outflow_sum)}"
        for b in months[:6]
    )
    summary = f"[{period}] {overview_summary}"
    if monthly_part:
        summary += f" Динамика (фрагмент): {monthly_part}."
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "file_label": session.file_label,
        "period": period,
        "operation_count": ov.operation_count,
        "date_min": insight._date_text(ov.date_min),
        "date_max": insight._date_text(ov.date_max),
        "inflow_sum": format_amount_rub(ov.flow.inflow_sum),
        "outflow_sum": format_amount_rub(ov.flow.outflow_sum),
        "net_sum": format_amount_rub(ov.flow.net_sum),
        "cash_out_sum": format_amount_rub(ov.cash_out_sum),
        "top_outflow_counterparties": [
            {"description": s.description, "op_count": s.op_count, "abs_sum": format_amount_rub(s.abs_sum)}
            for s in ov.top_outflow_counterparties
        ],
        "largest_operations": [insight._row_brief(r) for r in ov.largest_operations],
        "monthly": [
            {
                "month": b.label,
                "inflow_sum": format_amount_rub(b.inflow_sum),
                "outflow_sum": format_amount_rub(b.outflow_sum),
                "net_sum": format_amount_rub(b.net_sum),
                "op_count": b.op_count,
            }
            for b in months
        ],
        "summary": summary,
        "next_steps_hint": "Подозрительные паттерны → risk_scan; банкротство → legal_calendar.",
    }
    insight._apply_truncation(payload, session)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _baseline_before_window(d_from: date, d_to: date) -> Tuple[date, date]:
    length = (d_to - d_from).days + 1
    end = d_from - timedelta(days=1)
    start = end - timedelta(days=max(0, length - 1))
    return start, end


@tool
def legal_calendar(petition_date: str) -> str:
    """
    Юридический календарь банкротства: окна 61.2/61.3 от даты принятия заявления.

    В каждом окне — оборот и findings; также контраст с равным периодом «до окна».
    """
    _record_tool("legal_calendar")
    session = get_statement_table_session()
    anchor = parse_ru_date(petition_date)
    if anchor is None:
        return json.dumps(
            {"ok": False, "reason": "bad_petition_date", "hint": "DD.MM.YYYY"},
            ensure_ascii=False,
        )

    all_rows = session.load_all_rows()
    if not all_rows:
        return insight._empty_scope_payload(session.file_label)

    thr = insight._thresholds()
    windows_out: List[Dict[str, Any]] = []
    summary_parts: List[str] = []

    for code, label, d_from, d_to in suspicion_windows(anchor):
        scoped = filter_by_date_range(all_rows, d_from, d_to)
        ov = compute_overview(scoped, top_n=3) if scoped else None
        findings = run_anomaly_detection(scoped, thresholds=thr) if scoped else []
        for finding in findings:
            session.add_citation_rows(finding.rows)

        b_start, b_end = _baseline_before_window(d_from, d_to)
        baseline_rows = filter_by_date_range(all_rows, b_start, b_end)
        b_flow = compute_money_flow(baseline_rows) if baseline_rows else None
        w_out = ov.flow.outflow_sum if ov else Decimal("0")
        b_out = b_flow.outflow_sum if b_flow else Decimal("0")
        contrast = None
        if b_out > 0 and w_out > 0:
            contrast = float(w_out / b_out)

        window_summary = (
            f"{label}: {len(scoped)} оп., отток {format_amount_rub(w_out)}"
            + (f"; vs период до окна: ×{contrast:.2f} по оттоку" if contrast and contrast != 1.0 else "")
            + (f"; зоны: {', '.join(f.title for f in findings)}" if findings else "")
        )
        summary_parts.append(window_summary)
        windows_out.append(
            {
                "basis": code,
                "label": label,
                "date_from": insight._date_text(d_from),
                "date_to": insight._date_text(d_to),
                "operation_count": len(scoped),
                "outflow_sum": format_amount_rub(w_out),
                "baseline_period": f"{insight._date_text(b_start)} — {insight._date_text(b_end)}",
                "baseline_outflow_sum": format_amount_rub(b_out),
                "outflow_ratio_vs_baseline": contrast,
                "findings": [{"code": f.code, "title": f.title, "severity": f.severity} for f in findings],
            }
        )

    summary = f"Календарь от {insight._date_text(anchor)}. " + " | ".join(summary_parts)
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "petition_date": insight._date_text(anchor),
        "windows": windows_out,
        "summary": summary,
        "disclaimer": "Квалификацию сделок определяет юрист; окна детерминированы.",
        "next_steps_hint": "Углубление по окну → risk_scan(date_from, date_to) или counterparty_dossier.",
    }
    insight._apply_truncation(payload, session)
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def risk_scan(date_from: str = "", date_to: str = "") -> str:
    """
    Чеклист рисков + структура по типам операций (наличные, займы, ФЛ, налоги…)
    за период. Для «что подозрительного», «на что смотреть».
    """
    _record_tool("risk_scan")
    session = get_statement_table_session()
    rows, period = insight._scoped_rows(session, date_from, date_to)
    if not rows:
        return insight._empty_scope_payload(session.file_label)

    findings = run_anomaly_detection(rows, thresholds=insight._thresholds())
    for finding in findings:
        session.add_citation_rows(finding.rows)

    buckets = compute_category_breakdown(rows)
    for b in buckets:
        session.add_citation_rows(insight._sort_examples(b.rows)[:2])

    if not findings:
        risk_line = "Явных паттернов по эвристикам не выявлено."
    else:
        risk_line = "Зоны внимания: " + "; ".join(f"{f.title} ({f.severity})" for f in findings)

    cat_line = insight._category_summary(buckets, period)
    summary = f"[{period}] {risk_line} {cat_line}"
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "period": period,
        "findings": [insight._anomaly_payload(f) for f in findings],
        "categories": [
            {
                "label": b.label,
                "op_count": b.op_count,
                "outflow_sum": format_amount_rub(b.outflow_sum),
            }
            for b in buckets
            if b.outflow_sum > Decimal("0") or b.inflow_sum > Decimal("0")
        ],
        "summary": summary,
        "disclaimer": "Эвристики для проверки, не доказательство нарушения.",
        "next_steps_hint": "Контрагент из finding → counterparty_dossier; строки → evidence_bundle.",
    }
    insight._apply_truncation(payload, session)
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def counterparty_dossier(
    token: str,
    date_from: str = "",
    date_to: str = "",
    list_limit: str = "15",
) -> str:
    """
    Досье контрагента: операции, суммы, период, примеры и список ключевых строк.
    После resolve_entity используй grounded_token.
    """
    _record_tool("counterparty_dossier")
    session = get_statement_table_session()
    needle = (token or "").strip()
    if not needle:
        return json.dumps({"ok": False, "reason": "empty_token"}, ensure_ascii=False)

    rows, period = insight._scoped_rows(session, date_from, date_to)
    if not rows:
        return insight._empty_scope_payload(session.file_label)

    profile = compute_counterparty_profile(rows, needle)
    if not profile.matched:
        summary = f"[{period}] Операций по «{needle}» не найдено."
        session.analysis_findings.append(summary)
        return json.dumps(
            {
                "ok": True,
                "matched": False,
                "token": needle,
                "summary": summary,
                "next_steps_hint": "Вызови resolve_entity с другим hint.",
            },
            ensure_ascii=False,
        )

    try:
        lim = max(1, min(50, int(list_limit or "15")))
    except ValueError:
        lim = 15

    examples = insight._sort_examples(profile.rows)[:lim]
    session.add_citation_rows(examples)

    summary = (
        f"[{period}] «{needle}»: {profile.op_count} оп.; "
        f"поступления {format_amount_rub(profile.inflow_sum)}, "
        f"списания {format_amount_rub(profile.outflow_sum)}, "
        f"сальдо {format_amount_rub(profile.net_sum)}."
    )
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
        "date_min": insight._date_text(profile.date_min),
        "date_max": insight._date_text(profile.date_max),
        "operations": [insight._row_brief(r) for r in examples],
        "summary": summary,
        "next_steps_hint": "Полный перечень → evidence_bundle или transactions_query list.",
    }
    insight._apply_truncation(payload, session)
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def evidence_bundle(
    description_contains: str = "",
    date_from: str = "",
    date_to: str = "",
    amount_compare: AmountCompare = "none",
    amount_min: str = "",
    amount_max: str = "",
    max_rows: str = "20",
) -> str:
    """
    Пакет строк под процесс: дата, сумма, назначение, страница PDF.
    Фильтры как у transactions_query; по умолчанию list до max_rows.
    """
    _record_tool("evidence_bundle")
    try:
        limit = max(1, min(50, int(max_rows or "20")))
    except ValueError:
        limit = 20

    raw = run_statement_query(
        record_as="evidence_bundle_query",
        operation="list",
        date_from=date_from,
        date_to=date_to,
        description_contains=description_contains,
        amount_compare=amount_compare,
        amount_min=amount_min,
        amount_max=amount_max,
        result_limit=str(limit),
    )
    session = get_statement_table_session()
    rows = list(session.last_execution.rows if session.last_execution else [])[:limit]
    bundle = [insight._row_brief(r) for r in rows]
    count = session.last_facts.row_count if session.last_facts else len(bundle)

    summary = f"Пакет доказательств: {count} операций (показано {len(bundle)})."
    session.analysis_findings.append(summary)

    payload = {
        "ok": True,
        "row_count": count,
        "shown": len(bundle),
        "rows": bundle,
        "evidence_note": "Используй эти строки в ответе и ссылках на PDF.",
        "query_evidence": raw[:2000] if raw else "",
        "summary": summary,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_statement_lawyer_tools() -> list:
    """Eight-tool toolkit for create_agent on the Operations statement chat."""
    return [
        statement_context,
        resolve_entity,
        transactions_query,
        flow_profile,
        legal_calendar,
        risk_scan,
        counterparty_dossier,
        evidence_bundle,
    ]
