"""
HTTP-layer preparation for in-case assistant chat (before orchestrator).

Runs after the SSE connection is opened so the client can receive early activity events.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.chat import ChatRequest
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.session_context_retrieval import (
    align_budget_profile_with_session,
    session_context_meta_from_package,
)
from app.services.chat.session_context_service import build_session_context_for_turn
from app.services.observability.assistant_pipeline_langfuse_tracing import (
    assistant_step_span,
    turn_context_trace_fields,
)
import logging

logger = logging.getLogger(__name__)


@dataclass
class CaseChatPrepParams:
    case_id: str
    question: str
    current_user: User
    session_id: Optional[str] = None
    trace_id: str = ""
    preview_mode: str = ""
    draft_mode: bool = False
    legal_research: bool = False
    court_practice: bool = False
    deep_think: bool = False
    web_search: bool = False
    document_context: Optional[str] = None
    document_id: Optional[str] = None
    selected_text: Optional[str] = None
    template_file_id: Optional[str] = None
    template_file_content: Optional[str] = None
    template_system_id: Optional[str] = None
    attached_file_ids: Optional[List[str]] = None
    editor_mode_hint: Optional[str] = None
    draft_action: Optional[str] = None
    corpus_size_hint: int = 0


@dataclass
class CaseChatPrepResult:
    chat_request: ChatRequest
    turn_context_dict: Optional[Dict[str, Any]] = None


def prepare_case_chat_request(db: Session, params: CaseChatPrepParams) -> CaseChatPrepResult:
    """Classify task, build budget profile and ChatRequest (sync, may call LLM)."""
    case_id = params.case_id
    question = params.question
    session_id = params.session_id
    attached_file_ids = params.attached_file_ids
    legal_research = params.legal_research
    draft_mode = params.draft_mode
    deep_think = params.deep_think
    corpus_size_hint = params.corpus_size_hint

    case_doc_count = 0
    task_type = ""
    depth_tier = ""
    clarification_needed = False
    task_reason = ""
    task_conf = 0.0
    task_family = ""
    structured_tier = None
    budget_profile: Dict[str, Any] = {}
    turn_context_dict: Optional[Dict[str, Any]] = None
    dialog_history = ""
    conversation_summary = ""
    anchor_filenames: list = []
    anchor_file_ids: list = []
    routing_question = question

    with assistant_step_span(
        "case",
        "http.request_prep",
        input_payload={
            "question_chars": len(question),
            "case_id": case_id,
            "session_id": session_id or "",
        },
    ) as prep_out:
        with assistant_step_span("case", "http.case_doc_count") as doc_out:
            try:
                from app.services.chat.case_doc_count_cache import resolve_case_doc_count

                case_doc_count = resolve_case_doc_count(
                    db,
                    str(case_id),
                    hint=corpus_size_hint or None,
                )
                doc_out["case_doc_count_source"] = (
                    "client_hint" if corpus_size_hint > 0 else "cache_or_db"
                )
            except Exception as case_meta_err:
                logger.debug("case doc count probe failed: %s", case_meta_err)
            doc_out["case_doc_count"] = case_doc_count

        with assistant_step_span(
            "case",
            "http.infer_task_and_depth",
            input_payload={"question_chars": len(question)},
        ) as inf_out:
            if session_id:
                try:
                    from app.services.chat.history_service import ChatHistoryService
                    from langchain_core.messages import AIMessage, HumanMessage

                    hist_svc = ChatHistoryService(db)
                    recent = hist_svc.get_session_history(
                        case_id=str(case_id),
                        session_id=str(session_id),
                        limit=16,
                    )
                    lc_msgs = []
                    for msg in recent or []:
                        if msg.role == "user" and msg.content:
                            lc_msgs.append(HumanMessage(content=str(msg.content)))
                        elif msg.role == "assistant" and msg.content:
                            lc_msgs.append(AIMessage(content=str(msg.content)))
                    from app.services.chat.session_context_retrieval import (
                        format_dialog_history_for_memory,
                    )

                    dialog_history = format_dialog_history_for_memory(
                        lc_msgs,
                        max_turns=8,
                        max_chars=4000,
                    )
                    for msg in reversed(recent or []):
                        ev = getattr(msg, "evidence", None) or {}
                        if isinstance(ev, dict):
                            for c in ev.get("citations") or []:
                                if isinstance(c, dict):
                                    fn = c.get("filename") or c.get("file_name")
                                    if fn and fn not in anchor_filenames:
                                        anchor_filenames.append(str(fn))
                                    fid = c.get("source_id") or c.get("file_id")
                                    if fid and str(fid) not in anchor_file_ids:
                                        anchor_file_ids.append(str(fid))
                        refs = getattr(msg, "source_references", None) or []
                        if isinstance(refs, list):
                            for ref in refs:
                                if ref and str(ref) not in anchor_filenames:
                                    anchor_filenames.append(str(ref))

                    from app.services.chat.session_transcript import load_case_session_turns
                    from app.services.chat.turn_context_resolution import (
                        load_and_resolve_turn_context,
                    )

                    case_turns = load_case_session_turns(
                        db, case_id=str(case_id), session_id=str(session_id)
                    )
                    if case_turns and (case_turns[-1].role or "").lower() == "user":
                        if (case_turns[-1].content or "").strip() == question.strip():
                            case_turns = case_turns[:-1]
                    with assistant_step_span(
                        "case",
                        "http.turn_context_resolution",
                        input_payload={"question_chars": len(question)},
                    ) as tc_out:
                        turn_resolution = load_and_resolve_turn_context(
                            question=question,
                            turns=case_turns,
                            dialog_history=dialog_history,
                            conversation_summary=conversation_summary,
                            anchor_filenames=anchor_filenames,
                        )
                        turn_context_dict = turn_resolution.to_dict()
                        tc_out.update(turn_context_trace_fields(turn_context_dict))
                        tc_out["standalone_query_chars"] = len(
                            turn_resolution.standalone_query or ""
                        )
                    if turn_resolution.standalone_query:
                        routing_question = turn_resolution.standalone_query
                except Exception as hist_err:
                    logger.debug("standalone query history load skipped: %s", hist_err)

            task_type, depth_tier, clarification_needed, task_reason, task_conf = (
                ConversationPolicyService.infer_task_and_depth(
                    question=routing_question,
                    draft_mode=bool(draft_mode),
                    legal_research=bool(legal_research),
                    deep_think=bool(deep_think),
                    attached_files_count=len(attached_file_ids or []),
                    corpus_size=case_doc_count,
                    dialog_history=dialog_history,
                    conversation_summary=conversation_summary,
                    anchor_filenames=anchor_filenames,
                )
            )
            task_family = ConversationPolicyService.map_task_family(task_type)
            inf_out["task_type"] = task_type
            inf_out["depth_tier"] = depth_tier
            inf_out["clarification_needed"] = clarification_needed

        with assistant_step_span("case", "http.tier_classifier_llm") as tier_out:
            try:
                from app.services.chat.tier_classifier import classify_execution_tier_llm

                structured_tier = classify_execution_tier_llm(
                    question=question,
                    task_type=task_type,
                    depth_tier=depth_tier,
                    clarification_needed=clarification_needed,
                    legal_research=bool(legal_research),
                    deep_think=bool(deep_think),
                    draft_mode=bool(draft_mode),
                    corpus_size=max(case_doc_count, len(attached_file_ids or [])),
                    attached_files_count=len(attached_file_ids or []),
                )
                tier_out["execution_tier"] = structured_tier
            except Exception as tier_cls_err:
                logger.debug("tier LLM classifier skipped: %s", tier_cls_err)
                tier_out["skipped"] = True

        with assistant_step_span("case", "http.budget_profile") as budget_out:
            budget_profile = ConversationPolicyService.budget_profile_for_depth(
                depth_tier,
                task_type,
                corpus_size=max(case_doc_count, len(attached_file_ids or [])),
                question=question,
                clarification_needed=clarification_needed,
                legal_research=bool(legal_research),
                court_practice=bool(params.court_practice),
                deep_think=bool(deep_think),
                draft_mode=bool(draft_mode),
                structured_execution_tier=structured_tier,
                attached_files_count=len(attached_file_ids or []),
                dialog_history=dialog_history,
                conversation_summary=conversation_summary,
                anchor_filenames=anchor_filenames,
                turn_context=turn_context_dict,
            )
            budget_profile["anchor_file_ids"] = list(anchor_file_ids)
            budget_profile["anchor_filenames"] = list(anchor_filenames)
            if turn_context_dict:
                budget_out["referential_kind"] = turn_context_dict.get("referential_kind")
            budget_out["profile_name"] = str(budget_profile.get("name") or "")
            budget_out["execution_tier"] = budget_profile.get("execution_tier")
            prep_out["task_type"] = task_type
            prep_out["depth_tier"] = depth_tier
            prep_out["execution_tier"] = budget_profile.get("execution_tier")
            if turn_context_dict:
                prep_out["referential_kind"] = turn_context_dict.get("referential_kind")

    session_context_prompt: Optional[str] = None
    session_context_meta: Optional[Dict[str, Any]] = None
    if session_id:
        with assistant_step_span(
            "case",
            "http.session_context.build",
            input_payload={"question_chars": len(question)},
        ) as sc_out:
            try:
                session_pkg = build_session_context_for_turn(
                    db,
                    scope="case",
                    question=question,
                    session_id=str(session_id),
                    case_id=str(case_id),
                    task_type=task_type,
                    corpus_size=max(case_doc_count, len(attached_file_ids or [])),
                    draft_mode=bool(draft_mode),
                    turn_context=turn_context_dict,
                )
                session_context_prompt = (session_pkg.prompt_block or "").strip() or None
                session_context_meta = session_context_meta_from_package(
                    session_pkg,
                    turn_context=turn_context_dict,
                )
                budget_profile = align_budget_profile_with_session(
                    budget_profile, session_pkg
                )
                sc_out["prompt_chars"] = len(session_context_prompt or "")
                sc_out["turn_relation"] = session_pkg.resolver.turn_relation.value
                sc_out["needs_document_retrieval"] = bool(
                    session_pkg.resolver.needs_document_retrieval
                )
                sc_out["has_evidence_replay"] = session_pkg.evidence_replay is not None
                sc_out["execution_tier"] = budget_profile.get("execution_tier")
            except Exception as sc_err:
                logger.warning("case session context assembly failed: %s", sc_err)
                session_context_prompt = None
                session_context_meta = None

    state_contract = ConversationPolicyService.build_case_state_contract(
        case_id=case_id,
        session_id=session_id,
        trace_id=params.trace_id,
        question=question,
        attached_file_ids=attached_file_ids,
        legal_research=legal_research,
        draft_mode=draft_mode,
        task_type=task_type,
        route_confidence=float(task_conf),
        route_reason=task_reason,
    )
    state_contract.depth_tier = depth_tier
    state_contract.budget_profile = budget_profile
    state_contract.task_family = task_family

    chat_request = ChatRequest(
        case_id=case_id,
        question=question,
        current_user=params.current_user,
        web_search=params.web_search,
        legal_research=legal_research,
        court_practice=params.court_practice,
        deep_think=deep_think,
        draft_mode=draft_mode,
        document_context=params.document_context,
        document_id=params.document_id,
        selected_text=params.selected_text,
        template_file_id=params.template_file_id,
        template_file_content=params.template_file_content,
        template_system_id=params.template_system_id,
        attached_file_ids=attached_file_ids,
        editor_mode_hint=params.editor_mode_hint,
        session_id=session_id,
        trace_id=params.trace_id,
        mode=params.preview_mode,
        task_type=state_contract.task_type,
        task_family=state_contract.task_family,
        depth_tier=state_contract.depth_tier,
        route_confidence=state_contract.route_confidence,
        route_reason=state_contract.route_reason,
        clarification_needed=clarification_needed,
        budget_profile=state_contract.budget_profile,
        corpus_size=max(case_doc_count, len(attached_file_ids or [])),
        retrieval_task=None,
        scoped_file_ids=None,
        scoped_doc_type=None,
        semantic_intent="",
        retrieval_probe_hits=0,
        retrieval_probe_covered=False,
        draft_action=params.draft_action,
        session_context_prompt=session_context_prompt,
        session_context_meta=session_context_meta,
    )
    return CaseChatPrepResult(chat_request=chat_request, turn_context_dict=turn_context_dict)
