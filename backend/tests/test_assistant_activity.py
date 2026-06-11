"""Tests for case assistant activity SSE builders."""
from app.services.chat.assistant_activity import (
    AssistantActivityStep,
    activity_sse,
    build_analyzing_request_activity,
    build_fast_path_recall_completed,
    build_graph_node_activity,
    build_request_accepted_activity,
    build_search_case_running_activity,
    mark_step_completed,
)


def test_request_accepted_is_natural_not_technical():
    step = build_request_accepted_activity(question="о чем документы")
    assert step.step_id == "accepted"
    assert "режим" not in step.content.lower()
    assert "стандартный" not in step.content.lower()
    assert step.content.strip()


def test_analyzing_varies_by_overview_question():
    overview = build_analyzing_request_activity(question="о чем документы в деле")
    dates = build_analyzing_request_activity(question="какая дата договора")
    assert overview.content != dates.content
    assert "фрагмент" not in overview.content.lower()


def test_hidden_nodes_not_surfaced():
    assert build_graph_node_activity("mode_router", {"mode": "normal"}) is None
    assert build_graph_node_activity("sync_execution_tier", {"execution_tier": "standard"}) is None
    assert build_graph_node_activity("grade_retrieval", {}) is None


def test_rag_retrieval_uses_document_names_not_fragment_counts():
    step = build_graph_node_activity(
        "rag_retrieval",
        {
            "rag_documents": [
                {
                    "page_content": "текст",
                    "metadata": {"filename": "Договор поставки.pdf"},
                },
                {
                    "page_content": "текст2",
                    "metadata": {"source_file": "Спецификация №1.pdf"},
                },
            ],
        },
        question="о чем документы",
    )
    assert step is not None
    assert step.step_id == "review"
    assert "Договор поставки" in step.content
    assert "фрагмент" not in step.content.lower()
    assert "«о чем документы»" not in step.content


def test_rerank_hidden_when_no_doc_names():
    step = build_graph_node_activity(
        "rerank_context",
        {"context_pipeline_meta": {"recall_docs": 40, "rerank_docs": 8}},
        question="тест",
    )
    assert step is not None
    assert "40" not in step.content
    assert "rerank" not in step.content.lower()


def test_fast_path_recall_no_fragment_jargon():
    step = build_fast_path_recall_completed(
        question="дата подписания",
        retrieved_chunks=7,
        docs_used=2,
    )
    assert step.status == "completed"
    assert "фрагмент" not in step.content.lower()
    assert "7" not in step.content


def test_search_running_no_scope_mode_jargon():
    step = build_search_case_running_activity(
        question="о чем документы",
        scope_mode="passport",
        file_count=3,
    )
    assert "passport" not in step.content.lower()
    assert "описан" not in step.content.lower() or "документ" in step.content.lower()
    assert "«о чем" not in step.content


def test_variation_stable_within_same_seed():
    a = build_request_accepted_activity(question="один и тот же вопрос")
    b = build_request_accepted_activity(question="один и тот же вопрос")
    assert a.content == b.content


def test_activity_sse_payload():
    step = AssistantActivityStep(
        step_id="answer",
        phase="generate_response",
        step=3,
        total_steps=4,
        label="Готовлю ответ с опорой на просмотренные документы",
        content="Готовлю ответ с опорой на просмотренные документы",
        status="running",
    )
    sse = activity_sse(step)
    assert '"type": "assistant_activity"' in sse
    assert "assistant_activity" in sse


def test_mark_completed():
    step = mark_step_completed(build_request_accepted_activity(question="x"))
    assert step.status == "completed"
