"""Response shape delegates to case_assistant_intent."""
from app.services.chat.response_shape import resolve_response_shape


def test_drill_down_shape_via_intent_layer():
    shape, reason = resolve_response_shape(
        question="подробнее про возражение шар",
        task_type="single_doc_extraction",
        depth_tier="fast",
        corpus_size=4,
    )
    assert shape == "memorandum"
    assert reason == "drill_down_semantics"


def test_executive_summary_from_corpus_overview():
    shape, reason = resolve_response_shape(
        question="о чем документы",
        task_type="multi_doc_synthesis",
        depth_tier="fast",
        corpus_size=4,
    )
    assert shape == "executive_summary"
    assert reason == "case_corpus_overview"
