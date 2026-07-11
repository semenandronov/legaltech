"""Deterministic retrieval escalation (broaden / deepen)."""
from app.services.chat.retrieval_escalation import (
    build_escalated_retrieval_task,
    dominant_hit_file_ids,
    extract_question_anchors,
    merge_retrieval_documents,
    plan_retrieval_escalation,
    question_anchors_covered,
)
from app.services.chat.tier_graph_nodes import (
    escalate_retrieval_node,
    grade_retrieval_node,
    route_after_grade_retrieval,
)


def test_anchors_extracted_from_case_and_contract_questions():
    anchors = extract_question_anchors(
        "Какой номер дела А40-179003/2024 и сумма 2 443 000 по договору №54?"
    )
    assert any("а40" in a or "179003" in a for a in anchors)
    assert any("54" in a for a in anchors)


def test_anchors_covered_false_when_missing_from_docs():
    docs = [
        {"page_content": "Возражения должников без номера дела", "metadata": {"file_id": "f1"}},
        {"page_content": "Ещё один фрагмент", "metadata": {"file_id": "f1"}},
    ]
    assert question_anchors_covered("Какой номер дела А40-179003/2024?", docs) is False


def test_anchors_covered_true_when_present():
    docs = [
        {
            "page_content": "Дело № А40-179003/2024 Арбитражный суд",
            "metadata": {"file_id": "f1", "score": 0.8},
        },
        {"page_content": "Просительная часть", "metadata": {"file_id": "f1", "score": 0.7}},
    ]
    assert question_anchors_covered("Какой номер дела А40-179003/2024?", docs) is True


def test_plan_broadens_when_narrow_scope_weak():
    plan = plan_retrieval_escalation(
        question="номер дела",
        retrieval_task={
            "search_query": "номер дела",
            "file_ids": ["f1"],
            "scope_mode": "resolved",
            "confidence": 0.5,
            "rationale": "weak_guess",
        },
        docs=[{"page_content": "x", "metadata": {"file_id": "f1"}}],
        retrieval_round=0,
        max_rounds=2,
    )
    assert plan.action == "broaden_full_case"
    assert plan.reason == "weak_under_narrow_scope"
    task = build_escalated_retrieval_task(
        plan=plan, question="номер дела", prior_task={"rationale": "summary"}
    )
    assert task["scope_mode"] == "full_case"
    assert task["file_ids"] == []
    assert task["escalation_lock"] is True


def test_plan_deepens_when_document_ref_scope_bound():
    plan = plan_retrieval_escalation(
        question="Какая стоимость оборудования по договору №51?",
        retrieval_task={
            "search_query": "стоимость №51",
            "file_ids": ["f51"],
            "scope_mode": "resolved",
            "confidence": 0.94,
            "rationale": "document_ref_catalog_match",
            "within_file_expand": True,
        },
        docs=[
            {
                "page_content": "ДОГОВОР ПОСТАВКИ №51 стороны",
                "metadata": {"file_id": "f51", "score": 0.4},
            }
        ],
        retrieval_round=0,
        max_rounds=2,
    )
    assert plan.action == "deepen_in_files"
    assert plan.reason == "weak_under_bound_scope_deepen"
    assert plan.within_file_expand is True
    assert plan.file_ids == ("f51",)
    task = build_escalated_retrieval_task(
        plan=plan,
        question="Какая стоимость оборудования по договору №51?",
        prior_task={"rationale": "document_ref_catalog_match"},
    )
    assert task["file_ids"] == ["f51"]
    assert task["within_file_expand"] is True
    assert task["escalation_lock"] is True


def test_plan_deepens_into_hit_files_on_full_case():
    docs = [
        {"page_content": "a", "metadata": {"file_id": "fa", "score": 0.4}},
        {"page_content": "b", "metadata": {"file_id": "fa", "score": 0.3}},
        {"page_content": "c", "metadata": {"file_id": "fb", "score": 0.2}},
    ]
    plan = plan_retrieval_escalation(
        question="срок передачи по договору",
        retrieval_task={"search_query": "срок", "file_ids": [], "scope_mode": "full_case"},
        docs=docs,
        retrieval_round=0,
        max_rounds=2,
    )
    assert plan.action == "deepen_in_files"
    assert plan.merge_prior_docs is True
    assert "fa" in plan.file_ids
    assert dominant_hit_file_ids(docs)[0] == "fa"


def test_merge_prefers_new_docs_and_dedups():
    prior = [
        {"page_content": "old", "metadata": {"chunk_id": "c1", "file_id": "f1"}},
        {"page_content": "keep", "metadata": {"chunk_id": "c2", "file_id": "f1"}},
    ]
    new_docs = [
        {"page_content": "new", "metadata": {"chunk_id": "c1", "file_id": "f1"}},
    ]
    merged = merge_retrieval_documents(prior, new_docs)
    assert len(merged) == 2
    assert merged[0]["page_content"] == "new"


def test_grade_weak_fast_path_escalates_when_rounds_remain():
    state = {
        "execution_tier": "instant",
        "question": "Какой номер дела А40-179003/2024?",
        "rag_documents": [
            {"page_content": "без номера", "metadata": {"score": 0.5, "file_id": "f1"}},
            {"page_content": "ещё кусок", "metadata": {"score": 0.4, "file_id": "f1"}},
        ],
        "budget_profile": {
            "execution_tier": "instant",
            "max_retrieval_rounds": 2,
            "recall_k": 16,
            "skip_llm_document_scope": True,
            "latency_path": {"kind": "fast", "reason": "default_document_qa"},
        },
        "retrieval_round": 0,
        "retrieval_task": {
            "search_query": "номер дела",
            "file_ids": [],
            "scope_mode": "full_case",
        },
    }
    out = grade_retrieval_node(state)
    assert out.get("grade_retrieval_ok") is False
    assert route_after_grade_retrieval(out) == "escalate_retrieval"

    escalated = escalate_retrieval_node({**state, **out})
    assert escalated["retrieval_task"]["escalation_lock"] is True
    assert escalated["retrieval_task"]["scope_mode"] == "resolved"
    assert escalated["retrieval_round"] == 1
    assert escalated.get("escalation_seed_documents")


def test_grade_weak_fast_accepts_when_rounds_exhausted():
    state = {
        "execution_tier": "instant",
        "question": "сумма",
        "rag_documents": [],
        "budget_profile": {
            "execution_tier": "instant",
            "max_retrieval_rounds": 2,
            "recall_k": 16,
            "skip_llm_document_scope": True,
            "latency_path": {"kind": "fast", "reason": "default_document_qa"},
        },
        "retrieval_round": 1,
    }
    out = grade_retrieval_node(state)
    assert out.get("grade_retrieval_ok") is True
    assert route_after_grade_retrieval(out) == "rag_quality_gate"
