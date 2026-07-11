#!/usr/bin/env python3
"""
Проверка сценариев: фильтры таблицы → вопрос → уточнение → снятие фильтров → новый вопрос.

Запуск из backend/:
  python3 scripts/repro_operations_chat_filter_scenarios.py
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.case import Base, Case
from app.models.case_file_transaction import CaseFileTransaction
from app.models.user import User
from app.schemas.operations import OperationsSessionUiState
from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.turn_context_evidence import PriorTurnEvidence
from app.services.chat.turn_execution_contract import resolve_turn_execution_contract
from app.services.operations_chat_scope import filter_operations_scope
from app.services.operations_chat_service import OperationsChatService

FILE_ID = "stmt-test"
CASE_ID = "case-test"
USER_ID = "user-test"

AMOUNT_UI_FILTER = {
    "columnId": "op_amount",
    "operator": "number_greater_than",
    "numberFrom": 10000,
}


def _seed_rows() -> List[CaseFileTransaction]:
    """15 операций: 10 >10k, 5 ровно 10k, остальные мелкие — всего 335 не нужно, хватит модели."""
    specs = [
        ("r01", Decimal("50000")),
        ("r02", Decimal("25000")),
        ("r03", Decimal("15000")),
        ("r04", Decimal("12000")),
        ("r05", Decimal("11000")),
        ("r06", Decimal("10001")),
        ("r07", Decimal("20000")),
        ("r08", Decimal("30000")),
        ("r09", Decimal("40000")),
        ("r10", Decimal("50000")),
        ("r11", Decimal("10000")),
        ("r12", Decimal("10000")),
        ("r13", Decimal("10000")),
        ("r14", Decimal("10000")),
        ("r15", Decimal("10000")),
        ("r16", Decimal("500")),
        ("r17", Decimal("1000")),
    ]
    rows: List[CaseFileTransaction] = []
    for idx, (rid, amount) in enumerate(specs):
        rows.append(
            CaseFileTransaction(
                id=rid,
                case_id=CASE_ID,
                file_id=FILE_ID,
                global_row_index=idx,
                table_index=0,
                row_index=idx,
                operation_datetime_text=f"01.05.2026 10:{idx:02d}",
                amount_rub=amount,
                amount_raw=str(amount),
                description=f"операция {idx}",
                row_columns={"Сумма": str(amount)},
            )
        )
    return rows


@dataclass
class ScenarioResult:
    name: str
    ui_filters: int
    row_search: str
    question: str
    scope_total: int
    scope_filtered: int
    path: str
    sql_pipeline_called: bool
    in_memory_rows_used: Optional[int]
    turn_hints: Dict[str, str]
    scope_note: str
    ok: Optional[bool] = None
    note: str = ""


def _scope(
    rows: List[CaseFileTransaction],
    *,
    value_filters: List[dict],
    row_search: str = "",
):
    return filter_operations_scope(
        rows=rows,
        file_id=FILE_ID,
        file_label="test.pdf",
        row_search=row_search,
        value_filters=value_filters,
    )


def _prior_evidence_gt_10k() -> PriorTurnEvidence:
    state = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id=FILE_ID,
        operation="list",
        amount_compare="gt",
        amount_min="10000",
        structured_data_plane="sql",
        topic_file_ids=(FILE_ID,),
    )
    return PriorTurnEvidence(
        message_id="msg-prior",
        assistant_excerpt="Найдено 10 операций больше 10 000 ₽.",
        citations=(),
        retrieval_metadata={"turn_state": state.to_dict()},
    )


async def _run_chat_turn(
    rows: List[CaseFileTransaction],
    *,
    question: str,
    value_filters: List[dict],
    row_search: str = "",
    prior_evidence: Optional[PriorTurnEvidence] = None,
) -> ScenarioResult:
    scope = _scope(rows, value_filters=value_filters, row_search=row_search)
    sql_called = False
    in_memory_count: Optional[int] = None
    path = "unknown"

    captured_pipeline: Dict[str, Any] = {}
    captured_execution_rows: List[Any] = []

    def _fake_pipeline(db, **kwargs):
        nonlocal sql_called, path
        sql_called = True
        path = "sql_pipeline_full_db"
        captured_pipeline.update(kwargs)
        return {
            "response": f"[SQL] ответ по полной выписке, вопрос: {kwargs.get('question', '')}",
            "citations": [],
            "outbound_turn_state": {},
        }

    def _fake_plan(db, **kwargs):
        from app.services.chat.statement_sql_models import StatementSqlPlan, StatementSqlPlanResult

        plan = StatementSqlPlan(
            operation="list",
            statement_file_id=FILE_ID,
            amount_compare="gt",
            amount_min="10000",
            confidence=0.9,
        )
        return StatementSqlPlanResult(plan=plan, resolver="test", reason="test")

    def _fake_execute_on_rows(**kwargs):
        nonlocal in_memory_count, path
        path = "in_memory_filtered_scope"
        rows_in = kwargs.get("rows") or []
        in_memory_count = len(rows_in)
        captured_execution_rows.extend(rows_in)
        from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
        from app.services.chat.statement_sql_facts import StatementSqlFacts

        facts = StatementSqlFacts(
            operation="list",
            file_label="test.pdf",
            file_id=FILE_ID,
            period_label="вся выписка",
            row_count=len(rows_in),
            amount_sum=sum((r.amount_rub or Decimal(0) for r in rows_in), Decimal(0)),
            sample_rows=[],
            scope_note=kwargs.get("scope_note") or "",
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=list(rows_in))

    def _fake_synthesize(**kwargs):
        from app.services.chat.statement_sql_synthesizer import StatementSqlSynthesisResult

        facts = kwargs["execution"].facts
        return StatementSqlSynthesisResult(
            text=f"[in-memory] операций в scope: {facts.row_count}. {facts.scope_note}",
            via_llm=False,
        )

    service = OperationsChatService(SimpleNamespace())
    service._get_case_for_user = lambda case_id, user_id: SimpleNamespace(id=case_id)  # type: ignore[method-assign]
    service._load_scope = lambda **_: scope  # type: ignore[method-assign]
    service._load_prior_turn_evidence = lambda **_: prior_evidence  # type: ignore[method-assign]
    service._load_conversation_history = lambda **_: [  # type: ignore[method-assign]
        {"role": "user", "content": "операции больше 10к"},
        {"role": "assistant", "content": "Найдено 10 операций больше 10 000 ₽."},
    ]
    service._persist_turn = lambda *a, **k: None  # type: ignore[method-assign]

    with (
        patch("app.services.operations_chat_service.run_statement_sql_pipeline", side_effect=_fake_pipeline),
        patch("app.services.operations_chat_service.plan_statement_sql", side_effect=_fake_plan),
        patch("app.services.operations_chat_service.execute_statement_sql_plan_on_rows", side_effect=_fake_execute_on_rows),
        patch("app.services.operations_chat_service.synthesize_statement_sql_answer", side_effect=_fake_synthesize),
        patch("app.services.operations_chat_service.build_transaction_citations", return_value=[]),
    ):
        events = []
        ui = OperationsSessionUiState(value_filters=value_filters, row_search=row_search)
        async for ev in service.stream_analyze(CASE_ID, USER_ID, question, FILE_ID, ui):
            events.append(ev)

    done = next((e for e in events if e.get("type") == "done"), {})
    answer = str(done.get("answer") or "")

    contract = resolve_turn_execution_contract(
        question=question,
        turn_context=None,
        prior_evidence=prior_evidence,
    )

    return ScenarioResult(
        name="",
        ui_filters=len([f for f in value_filters if f]),
        row_search=row_search,
        question=question,
        scope_total=scope.total_rows,
        scope_filtered=len(scope.filtered_rows),
        path=path,
        sql_pipeline_called=sql_called,
        in_memory_rows_used=in_memory_count,
        turn_hints=dict(contract.sql_plan_hints),
        scope_note=scope.scope_note(),
        note=answer[:120],
    )


def _check_turn_resolver(rows: List[CaseFileTransaction]) -> List[ScenarioResult]:
    out: List[ScenarioResult] = []
    prior = _prior_evidence_gt_10k()
    cases = [
        ("Уточнение «что за операции?» после >10к", "что за операции?"),
        ("Уточнение «подробнее»", "подробнее"),
        ("Новый вопрос «сколько всего операций»", "сколько всего операций в выписке"),
        ("Явно по всей выписке >10к", "по всей выписке найди операции больше 10к"),
    ]
    for title, q in cases:
        contract = resolve_turn_execution_contract(
            question=q,
            turn_context=None,
            prior_evidence=prior,
        )
        scope_full = _scope(rows, value_filters=[], row_search="")
        out.append(
            ScenarioResult(
                name=title,
                ui_filters=0,
                row_search="",
                question=q,
                scope_total=scope_full.total_rows,
                scope_filtered=len(scope_full.filtered_rows),
                path="turn_resolver_only",
                sql_pipeline_called=False,
                in_memory_rows_used=None,
                turn_hints=dict(contract.sql_plan_hints),
                scope_note="",
                note=f"resolver={contract.resolver}, effective={contract.effective_query[:80]}",
            )
        )
    return out


async def main() -> int:
    rows = _seed_rows()
    gt10_ui = [AMOUNT_UI_FILTER]

    scenarios: List[ScenarioResult] = []

    s1 = await _run_chat_turn(
        rows,
        question="сколько операций больше 10 тысяч?",
        value_filters=gt10_ui,
    )
    s1.name = "1. Фильтр в таблице → вопрос про >10к"
    s1.ok = s1.path == "in_memory_filtered_scope" and s1.in_memory_rows_used == 10
    s1.note = f"path={s1.path}, rows_in_scope={s1.in_memory_rows_used}, ожидали 10"
    scenarios.append(s1)

    s2 = await _run_chat_turn(
        rows,
        question="что за операции?",
        value_filters=gt10_ui,
        prior_evidence=_prior_evidence_gt_10k(),
    )
    s2.name = "2. Фильтр в таблице → уточнение «что за операции?»"
    s2.ok = s2.path == "in_memory_filtered_scope" and s2.in_memory_rows_used == 10
    s2.note = f"path={s2.path}, rows={s2.in_memory_rows_used}, hints={s2.turn_hints}"
    scenarios.append(s2)

    s3 = await _run_chat_turn(
        rows,
        question="сколько всего операций в выписке?",
        value_filters=[],
    )
    s3.name = "3. Фильтры сняты → новый вопрос «сколько всего»"
    s3.ok = s3.path == "sql_pipeline_full_db" and s3.sql_pipeline_called
    s3.note = f"path={s3.path}, sql_called={s3.sql_pipeline_called}"
    scenarios.append(s3)

    s4 = await _run_chat_turn(
        rows,
        question="что за операции?",
        value_filters=[],
        prior_evidence=_prior_evidence_gt_10k(),
    )
    s4.name = "4. Фильтры сняты → уточнение «что за операции?» (после >10к)"
    s4.ok = s4.path == "sql_pipeline_full_db"
    inherited = s4.turn_hints.get("amount_compare") == "gt" and s4.turn_hints.get("amount_min") == "10000"
    s4.note = f"path={s4.path}, наследует >10к в hints={inherited}, hints={s4.turn_hints}"
    scenarios.append(s4)

    s5 = await _run_chat_turn(
        rows,
        question="покажи все операции",
        value_filters=[],
        row_search="операция 1",
    )
    s5.name = "5. Фильтры сняты, но поиск в строке «операция 1»"
    s5.ok = s5.path == "in_memory_filtered_scope" and (s5.in_memory_rows_used or 0) < len(rows)
    s5.note = f"path={s5.path}, rows={s5.in_memory_rows_used}, scope_filtered={s5.scope_filtered}"
    scenarios.append(s5)

    s6 = await _run_chat_turn(
        rows,
        question="по всей выписке сколько операций?",
        value_filters=[],
        prior_evidence=_prior_evidence_gt_10k(),
    )
    s6.name = "6. Фильтры сняты → явно «по всей выписке»"
    s6.ok = s6.path == "sql_pipeline_full_db"
    clears = "amount_compare" not in s6.turn_hints or s6.turn_hints.get("amount_compare") != "gt"
    s6.note = f"path={s6.path}, сброс amount в hints={clears}, hints={s6.turn_hints}"
    scenarios.append(s6)

    scenarios.extend(_check_turn_resolver(rows))

    print("=" * 72)
    print("ПРОВЕРКА СЦЕНАРИЕВ: фильтры таблицы и контекст чата")
    print(f"Тестовых операций: {len(rows)} (из них >10к: 10, ровно 10к: 5)")
    print("=" * 72)

    issues: List[str] = []
    for s in scenarios:
        status = "OK" if s.ok else ("ВНИМАНИЕ" if s.ok is False else "—")
        print(f"\n[{status}] {s.name}")
        print(f"  Вопрос: {s.question}")
        print(f"  UI-фильтры: {s.ui_filters}, поиск: «{s.row_search}»")
        print(f"  Таблица для чата: {s.scope_filtered} из {s.scope_total} строк")
        print(f"  Путь ответа: {s.path}")
        if s.sql_pipeline_called:
            print("  → SQL по всей выписке в БД")
        if s.in_memory_rows_used is not None:
            print(f"  → In-memory по отфильтрованной таблице: {s.in_memory_rows_used} строк")
        if s.turn_hints:
            print(f"  Наследуемые SQL-hints: {s.turn_hints}")
        print(f"  {s.note}")

        if s.ok is False:
            issues.append(s.name)

    print("\n" + "=" * 72)
    print("ИТОГ ПРОСТЫМ ЯЗЫКОМ")
    print("=" * 72)
    print(
        """
1. Пока в таблице стоят фильтры — чат считает только по отфильтрованным строкам
   (не лезет в полную выписку в БД). Это ожидаемо.

2. Сняли фильтры и задали НОВЫЙ вопрос («сколько всего операций») —
   чат переключается на полную выписку через SQL. Это работает.

3. Сняли фильтры, но спрашиваете УТОЧНЕНИЕ («что за операции?», «подробнее»)
   после прошлого ответа про >10к — чат ПО-ПРЕЖНЕМУ помнит условие >10к
   из диалога, даже если таблица уже показывает все строки.
   Это главная причина расхождений «на экране 335, в ответе 10».

4. Если сняли фильтры колонок, но в строке поиска что-то осталось —
   чат всё ещё видит урезанную таблицу (как будто фильтр не снят).

5. Фраза «по всей выписке» в вопросе помогает сбросить период,
   но наследование суммы (>10к) из прошлого turn может остаться —
   зависит от формулировки и resolver.
""".strip()
    )

    if issues:
        print(f"\nСценарии с неожиданным поведением: {', '.join(issues)}")
    else:
        print("\nВсе проверенные сценарии вели себя предсказуемо.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
