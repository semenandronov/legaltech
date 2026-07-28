"""
Statement reasoning agent — plan → execute → critique → revise → answer.

LangGraph orchestrates the loop; numbers still come from lawyer toolkit tools.
"""
from __future__ import annotations

import json
import logging
import operator
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_lawyer_tool_registry import LAWYER_TOOL_WORKFLOWS
from app.services.chat.statement_lawyer_toolkit import (
    counterparty_dossier,
    evidence_bundle,
    flow_profile,
    legal_calendar,
    resolve_entity,
    risk_scan,
    statement_context,
    transactions_query,
)
from app.services.chat.statement_result_critique import critique_statement_execution
from app.services.chat.statement_reasoning_progress import StatementReasoningProgress
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)
from app.services.chat.statement_table_turn_contract import classify_statement_turn_intent
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

ConversationHistory = Sequence[Dict[str, Any]]

_TOOL_REGISTRY = {
    "statement_context": statement_context,
    "resolve_entity": resolve_entity,
    "transactions_query": transactions_query,
    "flow_profile": flow_profile,
    "legal_calendar": legal_calendar,
    "risk_scan": risk_scan,
    "counterparty_dossier": counterparty_dossier,
    "evidence_bundle": evidence_bundle,
}


class PlanStep(TypedDict, total=False):
    tool: str
    args: Dict[str, Any]
    purpose: str


class ReasoningPlan(TypedDict, total=False):
    intent_summary: str
    success_criteria: str
    steps: List[PlanStep]


class ReasoningState(TypedDict, total=False):
    question: str
    intent: str
    plan: ReasoningPlan
    execution_log: List[str]
    critique_issues: List[str]
    revise_hint: str
    revision_count: int
    reasoning_trace: Annotated[List[str], operator.add]
    status: str


def reasoning_agent_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_REASONING_AGENT_ENABLED", True))


def _max_revisions() -> int:
    return max(0, min(3, int(getattr(config, "STATEMENT_REASONING_MAX_REVISIONS", 2) or 2)))


def _default_plan_for_intent(question: str) -> ReasoningPlan:
    intent = classify_statement_turn_intent(question)
    q = question.strip()
    if intent == "counterparty_lookup":
        hint = q
        for sep in (" с ", " по ", " про "):
            if sep in q.lower():
                hint = q.split(sep, 1)[-1].strip(" ?.")
                break
        return {
            "intent_summary": "Проверка операций по контрагенту/ФИО",
            "success_criteria": "Token содержит фамилию из вопроса; примеры строк подтверждают личность",
            "steps": [
                {
                    "tool": "resolve_entity",
                    "args": {"hint": hint, "question": q},
                    "purpose": "Найти token в текстах операций",
                },
                {
                    "tool": "counterparty_dossier",
                    "args": {"token": "__GROUNDED__", "list_limit": "10"},
                    "purpose": "Досье и примеры операций",
                },
            ],
        }
    if intent == "open_analytics":
        return {
            "intent_summary": "Обзор и риски по выписке",
            "success_criteria": "Есть картина денег и зоны внимания",
            "steps": [
                {"tool": "statement_context", "args": {}, "purpose": "Контекст"},
                {"tool": "flow_profile", "args": {}, "purpose": "Картина денег"},
                {"tool": "risk_scan", "args": {}, "purpose": "Паттерны риска"},
            ],
        }
    return {
        "intent_summary": "Точный факт по выписке",
        "success_criteria": "Числа из transactions_query отвечают на вопрос",
        "steps": [
            {"tool": "statement_context", "args": {}, "purpose": "Контекст"},
            {
                "tool": "transactions_query",
                "args": {"operation": "count"},
                "purpose": "Факт по таблице (уточни args при revise)",
            },
        ],
    }


def _parse_plan_json(text: str) -> Optional[ReasoningPlan]:
    raw = (text or "").strip()
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    norm_steps: List[PlanStep] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "").strip()
        if tool not in _TOOL_REGISTRY:
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        norm_steps.append(
            {
                "tool": tool,
                "args": args,
                "purpose": str(step.get("purpose") or ""),
            }
        )
    if not norm_steps:
        return None
    return {
        "intent_summary": str(data.get("intent_summary") or ""),
        "success_criteria": str(data.get("success_criteria") or ""),
        "steps": norm_steps,
    }


