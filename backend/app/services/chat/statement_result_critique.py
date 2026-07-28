"""Critique tool/SQL results before answering the lawyer."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.services.chat.statement_entity_grounding import (
    _is_patronymic_anchor,
    _person_surname_anchors,
    stem_probe_variants,
)
from app.services.chat.statement_table_session import StatementTableSession
from app.services.chat.statement_table_turn_contract import classify_statement_turn_intent
from app.services.transaction_description_match import description_token_match

# Tokens too short / generic for person lookup when a longer anchor exists in the question.
_MIN_ENTITY_TOKEN_LEN = 6
_BROAD_HIT_THRESHOLD = 40


@dataclass(frozen=True)
class StatementCritiqueResult:
    ok: bool
    status: str
    issues: List[str] = field(default_factory=list)
    revise_hint: str = ""


def _surname_anchors(question: str) -> List[str]:
    return _person_surname_anchors(question)


def _token_in_anchor(token: str, anchor: str) -> bool:
    t = (token or "").lower()
    a = (anchor or "").lower()
    if not t or not a:
        return False
    return a in t or t in a or description_token_match(a, t)


def _parse_tool_payload(text: str) -> Optional[dict]:
    try:
        data = json.loads(text or "")
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _last_entity_token_from_log(execution_log: Sequence[str]) -> Optional[str]:
    for block in reversed(list(execution_log)):
        data = _parse_tool_payload(block)
        if not data:
            continue
        for key in ("grounded_token", "token"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _sample_descriptions_from_log(execution_log: Sequence[str], limit: int = 5) -> List[str]:
    out: List[str] = []
    for block in execution_log:
        data = _parse_tool_payload(block)
        if not data:
            continue
        for key in ("examples", "operations", "rows"):
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, str):
                    text = item
                elif isinstance(item, dict):
                    text = str(item.get("description") or item.get("summary") or "")
                else:
                    continue
                text = text.strip()
                if text and text not in out:
                    out.append(text[:200])
                if len(out) >= limit:
                    return out
    return out


def critique_statement_execution(
    *,
    question: str,
    session: StatementTableSession,
    execution_log: Sequence[str],
    plan_success_criteria: str = "",
) -> StatementCritiqueResult:
    """Deterministic quality gate: does evidence answer the lawyer's question?"""
    intent = classify_statement_turn_intent(question)
    issues: List[str] = []

    if not session.tool_calls:
        return StatementCritiqueResult(
            ok=False,
            status="no_tools",
            issues=["Не вызван ни один инструмент по данным выписки."],
            revise_hint="Составь план и выполни tools по цепочке из workflows.",
        )

    if intent == "counterparty_lookup":
        anchors = _surname_anchors(question)
        token = _last_entity_token_from_log(execution_log)
        if not token and session.last_plan:
            token = (session.last_plan.description_contains or "").strip()

        if anchors and token:
            match_total: Optional[int] = None
            for block in execution_log:
                data = _parse_tool_payload(block)
                if not data:
                    continue
                raw_count = data.get("match_count")
                if raw_count is None:
                    raw_count = data.get("op_count")
                if raw_count is not None:
                    match_total = int(raw_count)

            primary_anchors = [a for a in anchors if not _is_patronymic_anchor(a)]
            if (
                match_total == 0
                and primary_anchors
                and any(_token_in_anchor(token, a) for a in primary_anchors)
            ):
                return StatementCritiqueResult(ok=True, status="accepted", issues=[])

            if len(token) < _MIN_ENTITY_TOKEN_LEN:
                issues.append(
                    f"Тoken «{token}» слишком короткий для вопроса про конкретное лицо/название."
                )
            if not any(_token_in_anchor(token, a) for a in anchors):
                issues.append(
                    f"Token «{token}» не содержит якорь из вопроса ({', '.join(anchors[:3])})."
                )

            for block in execution_log:
                data = _parse_tool_payload(block)
                if not data:
                    continue
                count = data.get("match_count") or data.get("op_count")
                if count is not None and int(count) >= _BROAD_HIT_THRESHOLD:
                    if len(token) < 8 and not any(
                        _token_in_anchor(token, a) and len(a) >= 7 for a in anchors
                    ):
                        issues.append(
                            f"Слишком широкая выборка ({count} op.) по token «{token}» — "
                            "вероятно не тот человек."
                        )
                        break

            samples = _sample_descriptions_from_log(execution_log)
            if samples and anchors:
                primary = next((a for a in anchors if not _is_patronymic_anchor(a)), anchors[0])
                if not any(
                    description_token_match(s, primary)
                    or any(description_token_match(s, v) for v in stem_probe_variants(primary.split()[0]))
                    for s in samples
                ):
                    issues.append(
                        f"Примеры строк не содержат «{primary}» — ответ может быть не про того контрагента."
                    )

        elif anchors and not token:
            issues.append("Не выполнен resolve_entity / нет grounded token для контрагента.")

    if intent == "factual_aggregate" and session.last_plan:
        op = session.last_plan.operation
        if op in {"count", "sum"} and not (session.last_plan.description_contains or "").strip():
            if _surname_anchors(question):
                issues.append("Запрос count/sum по всей выписке, хотя в вопросе указан контрагент.")

    if issues:
        hint = (
            "Пересмотри план: для ФИО — resolve_entity с фамилией из вопроса, "
            "затем counterparty_dossier / transactions_query с этим token; "
            "не используй укороченные префиксы имён. "
            "При сомнении покажи 3–5 example descriptions."
        )
        if plan_success_criteria.strip():
            hint += f" Критерий успеха: {plan_success_criteria.strip()}"
        return StatementCritiqueResult(
            ok=False,
            status="needs_revision",
            issues=issues,
            revise_hint=hint,
        )

    return StatementCritiqueResult(ok=True, status="accepted", issues=[])
