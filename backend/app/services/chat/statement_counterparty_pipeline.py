"""
Deterministic multi-pass counterparty lookup (lawyer-facing).

Mimics a careful analyst: surname in payment text → if empty, name+patronymic
with an explicit ambiguity note — no whole-statement counts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_analytics import (
    CounterpartyProfile,
    compute_counterparty_profile,
    compute_money_flow,
    format_amount_rub,
    _row_dates,
)
from app.services.chat.statement_entity_grounding import (
    _is_patronymic_anchor,
    _person_surname_anchors,
    ground_counterparty_needle,
    stem_probe_variants,
)
from app.services.chat.statement_sql_plan_validate import extract_content_tokens
from app.services.chat.statement_table_session import StatementTableSession
from app.services.chat.statement_table_turn_contract import _repair_patch

logger = logging.getLogger(__name__)

_YES_NO_RE = re.compile(r"\b(были\s+ли|есть\s+ли|нашли\s+ли)\b", re.IGNORECASE)


@dataclass(frozen=True)
class CounterpartyInvestigation:
    surname_label: str
    surname_profile: Optional[object]
    name_patronymic_parts: tuple[str, ...]
    name_patronymic_profile: Optional[object]
    org_needle: str


def _rows_matching_all_parts(
    rows: Sequence[CaseFileTransaction],
    parts: Sequence[str],
) -> List[CaseFileTransaction]:
    normalized = [p.lower() for p in parts if (p or "").strip()]
    if not normalized:
        return []
    out: List[CaseFileTransaction] = []
    for row in rows:
        hay = " ".join(
            (
                str(row.description or ""),
                str(row.operation_datetime_text or ""),
                str(row.verbatim_row_text or ""),
            )
        ).lower()
        if all(part in hay for part in normalized):
            out.append(row)
    return out


def _counterparty_profile_from_rows(
    rows: Sequence[CaseFileTransaction],
    label: str,
) -> CounterpartyProfile:
    matched = list(rows)
    flow = compute_money_flow(matched)
    dates = _row_dates(matched)
    return CounterpartyProfile(
        token=label,
        matched=bool(matched),
        op_count=len(matched),
        inflow_sum=flow.inflow_sum,
        outflow_sum=flow.outflow_sum,
        net_sum=flow.net_sum,
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        rows=matched,
    )


def _primary_surname_label(
    question: str,
    rows: Optional[Sequence[CaseFileTransaction]] = None,
) -> str:
    for anchor in _person_surname_anchors(question):
        if _is_patronymic_anchor(anchor):
            continue
        head = (anchor.split()[0] if anchor else "").strip()
        if not head:
            continue
        variants = stem_probe_variants(head)
        if rows is not None:
            best = ""
            best_hits = -1
            for variant in variants:
                if len(variant) < 5:
                    continue
                profile = compute_counterparty_profile(rows, variant)
                hits = profile.op_count if profile.matched else 0
                if hits > best_hits or (
                    hits == best_hits and len(variant) < len(best or variant)
                ):
                    best_hits = hits
                    best = variant
            if best:
                return best
        for variant in reversed(variants):
            if len(variant) >= 5:
                return variant
    return ""


def _name_patronymic_search_parts(question: str) -> tuple[str, ...]:
    """Stems for «имя + отчество» secondary search when surname absent in texts."""
    tokens = list(extract_content_tokens(question))
    patronymic: Optional[str] = None
    given: Optional[str] = None
    surname_heads: set[str] = set()
    for anchor in _person_surname_anchors(question):
        if _is_patronymic_anchor(anchor):
            continue
        surname_heads.add((anchor.split()[0] if anchor else "").lower())
        break

    def _same_stem_family(a: str, b: str) -> bool:
        al, bl = a.lower(), b.lower()
        if al == bl:
            return True
        stems_a = {v.lower() for v in stem_probe_variants(a)}
        stems_b = {v.lower() for v in stem_probe_variants(b)}
        return bool(stems_a & stems_b)

    for token in tokens:
        if _is_patronymic_anchor(token) and len(token) >= 8:
            patronymic = token
            break

    for token in tokens:
        if token == patronymic or _is_patronymic_anchor(token):
            continue
        head = token.split()[0]
        if head.lower() in surname_heads:
            continue
        if any(_same_stem_family(head, s) for s in surname_heads):
            continue
        if len(token) >= 4 and re.match(r"^[А-ЯЁа-яё]", token):
            given = token
            break

    if not given or not patronymic:
        return ()

    given_stem = ""
    for variant in reversed(list(stem_probe_variants(given))):
        if len(variant) >= 4:
            given_stem = variant.lower()
            break
    pat_stem = ""
    for variant in reversed(list(stem_probe_variants(patronymic))):
        if len(variant) >= 6:
            pat_stem = variant.lower()
            break
    if given_stem and pat_stem:
        return (given_stem, pat_stem)
    return ()


def investigate_counterparty(
    question: str,
    rows: Sequence[CaseFileTransaction],
) -> CounterpartyInvestigation:
    q = (question or "").strip()
    surname_label = _primary_surname_label(q, rows)
    org_needle = ""
    if not surname_label:
        org_needle = ground_counterparty_needle(q, rows=rows)

    surname_profile = None
    if surname_label:
        surname_profile = compute_counterparty_profile(rows, surname_label)

    parts = _name_patronymic_search_parts(q)
    name_patronymic_profile = None
    if parts:
        matched = _rows_matching_all_parts(rows, parts)
        label = " + ".join(parts)
        name_patronymic_profile = _counterparty_profile_from_rows(matched, label)

    return CounterpartyInvestigation(
        surname_label=surname_label,
        surname_profile=surname_profile,
        name_patronymic_parts=parts,
        name_patronymic_profile=name_patronymic_profile,
        org_needle=org_needle or surname_label,
    )


def _format_examples(rows: Sequence[CaseFileTransaction], limit: int = 5) -> List[str]:
    lines: List[str] = []
    for row in rows[:limit]:
        dt = (row.operation_datetime_text or "").strip()
        amt = row.amount_rub
        desc = (row.description or "").strip()
        if len(desc) > 160:
            desc = desc[:157] + "…"
        amt_s = format_amount_rub(amt) if amt is not None else "—"
        lines.append(f"• {dt}: {amt_s} — {desc}")
    return lines


def compose_counterparty_lawyer_answer(
    *,
    session: StatementTableSession,
    question: str,
    investigation: CounterpartyInvestigation,
) -> str:
    scope = f"{session.scope_note.strip()} " if session.scope_note.strip() else ""
    label = session.file_label or "выписке"
    yes_no = bool(_YES_NO_RE.search(question or ""))

    sp = investigation.surname_profile
    np = investigation.name_patronymic_profile
    surname = investigation.surname_label
    surname_hits = sp.op_count if sp and sp.matched else 0
    np_hits = np.op_count if np and np.matched else 0

    sections: List[str] = []

    # --- Lead ---
    if surname and surname_hits > 0:
        lead = (
            f"Да, в файле «{label}» есть операции с «{surname}»: "
            f"{sp.op_count} операций; поступления {format_amount_rub(sp.inflow_sum)}, "
            f"списания {format_amount_rub(sp.outflow_sum)}, "
            f"сальдо {format_amount_rub(sp.net_sum)}."
        )
        sections.append(lead)
    elif surname and surname_hits == 0 and np_hits > 0:
        parts_label = " + ".join(investigation.name_patronymic_parts)
        if yes_no:
            lead = (
                f"По фамилии «{surname}» в текстах назначений платежей совпадений нет. "
                f"При этом найдено {np_hits} операций, где в описании встречаются "
                f"«{parts_label}» (имя и отчество из вашего вопроса). "
                "Это может быть тот же человек, но выписка не содержит фамилии — "
                "однозначно отождествлять с «{surname}» нельзя."
            )
        else:
            lead = (
                f"Фамилия «{surname}» в назначениях не найдена; "
                f"по имени и отчеству ({parts_label}) — {np_hits} операций "
                f"(поступления {format_amount_rub(np.inflow_sum)}, "
                f"списания {format_amount_rub(np.outflow_sum)})."
            )
        sections.append(lead)
    elif surname and surname_hits == 0 and np_hits == 0:
        if yes_no:
            sections.append(
                f"Нет, в файле «{label}» не найдено операций ни с «{surname}», "
                "ни по имени и отчеству из формулировки вопроса."
            )
        else:
            sections.append(
                f"По файлу «{label}» операций с «{surname}» (и по связанным "
                "фрагментам ФИО) не найдено."
            )
    elif investigation.org_needle and sp and sp.matched:
        sections.append(
            f"По контрагенту «{investigation.org_needle}»: {sp.op_count} операций; "
            f"оборот {format_amount_rub(sp.inflow_sum + sp.outflow_sum)}."
        )
    elif investigation.org_needle:
        op = compute_counterparty_profile(session.rows or [], investigation.org_needle)
        if op.matched:
            sections.append(
                f"По «{investigation.org_needle}»: {op.op_count} операций; "
                f"поступления {format_amount_rub(op.inflow_sum)}, "
                f"списания {format_amount_rub(op.outflow_sum)}."
            )
        else:
            sections.append(
                f"По файлу «{label}» операций с «{investigation.org_needle}» не найдено."
            )
    else:
        sections.append(
            f"Не удалось сопоставить контрагента из вопроса с текстами операций. "
            "Уточните фамилию или фрагмент назначения, как в выписке."
        )

    # --- Facts ---
    facts: List[str] = []
    if surname:
        facts.append(f"Поиск по фамилии/якорю «{surname}»: {surname_hits} операций.")
    if investigation.name_patronymic_parts:
        facts.append(
            f"Дополнительный поиск ({' + '.join(investigation.name_patronymic_parts)}): "
            f"{np_hits} операций."
        )
    if facts:
        sections.append("**Факты:**\n" + "\n".join(f"• {f}" for f in facts))

    cite_rows: List[CaseFileTransaction] = []
    if surname_hits > 0 and sp:
        cite_rows = list(sp.rows)
    elif np_hits > 0 and np:
        cite_rows = list(np.rows)

    examples = _format_examples(
        sorted(
            cite_rows,
            key=lambda r: abs(float(r.amount_rub or 0)),
            reverse=True,
        )
    )
    if examples:
        sections.append("**Примеры строк:**\n" + "\n".join(examples))

    if surname and surname_hits == 0 and np_hits > 0:
        sections.append(
            "**Что проверить:** запросите у клиента полное ФИО и реквизиты "
            "(карта/счёт) контрагента; сопоставьте с инициалами «А.» в выписке."
        )

    return f"{scope}" + "\n\n".join(sections).strip()


def counterparty_lookup_patch(
    db: Session,
    *,
    case_id: str,
    question: str,
    file_id: str,
    file_label: str,
    rows: Sequence[CaseFileTransaction],
    scope_note: str = "",
) -> Optional[dict]:
    session = StatementTableSession(
        case_id=case_id,
        file_id=file_id,
        file_label=file_label,
        question=question,
        db=db,
        rows=list(rows),
        scope_note=scope_note,
    )
    session.tool_calls.extend(["resolve_entity", "counterparty_dossier", "transactions_query"])

    investigation = investigate_counterparty(question, rows)
    answer = compose_counterparty_lawyer_answer(
        session=session,
        question=question,
        investigation=investigation,
    )

    cite_rows: List[CaseFileTransaction] = []
    if investigation.surname_profile and investigation.surname_profile.matched:
        cite_rows = list(investigation.surname_profile.rows)
    elif (
        investigation.name_patronymic_profile
        and investigation.name_patronymic_profile.matched
    ):
        cite_rows = list(investigation.name_patronymic_profile.rows)
    if cite_rows:
        session.add_citation_rows(cite_rows[:20])

    row_count = len(cite_rows)
    logger.info(
        "[CounterpartyPipeline] file=%s surname=%r surname_ops=%s np_ops=%s",
        file_id,
        investigation.surname_label,
        investigation.surname_profile.op_count
        if investigation.surname_profile
        else 0,
        investigation.name_patronymic_profile.op_count
        if investigation.name_patronymic_profile
        else 0,
    )

    return _repair_patch(
        db,
        session,
        answer=answer,
        operation="counterparty_lookup",
        row_count=row_count,
        resolver="operations_counterparty_pipeline",
    )
