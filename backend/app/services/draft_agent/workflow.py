"""Hybrid draft workflow: deterministic pipeline + bounded gap retrieval."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_agent.coverage import assess_fact_coverage
from app.services.draft_agent.brief_intent import DraftBriefIntent
from app.services.draft_agent.document_completion import (
    build_completion_gap_report,
    build_document_completion_plan,
)
from app.services.draft_agent.instruction import (
    apply_brief_to_facts,
    build_chat_summary,
    build_document_instruction,
    build_verified_amounts_block,
    merge_extracted_facts,
)
from app.services.draft_agent.writer import complete_draft_document_html
from app.services.draft_agent.review import review_draft_html
from app.services.draft_agent.session import DraftAgentSession
from app.services.draft_agent.targeted_retrieval import run_targeted_gap_retrieval
from app.services.draft_agent.tools._emit import emit_tool_completed, emit_tool_started
from app.services.draft_agent.tools.build import TOOL_CALCULATOR, TOOL_WRITE_DOCUMENT
from app.services.draft_agent.writer import persist_draft_document
from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_pipeline.nodes.fact_passport import extract_case_fact_passport
from app.services.draft_pipeline.nodes.verify_financials import run_verify_financials
from app.services.draft_pipeline.schemas import (
    CaseRetrievalSnapshot,
    DocumentExtractionRecord,
    DocumentTriageResult,
    DraftTaskPlan,
    ExtractedFacts,
)
from app.services.draft_pipeline.nodes.task_decomposer import decompose_draft_task
from app.services.draft_pipeline.nodes.document_triage import triage_case_documents
from app.services.draft_pipeline.nodes.retrieve_materials import run_case_materials_retrieval
from app.services.draft_pipeline.nodes.parallel_extract import run_parallel_extraction
from app.services.draft_pipeline.nodes.consolidate_state import consolidate_extractions
from app.services.draft_pipeline.nodes.unified_generator import run_unified_draft_generation
from app.services.draft_agent.document_output import produce_draft_html
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

DraftTemplateMode = Literal["catalog_fill", "template_guide", "scratch"]


def _require_db(db: Optional[Session]) -> Session:
    if db is None:
        raise RuntimeError("draft_agent.workflow: database session is required")
    return db


def _max_coverage_retries() -> int:
    return int(getattr(config, "DRAFT_COVERAGE_MAX_RETRIES", 2) or 2)


class DraftHybridState(TypedDict, total=False):
    case_id: str
    user_id: str
    user_prompt: str
    attached_file_ids: Optional[List[str]]
    template_mode: DraftTemplateMode
    template_html: Optional[str]
    template_label: Optional[str]
    template_key: Optional[str]
    catalog_dict: Optional[Dict[str, Any]]

    task_plan: Dict[str, Any]
    triage: Dict[str, Any]
    case_retrieval: Dict[str, Any]
    extraction_records: List[Dict[str, Any]]
    extracted_facts: Dict[str, Any]

    coverage_gaps: List[Dict[str, Any]]
    coverage_sufficient: bool
    retrieval_retry_count: int

    final_html: str
    document_title: str
    document_created: Optional[Dict[str, Any]]
    response: str
    fill_stats: Dict[str, Any]
    errors: List[str]
    brief_intent: Dict[str, Any]


def _brief_intent_from_state(
    state: DraftHybridState,
    session: DraftAgentSession,
) -> Optional[DraftBriefIntent]:
    raw = state.get("brief_intent")
    if isinstance(raw, dict) and raw:
        return DraftBriefIntent.from_state_dict(raw)
    if session.template.brief_intent:
        return session.template.brief_intent
    return None


def _route_entry(state: DraftHybridState) -> str:
    if state.get("template_mode") == "catalog_fill":
        return "catalog_fill"
    return "decompose_task"


def _route_after_coverage(state: DraftHybridState) -> str:
    if state.get("coverage_sufficient"):
        return "verify_financials"
    retries = int(state.get("retrieval_retry_count") or 0)
    if retries < _max_coverage_retries() and (state.get("coverage_gaps") or []):
        return "targeted_retrieval"
    return "verify_financials"


def create_draft_hybrid_graph(db: Optional[Session], *, session: DraftAgentSession):
    """Compile bounded hybrid workflow for one draft session."""

    def catalog_fill_node(state: DraftHybridState) -> DraftHybridState:
        emit_tool_started(TOOL_WRITE_DOCUMENT, {"mode": "catalog_fill", "title": session.template.template_label or ""})
        catalog = session.template.catalog
        if not catalog:
            return {
                **state,
                "errors": (state.get("errors") or []) + ["catalog_fill: missing catalog"],
                "response": "❌ Шаблон с полями не найден",
            }

        rag = RAGService()
        html, stats = execute_catalog_field_fill(
            rag_service=rag,
            case_id=state["case_id"],
            catalog=catalog,
            db=_require_db(db),
            attached_file_ids=state.get("attached_file_ids"),
            user_context=state["user_prompt"],
            template_label=session.template.template_label or "",
        )
        calc = stats.get("calculator") or {}
        if calc.get("calculator_applied"):
            emit_tool_started(TOOL_CALCULATOR, {"reason": "авторасчёт перед заполнением шаблона"})
            emit_tool_completed(
                TOOL_CALCULATOR,
                success=True,
                output_summary=f"Итог: {calc.get('calculator_total') or '—'}",
            )
        lint = review_draft_html(html)
        if not lint["passed"]:
            msg = "; ".join(lint.get("issues") or [])
            logger.warning("[draft_agent.workflow] catalog_fill review (non-blocking): %s", msg)

        title = (session.template.template_label or "Новый документ")[:255]
        doc = persist_draft_document(
            _require_db(db),
            case_id=state["case_id"],
            user_id=state["user_id"],
            title=title,
            content=html,
        )
        artifact = {
            "type": "document",
            "id": doc["id"],
            "title": doc["title"],
            "path": f"/cases/{state['case_id']}/editor/{doc['id']}",
            "preview": doc.get("preview", "")[:300],
        }
        emit_tool_completed(
            TOOL_WRITE_DOCUMENT,
            success=True,
            output_summary=f"Шаблон заполнен ({stats.get('fields_filled')}/{stats.get('fields_total')} полей)",
            artifact=artifact,
        )
        response = build_chat_summary(
            document_title=doc["title"],
            document_id=doc["id"],
            case_id=state["case_id"],
            fill_mode="catalog_fill",
            fill_stats=stats,
        )
        return {
            **state,
            "final_html": html,
            "document_title": doc["title"],
            "document_created": doc,
            "fill_stats": stats,
            "response": response,
        }

    def decompose_task_node(state: DraftHybridState) -> DraftHybridState:
        plan = decompose_draft_task(state["user_prompt"])
        return {**state, "task_plan": plan.to_state_dict()}

    def triage_node(state: DraftHybridState) -> DraftHybridState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        triage = triage_case_documents(
            db=_require_db(db),
            case_id=state["case_id"],
            task_plan=plan,
            attached_file_ids=state.get("attached_file_ids"),
        )
        return {**state, "triage": triage.to_state_dict()}

    def retrieve_node(state: DraftHybridState) -> DraftHybridState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        triage = DocumentTriageResult.model_validate(state.get("triage") or {})
        snapshot = run_case_materials_retrieval(
            db=_require_db(db),
            case_id=state["case_id"],
            user_prompt=state["user_prompt"],
            task_plan=plan,
            triage=triage,
            attached_file_ids=state.get("attached_file_ids"),
        )
        return {**state, "case_retrieval": snapshot.to_state_dict()}

    def extract_node(state: DraftHybridState) -> DraftHybridState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        triage = DocumentTriageResult.model_validate(state.get("triage") or {})
        records = run_parallel_extraction(
            db=_require_db(db),
            case_id=state["case_id"],
            task_plan=plan,
            triage=triage,
        )
        return {**state, "extraction_records": [r.model_dump() for r in records]}

    def consolidate_node(state: DraftHybridState) -> DraftHybridState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        raw_records = state.get("extraction_records") or []
        records = [
            DocumentExtractionRecord.model_validate(x) for x in raw_records if isinstance(x, dict)
        ]
        facts = consolidate_extractions(
            records=records,
            task_plan=plan,
            user_prompt=state["user_prompt"],
        )
        intent = _brief_intent_from_state(state, session)
        facts = apply_brief_to_facts(facts, intent)
        return {**state, "extracted_facts": facts.to_prompt_json()}

    def assess_coverage_node(state: DraftHybridState) -> DraftHybridState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        assessment = assess_fact_coverage(
            user_prompt=state["user_prompt"],
            facts=facts,
            task_plan=plan,
            template_mode=state.get("template_mode") or "template_guide",
        )
        logger.info(
            "[draft_agent.workflow] coverage sufficient=%s gaps=%s score=%.2f retry=%s",
            assessment.sufficient,
            len(assessment.gaps),
            assessment.score,
            state.get("retrieval_retry_count") or 0,
        )
        return {
            **state,
            "coverage_gaps": assessment.to_state_list(),
            "coverage_sufficient": assessment.sufficient,
        }

    def targeted_retrieval_node(state: DraftHybridState) -> DraftHybridState:
        retrieval = CaseRetrievalSnapshot.model_validate(state.get("case_retrieval") or {})
        updated = run_targeted_gap_retrieval(
            db=_require_db(db),
            case_id=state["case_id"],
            gaps=state.get("coverage_gaps") or [],
            existing=retrieval,
            attached_file_ids=state.get("attached_file_ids"),
        )
        merged_facts = extract_case_fact_passport(
            user_prompt=state["user_prompt"],
            case_retrieval=updated,
        )
        base = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        facts = merge_extracted_facts(base, merged_facts)
        intent = _brief_intent_from_state(state, session)
        facts = apply_brief_to_facts(facts, intent)
        retries = int(state.get("retrieval_retry_count") or 0) + 1
        return {
            **state,
            "case_retrieval": updated.to_state_dict(),
            "extracted_facts": facts.to_prompt_json(),
            "retrieval_retry_count": retries,
            "coverage_sufficient": False,
        }

    def verify_financials_node(state: DraftHybridState) -> DraftHybridState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        intent = _brief_intent_from_state(state, session)
        should_verify = bool(
            intent and intent.requires_financial_calc
            or facts.penalty_terms
            or facts.financial.partial_payments
            or facts.amounts
        )
        if should_verify:
            emit_tool_started(TOOL_CALCULATOR, {"reason": "автоматический расчёт неустойки"})
        verified = run_verify_financials(facts)
        if verified.financial.verified:
            v = verified.financial.verified
            summary = f"Итог: {v.total_claim}"
            if v.state_duty:
                summary += f", госпошлина: {v.state_duty}"
            emit_tool_completed(
                TOOL_CALCULATOR,
                success=True,
                output_summary=summary,
            )
        return {**state, "extracted_facts": verified.to_prompt_json()}

    def generate_document_node(state: DraftHybridState) -> DraftHybridState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        retrieval = state.get("case_retrieval") or {}
        rag_context = str(retrieval.get("rag_context") or "") if isinstance(retrieval, dict) else ""
        mode = state.get("template_mode") or "template_guide"
        intent = _brief_intent_from_state(state, session)
        instruction = build_document_instruction(
            user_question=state["user_prompt"],
            facts=facts,
            rag_context=rag_context,
            brief_intent=intent,
        )

        emit_tool_started(
            TOOL_WRITE_DOCUMENT,
            {"mode": mode, "title": session.template.template_label or facts.document_type or ""},
        )

        if mode == "template_guide" and session.template.template_html:
            title, html, meta = produce_draft_html(
                _require_db(db),
                session=session,
                document_instruction=instruction,
                document_title=session.template.template_label,
            )
        elif mode == "scratch":
            html = run_unified_draft_generation(
                strategy="scratch",
                user_prompt=state["user_prompt"],
                facts=facts,
                rag_context=rag_context,
                template_html=None,
                template_label=None,
            )
            title = (facts.document_type or "Новый документ")[:255]
            meta = {"fill_mode": "scratch"}
        else:
            title, html, meta = produce_draft_html(
                _require_db(db),
                session=session,
                document_instruction=instruction,
            )

        return {
            **state,
            "final_html": html,
            "document_title": title,
            "fill_stats": meta,
        }

    def complete_document_node(state: DraftHybridState) -> DraftHybridState:
        html = state.get("final_html") or ""
        if not html.strip():
            return {
                **state,
                "errors": (state.get("errors") or []) + ["complete: empty draft"],
            }

        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        intent = _brief_intent_from_state(state, session)
        financial_claim = bool(intent and intent.requires_financial_calc)
        instruction = build_document_instruction(
            user_question=state["user_prompt"],
            facts=facts,
            brief_intent=intent,
        )
        amounts_block = build_verified_amounts_block(facts)

        plan = build_document_completion_plan(
            html,
            facts=facts,
            financial_claim=financial_claim,
        )

        if plan.run_completion:
            gap_report = build_completion_gap_report(plan)
            logger.info(
                "[draft_agent.workflow] completion pass gaps=%s financial=%s",
                plan.gap_labels,
                financial_claim,
            )
            try:
                html = complete_draft_document_html(
                    draft_html=html,
                    gap_report=gap_report,
                    verified_amounts_block=amounts_block,
                    document_instruction=instruction,
                    financial_claim=financial_claim,
                )
            except Exception as exc:
                logger.error("[draft_agent.workflow] completion failed: %s", exc, exc_info=True)
                return {
                    **state,
                    "errors": (state.get("errors") or []) + [f"completion: {exc}"],
                }

        verified = facts.financial.verified
        expected_amounts: List[str] = []
        if verified:
            for val in (
                verified.principal_outstanding,
                verified.penalty_amount,
                verified.total_claim,
                verified.state_duty,
            ):
                if val:
                    expected_amounts.append(str(val))

        lint = review_draft_html(
            html,
            expected_amounts=expected_amounts or None,
            financial_claim=financial_claim,
            verified_penalty=str(verified.penalty_amount) if verified else None,
            verified_total=str(verified.total_claim) if verified else None,
            verified_state_duty=str(verified.state_duty) if verified else None,
        )

        fill_stats = dict(state.get("fill_stats") or {})
        fill_stats["review"] = lint
        if not lint["passed"]:
            msg = "; ".join(lint.get("issues") or [])
            fill_stats["review_issues"] = lint.get("issues")
            logger.warning("[draft_agent.workflow] review issues (non-blocking): %s", msg)
        if plan.run_completion:
            fill_stats["completion_pass"] = True
            fill_stats["completion_gaps"] = plan.gap_labels

        return {
            **state,
            "final_html": html,
            "fill_stats": fill_stats,
        }

    def persist_node(state: DraftHybridState) -> DraftHybridState:
        html = state.get("final_html") or ""
        if not html.strip():
            return {
                **state,
                "errors": (state.get("errors") or []) + ["persist: empty html"],
                "response": "❌ Документ не сформирован",
            }

        title = (state.get("document_title") or "Новый документ")[:255]
        doc = persist_draft_document(
            _require_db(db),
            case_id=state["case_id"],
            user_id=state["user_id"],
            title=title,
            content=html,
        )
        fill_mode = (state.get("fill_stats") or {}).get("fill_mode", state.get("template_mode") or "draft")
        artifact = {
            "type": "document",
            "id": doc["id"],
            "title": doc["title"],
            "path": f"/cases/{state['case_id']}/editor/{doc['id']}",
            "preview": doc.get("preview", "")[:300],
        }
        emit_tool_completed(
            TOOL_WRITE_DOCUMENT,
            success=True,
            output_summary=f"Документ «{doc['title']}» создан",
            artifact=artifact,
        )
        response = build_chat_summary(
            document_title=doc["title"],
            document_id=doc["id"],
            case_id=state["case_id"],
            fill_mode=str(fill_mode),
            coverage_gaps=state.get("coverage_gaps"),
            fill_stats=state.get("fill_stats"),
        )
        return {
            **state,
            "document_created": doc,
            "response": response,
        }

    g = StateGraph(DraftHybridState)
    g.add_node("catalog_fill", catalog_fill_node)
    g.add_node("decompose_task", decompose_task_node)
    g.add_node("triage_documents", triage_node)
    g.add_node("retrieve_materials", retrieve_node)
    g.add_node("parallel_extract", extract_node)
    g.add_node("consolidate_state", consolidate_node)
    g.add_node("assess_coverage", assess_coverage_node)
    g.add_node("targeted_retrieval", targeted_retrieval_node)
    g.add_node("verify_financials", verify_financials_node)
    g.add_node("generate_document", generate_document_node)
    g.add_node("complete_document", complete_document_node)
    g.add_node("persist", persist_node)

    g.add_conditional_edges(START, _route_entry, {"catalog_fill": "catalog_fill", "decompose_task": "decompose_task"})
    g.add_edge("catalog_fill", END)
    g.add_edge("decompose_task", "triage_documents")
    g.add_edge("triage_documents", "retrieve_materials")
    g.add_edge("retrieve_materials", "parallel_extract")
    g.add_edge("parallel_extract", "consolidate_state")
    g.add_edge("consolidate_state", "assess_coverage")
    g.add_conditional_edges(
        "assess_coverage",
        _route_after_coverage,
        {"targeted_retrieval": "targeted_retrieval", "verify_financials": "verify_financials"},
    )
    g.add_edge("targeted_retrieval", "assess_coverage")
    g.add_edge("verify_financials", "generate_document")
    g.add_edge("generate_document", "complete_document")
    g.add_edge("complete_document", "persist")
    g.add_edge("persist", END)

    compiled = g.compile()
    logger.info(
        "[draft_agent.workflow] compiled mode=%s max_retries=%s",
        session.template.mode,
        _max_coverage_retries(),
    )
    return compiled
