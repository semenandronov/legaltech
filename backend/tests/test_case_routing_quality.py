from __future__ import annotations

from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.metrics import ChatMetrics
from app.routes.assistant_chat_v2 import _is_overview_query


def test_map_case_route_labels() -> None:
    route, reason, confidence = ConversationPolicyService.map_case_route(
        mode="drafting",
        retrieval_mode="matter",
        draft_mode=True,
    )
    assert route == "drafting"
    assert reason == "draft_mode"
    assert confidence > 0.9

    route2, _, _ = ConversationPolicyService.map_case_route(
        mode="case_advice",
        retrieval_mode="hybrid",
        legal_research=True,
        deep_think=True,
        attached_files_count=1,
    )
    assert route2 == "mixed"

    route3, reason3, _ = ConversationPolicyService.map_case_route(
        mode="case_advice",
        retrieval_mode="law",
        legal_research=False,
    )
    assert route3 == "extraction"
    assert reason3 == "default_case_only"


def test_chat_metrics_route_kpis() -> None:
    metrics = ChatMetrics()
    metrics.record_route_outcome("mixed", "mixed")
    metrics.record_route_outcome("mixed", "legal_qna")
    metrics.record_route_outcome("legal_qna", "legal_qna")
    summary = metrics.get_route_kpis()
    assert "confusion_matrix" in summary
    assert summary["per_label"]["mixed"]["precision"] < 1.0
    assert summary["per_label"]["legal_qna"]["recall"] > 0.0


def test_overview_query_detector_marks_corpus_style_intent() -> None:
    assert _is_overview_query("О чем документы в этом деле?")
    assert _is_overview_query("Сделай обзор по документам")
    assert not _is_overview_query("Кто судья по делу?")
