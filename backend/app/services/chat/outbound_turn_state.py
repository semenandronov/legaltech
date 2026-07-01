"""
Build outbound ConversationTurnState from graph state after any execution path.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    turn_state_from_rag_scope,
    turn_state_from_sql_plan,
)


def _unique_file_ids(*groups: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for raw in group:
            fid = str(raw or "").strip()
            if fid and fid not in seen:
                seen.add(fid)
                out.append(fid)
    return tuple(out)


def _file_ids_from_citations(citations: object) -> tuple[str, ...]:
    if not isinstance(citations, list):
        return ()
    ids: list[str] = []
    seen: set[str] = set()
    for cit in citations:
        if not isinstance(cit, dict):
            continue
        fid = str(cit.get("source_id") or cit.get("file_id") or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            ids.append(fid)
    return tuple(ids)


def collect_turn_scope_file_ids(state: Mapping[str, Any]) -> tuple[str, ...]:
    bp = state.get("budget_profile") if isinstance(state.get("budget_profile"), dict) else {}
    tc = bp.get("turn_context") if isinstance(bp.get("turn_context"), dict) else {}
    inherited = tc.get("inherited_file_ids") if isinstance(tc.get("inherited_file_ids"), list) else []

    rt = state.get("retrieval_task") if isinstance(state.get("retrieval_task"), dict) else {}
    rt_files = rt.get("file_ids") if isinstance(rt.get("file_ids"), list) else []

    return _unique_file_ids(
        state.get("scoped_file_ids") or [],
        state.get("statement_scope_file_ids") or [],
        state.get("hybrid_rag_file_ids") or [],
        inherited,
        rt_files,
        _file_ids_from_citations(state.get("citations")),
    )


def turn_state_from_hybrid_scope(
    *,
    statement_file_ids: Sequence[str],
    rag_file_ids: Sequence[str],
    sql_operation: str = "",
    plane: str = "hybrid",
) -> ConversationTurnState:
    sql_ids = _unique_file_ids(statement_file_ids)
    rag_ids = _unique_file_ids(rag_file_ids)
    topic = _unique_file_ids(sql_ids, rag_ids)
    return ConversationTurnState(
        domain="hybrid",
        statement_file_id=sql_ids[0] if sql_ids else "",
        operation=str(sql_operation or "").strip(),
        structured_data_plane=plane,
        rag_file_ids=rag_ids,
        topic_file_ids=topic,
    )


def build_outbound_turn_state(state: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Derive persisted turn state when the path did not set it explicitly (SQL)."""
    existing = state.get("outbound_turn_state")
    if isinstance(existing, dict) and existing.get("domain") not in (None, "", "none"):
        return dict(existing)

    plane = str(state.get("structured_data_plane") or "").strip().lower()
    scope_ids = collect_turn_scope_file_ids(state)

    meta = state.get("statement_sql_meta")
    sql_resolved = bool(state.get("transaction_agent_resolved"))

    if plane == "rag" and scope_ids:
        return turn_state_from_rag_scope(file_ids=scope_ids, plane="rag").to_dict()

    if isinstance(meta, dict) and meta.get("operation") and (plane == "sql" or sql_resolved):
        file_id = str(meta.get("file_id") or "").strip()
        if not file_id and scope_ids:
            file_id = scope_ids[0]
        from app.services.chat.statement_sql_models import StatementSqlPlan

        plan = StatementSqlPlan(
            operation=str(meta.get("operation") or "count"),
            date_from=str(meta.get("date_from") or ""),
            date_to=str(meta.get("date_to") or ""),
            on_date=str(meta.get("on_date") or ""),
            statement_file_id=file_id,
        )
        return turn_state_from_sql_plan(
            plan=plan,
            file_id=file_id,
            plane=plane or "sql",
        ).to_dict()

    if plane == "hybrid":
        sql_scope = [
            str(x).strip()
            for x in (state.get("statement_scope_file_ids") or [])
            if str(x).strip()
        ]
        rag_scope = [
            str(x).strip()
            for x in (state.get("hybrid_rag_file_ids") or [])
            if str(x).strip()
        ]
        if not rag_scope:
            rag_scope = [fid for fid in scope_ids if fid not in sql_scope]
        if sql_scope or rag_scope:
            op = ""
            if isinstance(meta, dict):
                op = str(meta.get("operation") or "")
            return turn_state_from_hybrid_scope(
                statement_file_ids=sql_scope,
                rag_file_ids=rag_scope or list(scope_ids),
                sql_operation=op,
                plane="hybrid",
            ).to_dict()

    if scope_ids and plane in {"", "rag"}:
        return turn_state_from_rag_scope(file_ids=scope_ids, plane="rag").to_dict()

    if scope_ids and not plane:
        return turn_state_from_rag_scope(file_ids=scope_ids, plane="rag").to_dict()

    return None


def attach_outbound_turn_state(state: Dict[str, Any]) -> Dict[str, Any]:
    built = build_outbound_turn_state(state)
    if built:
        state["outbound_turn_state"] = built
    return state