def _plan_node(state: ReasoningState) -> Dict[str, Any]:
    question = (state.get("question") or "").strip()
    intent = classify_statement_turn_intent(question)
    revise_hint = (state.get("revise_hint") or "").strip()
    revision = int(state.get("revision_count") or 0)

    if revision == 0 and not revise_hint:
        try:
            llm = create_legal_llm(temperature=0.0, max_tokens=1024, use_rate_limiting=False)
            prompt = f"""Ты планируешь анализ банковской выписки для юриста.
Вопрос: {question}
Intent: {intent}

Доступные tools: {", ".join(_TOOL_REGISTRY.keys())}

{LAWYER_TOOL_WORKFLOWS}

Верни ТОЛЬКО JSON:
{{
  "intent_summary": "...",
  "success_criteria": "когда считаем, что данные ответили на вопрос",
  "steps": [{{"tool": "...", "args": {{}}, "purpose": "..."}}]
}}
Не более 5 шагов. Для ФИО/контрагента: resolve_entity → counterparty_dossier.
"""
            resp = llm.invoke([SystemMessage(content="Ты составляешь план, не отвечаешь юристу."), HumanMessage(content=prompt)])
            text = resp.content if hasattr(resp, "content") else str(resp)
            plan = _parse_plan_json(str(text))
            if plan:
                return {
                    "plan": plan,
                    "intent": intent,
                    "reasoning_trace": [f"plan: {plan.get('intent_summary', '')}"],
                }
        except Exception as exc:
            logger.warning("[StatementReasoning] plan LLM failed: %s", exc)

    plan = _default_plan_for_intent(question)
    if revise_hint:
        plan["success_criteria"] = revise_hint[:500]
    return {
        "plan": plan,
        "intent": intent,
        "reasoning_trace": [f"plan(fallback): {plan.get('intent_summary', '')}"],
    }


def _resolve_grounded_token(session: StatementTableSession, execution_log: List[str]) -> str:
    for block in reversed(execution_log):
        try:
            data = json.loads(block)
            tok = data.get("grounded_token")
            if isinstance(tok, str) and tok.strip():
                return tok.strip()
        except json.JSONDecodeError:
            continue
    from app.services.chat.statement_entity_grounding import select_best_entity_token

    rows = list(session.rows) if session.rows is not None else session.load_all_rows()
    return select_best_entity_token(
        session.question,
        rows=rows,
        db=session.db,
        case_id=session.case_id,
        file_id=session.file_id,
    )


def _tool_result_snippet(text: str) -> str:
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        return (text or "").strip()[:120]
    if not isinstance(data, dict):
        return ""
    for key in ("summary", "grounded_token", "token", "match_count", "op_count"):
        val = data.get(key)
        if val is None or val == "":
            continue
        if key in ("match_count", "op_count"):
            return f"{val} оп."
        return str(val).strip()[:120]
    return ""


