"""LangGraph definition for agentic Draft pipeline."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _require_db(db: Optional[Session]) -> Session:
    if db is None:
        raise RuntimeError("draft_pipeline: database session is required")
    return db


class DraftPipelineGraphState(TypedDict, total=False):
    case_id: str
    user_id: str
    user_prompt: str
    attached_file_ids: Optional[List[str]]
    template_system_id: Optional[str]
    template_context: Optional[str]
    template_label: Optional[str]
    template_key: Optional[str]

    # Prebuilt by internal case assistant (retrieval + extract + optional calculator).
    _from_internal_assistant: bool
    financial_calculator_meta: Dict[str, Any]

    task_plan: Dict[str, Any]
    triage: Dict[str, Any]
    case_retrieval: Dict[str, Any]
    extraction_records: List[Dict[str, Any]]

    strategy: str
    generation_mode: str
    resolved_template_id: Optional[str]
    document_title: str
    extracted_facts: Dict[str, Any]

    blueprint: List[Dict[str, Any]]
    generated_sections: Dict[str, str]

    final_html: str
    document_created: Optional[Dict[str, Any]]
    response: str
    errors: List[str]


def _route_draft_pipeline_entry(state: DraftPipelineGraphState) -> str:
    if state.get("_from_internal_assistant") and state.get("extracted_facts"):
        return "resolve_template"
    return "decompose_task"


def _route_after_verify_financials(state: DraftPipelineGraphState) -> str:
    from app.services.draft_pipeline.generation_mode import is_unified_generation

    if is_unified_generation():
        return "generate_unified"
    return "blueprint"


def create_draft_pipeline_graph(db: Optional[Session] = None):
    from app.services.draft_pipeline.schemas import (
        BlueprintSection,
        DocumentTriageResult,
        DraftTaskPlan,
        ExtractedFacts,
    )
    from app.services.draft_pipeline.nodes.task_decomposer import decompose_draft_task
    from app.services.draft_pipeline.nodes.document_triage import triage_case_documents
    from app.services.draft_pipeline.nodes.retrieve_materials import run_case_materials_retrieval
    from app.services.draft_pipeline.nodes.parallel_extract import run_parallel_extraction
    from app.services.draft_pipeline.nodes.consolidate_state import consolidate_extractions
    from app.services.draft_pipeline.nodes.resolve_template import resolve_template_strategy
    from app.services.draft_pipeline.nodes.blueprint_builder import run_blueprint_builder
    from app.services.draft_pipeline.nodes.generate_sections import run_parallel_section_generation
    from app.services.draft_pipeline.nodes.compiler import run_compiler
    from app.services.draft_pipeline.nodes.verify_financials import run_verify_financials
    from app.services.draft_pipeline.nodes.unified_generator import run_unified_draft_generation
    from app.services.draft_pipeline.nodes.document_linter import run_document_linter
    from app.services.draft_pipeline.nodes.persist import run_persist
    from app.services.draft_pipeline.generation_mode import get_draft_generation_mode

    def decompose_task_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        plan = decompose_draft_task(state["user_prompt"])
        return {**state, "task_plan": plan.to_state_dict()}

    def triage_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        triage = triage_case_documents(
            db=_require_db(db),
            case_id=state["case_id"],
            task_plan=plan,
            attached_file_ids=state.get("attached_file_ids"),
        )
        return {**state, "triage": triage.to_state_dict()}

    def retrieve_materials_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
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

    def parallel_extract_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        triage = DocumentTriageResult.model_validate(state.get("triage") or {})
        records = run_parallel_extraction(
            db=_require_db(db),
            case_id=state["case_id"],
            task_plan=plan,
            triage=triage,
        )
        return {**state, "extraction_records": [r.model_dump() for r in records]}

    def consolidate_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        from app.services.draft_pipeline.schemas import DocumentExtractionRecord

        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        raw_records = state.get("extraction_records") or []
        records = [DocumentExtractionRecord.model_validate(x) for x in raw_records if isinstance(x, dict)]
        facts = consolidate_extractions(
            records=records,
            task_plan=plan,
            user_prompt=state["user_prompt"],
        )
        return {**state, "extracted_facts": facts.to_prompt_json()}

    def resolve_template_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        plan = DraftTaskPlan.model_validate(state.get("task_plan") or {})
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        strategy, tid, title, tc, tl, tkey, facts = resolve_template_strategy(
            db=_require_db(db),
            user_prompt=state["user_prompt"],
            facts=facts,
            task_plan=plan,
            template_system_id=state.get("template_system_id"),
            template_context=state.get("template_context"),
            template_label=state.get("template_label"),
            template_key=state.get("template_key"),
        )
        return {
            **state,
            "strategy": strategy,
            "generation_mode": get_draft_generation_mode(),
            "resolved_template_id": tid,
            "document_title": title,
            "template_context": tc or state.get("template_context"),
            "template_label": tl or state.get("template_label"),
            "template_key": tkey or state.get("template_key"),
            "extracted_facts": facts.to_prompt_json(),
        }

    def verify_financials_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        if state.get("_from_internal_assistant") and facts.financial.verified:
            logger.info(
                "[draft_pipeline.graph] verify_financials skipped — assistant calculator already applied"
            )
            return state
        verified = run_verify_financials(facts)
        return {**state, "extracted_facts": verified.to_prompt_json()}

    def generate_unified_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        retrieval = state.get("case_retrieval") or {}
        rag_context = str(retrieval.get("rag_context") or "") if isinstance(retrieval, dict) else ""
        html = run_unified_draft_generation(
            strategy=state.get("strategy") or "scratch",
            user_prompt=state["user_prompt"],
            facts=facts,
            rag_context=rag_context,
            template_html=state.get("template_context"),
            template_label=state.get("template_label"),
        )
        return {
            **state,
            "generation_mode": "unified",
            "final_html": html,
            "blueprint": [],
            "generated_sections": {},
        }

    def blueprint_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        sections = run_blueprint_builder(
            strategy=state.get("strategy") or "scratch",
            template_html=state.get("template_context"),
            user_prompt=state["user_prompt"],
            facts=facts,
        )
        return {**state, "generation_mode": "decomposed", "blueprint": [s.model_dump() for s in sections]}

    def sections_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        blueprint = [BlueprintSection.model_validate(x) for x in (state.get("blueprint") or [])]
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        generated = run_parallel_section_generation(
            blueprint=blueprint,
            facts=facts,
            user_prompt=state["user_prompt"],
        )
        return {**state, "generated_sections": generated}

    def compiler_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        blueprint = [BlueprintSection.model_validate(x) for x in (state.get("blueprint") or [])]
        html = run_compiler(
            strategy=state.get("strategy") or "scratch",
            template_html=state.get("template_context"),
            blueprint=blueprint,
            generated_sections=state.get("generated_sections") or {},
        )
        return {**state, "final_html": html}

    def linter_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        polished = run_document_linter(
            html=state.get("final_html") or "",
            facts=facts,
            user_prompt=state["user_prompt"],
        )
        return {**state, "final_html": polished}

    def persist_node(state: DraftPipelineGraphState) -> DraftPipelineGraphState:
        blueprint = [BlueprintSection.model_validate(x) for x in (state.get("blueprint") or [])]
        facts = ExtractedFacts.from_llm_dict(state.get("extracted_facts") or {})
        title = state.get("document_title") or "Новый документ"
        gen_mode = state.get("generation_mode") or get_draft_generation_mode()
        doc_created = run_persist(
            db=_require_db(db),
            case_id=state["case_id"],
            user_id=state["user_id"],
            title=title,
            final_html=state.get("final_html") or "",
            strategy=state.get("strategy") or "scratch",
            template_id=state.get("resolved_template_id"),
            template_key=state.get("template_key"),
            template_html=state.get("template_context"),
            facts=facts,
            blueprint=blueprint,
            generated_sections=state.get("generated_sections") or {},
            case_retrieval=state.get("case_retrieval") or {},
            task_plan=state.get("task_plan") or {},
            triage=state.get("triage") or {},
            extraction_records=state.get("extraction_records") or [],
            generation_mode=gen_mode,
        )
        return {
            **state,
            "document_created": doc_created,
            "response": f'✅ Документ "{doc_created.get("title", title)}" успешно создан!',
        }

    g = StateGraph(DraftPipelineGraphState)
    g.add_node("decompose_task", decompose_task_node)
    g.add_node("triage_documents", triage_node)
    g.add_node("retrieve_materials", retrieve_materials_node)
    g.add_node("parallel_extract", parallel_extract_node)
    g.add_node("consolidate_state", consolidate_node)
    g.add_node("resolve_template", resolve_template_node)
    g.add_node("verify_financials", verify_financials_node)
    g.add_node("generate_unified", generate_unified_node)
    g.add_node("blueprint", blueprint_node)
    g.add_node("generate_sections", sections_node)
    g.add_node("compiler", compiler_node)
    g.add_node("linter", linter_node)
    g.add_node("persist", persist_node)

    g.add_conditional_edges(
        START,
        _route_draft_pipeline_entry,
        {
            "decompose_task": "decompose_task",
            "resolve_template": "resolve_template",
        },
    )
    g.add_edge("decompose_task", "triage_documents")
    g.add_edge("triage_documents", "retrieve_materials")
    g.add_edge("retrieve_materials", "parallel_extract")
    g.add_edge("parallel_extract", "consolidate_state")
    g.add_edge("consolidate_state", "resolve_template")
    g.add_edge("resolve_template", "verify_financials")
    g.add_conditional_edges(
        "verify_financials",
        _route_after_verify_financials,
        {
            "generate_unified": "generate_unified",
            "blueprint": "blueprint",
        },
    )
    g.add_edge("generate_unified", "linter")
    g.add_edge("blueprint", "generate_sections")
    g.add_edge("generate_sections", "compiler")
    g.add_edge("compiler", "linter")
    g.add_edge("linter", "persist")
    g.add_edge("persist", END)

    compiled = g.compile()
    logger.info(
        "[draft_pipeline.graph] compiled generation_mode=%s",
        get_draft_generation_mode(),
    )
    return compiled