def _execute_node(
    state: ReasoningState,
    session: StatementTableSession,
    progress: Optional[StatementReasoningProgress] = None,
) -> Dict[str, Any]:
    plan = state.get("plan") or {}
    steps: List[PlanStep] = list(plan.get("steps") or [])
    log: List[str] = []
    trace: List[str] = []

    session.tool_calls.clear()

    for step in steps:
        tool_name = str(step.get("tool") or "")
        tool = _TOOL_REGISTRY.get(tool_name)
        if tool is None:
            continue
        args = dict(step.get("args") or {})
        if args.get("token") == "__GROUNDED__":
            grounded = _resolve_grounded_token(session, list(state.get("execution_log") or []) + log)
            if not grounded:
                log.append(json.dumps({"ok": False, "error": "no_grounded_token"}, ensure_ascii=False))
                trace.append(f"execute: {tool_name} skipped — no grounded token")
                continue
            args["token"] = grounded
        if tool_name == "resolve_entity" and "question" not in args:
            args["question"] = session.question

        purpose = str(step.get("purpose") or "")
        if progress:
            progress.tool_started(tool_name, purpose)

        try:
            result = tool.invoke(args)
            log.append(str(result))
            trace.append(f"execute: {tool_name} ({purpose})")
            if progress:
                progress.tool_done(tool_name, purpose, detail=_tool_result_snippet(str(result)))
        except Exception as exc:
            log.append(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            trace.append(f"execute: {tool_name} error")
            if progress:
                progress.tool_done(tool_name, purpose, detail="ошибка выполнения")

    return {"execution_log": list(state.get("execution_log") or []) + log, "reasoning_trace": trace}


def _critique_node(
    state: ReasoningState,
    session: StatementTableSession,
    progress: Optional[StatementReasoningProgress] = None,
) -> Dict[str, Any]:
    if progress:
        progress.critique_started()
    plan = state.get("plan") or {}
    all_log = list(state.get("execution_log") or [])
    critique = critique_statement_execution(
        question=state.get("question") or session.question,
        session=session,
        execution_log=all_log,
        plan_success_criteria=str(plan.get("success_criteria") or ""),
    )
    trace = [
        f"critique: {critique.status}"
        + (f" — {'; '.join(critique.issues)}" if critique.issues else " ok")
    ]
    detail = "; ".join(critique.issues) if critique.issues else ""
    if progress:
        progress.critique_done(ok=critique.ok, detail=detail)
    if critique.ok:
        return {
            "status": "accepted",
            "critique_issues": [],
            "revise_hint": "",
            "reasoning_trace": trace,
        }
    return {
        "status": "needs_revision",
        "critique_issues": critique.issues,
        "revise_hint": critique.revise_hint,
        "reasoning_trace": trace,
    }


def _route_after_critique(state: ReasoningState) -> Literal["revise", "finish"]:
    if state.get("status") == "accepted":
        return "finish"
    if int(state.get("revision_count") or 0) >= _max_revisions():
        return "finish"
    return "revise"


def _revise_node(
    state: ReasoningState,
    progress: Optional[StatementReasoningProgress] = None,
) -> Dict[str, Any]:
    count = int(state.get("revision_count") or 0) + 1
    hint = (state.get("revise_hint") or "").strip()
    if progress:
        progress.revise(count, hint)
    plan = _default_plan_for_intent(state.get("question") or "")
    if hint:
        plan["success_criteria"] = hint[:800]
    return {
        "revision_count": count,
        "plan": plan,
        "execution_log": [],
        "reasoning_trace": [f"revise #{count}: пересборка плана"],
    }


def _build_reasoning_graph(
    session: StatementTableSession,
    progress: Optional[StatementReasoningProgress] = None,
):
    graph: StateGraph = StateGraph(ReasoningState)

    def plan(state: ReasoningState) -> Dict[str, Any]:
        if progress:
            progress.plan_started()
        out = _plan_node(state)
        if progress:
            plan_obj = out.get("plan") if isinstance(out.get("plan"), dict) else {}
            progress.plan_ready(str(plan_obj.get("intent_summary") or ""))
        return out

    def execute(state: ReasoningState) -> Dict[str, Any]:
        return _execute_node(state, session, progress)

    def critique(state: ReasoningState) -> Dict[str, Any]:
        return _critique_node(state, session, progress)

    def revise(state: ReasoningState) -> Dict[str, Any]:
        return _revise_node(state, progress)

    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("critique", critique)
    graph.add_node("revise", revise)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "critique")
    graph.add_conditional_edges(
        "critique",
        _route_after_critique,
        {"revise": "revise", "finish": END},
    )
    graph.add_edge("revise", "execute")
    return graph.compile()


def run_statement_reasoning_graph(
    session: StatementTableSession,
    *,
    question: str,
    progress: Optional[StatementReasoningProgress] = None,
) -> Dict[str, Any]:
    """Run plan → execute → critique loop; mutates session via tools."""
    app = _build_reasoning_graph(session, progress)
    initial: ReasoningState = {
        "question": question.strip(),
        "execution_log": [],
        "revision_count": 0,
        "reasoning_trace": [],
        "critique_issues": [],
    }
    final = app.invoke(initial)
    return final
