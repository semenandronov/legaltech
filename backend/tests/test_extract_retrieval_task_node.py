"""extract_retrieval_task_node should not re-run LLM when task pre-routed."""
from unittest.mock import MagicMock, patch

from app.services.langchain_agents.graphs.chat_graph import extract_retrieval_task_node


@patch("app.services.chat.case_context_pipeline.pipeline_enabled", return_value=True)
def test_skips_reroute_when_retrieval_task_present(_pe):
    mock_router = MagicMock()
    state = {
        "mode": "normal",
        "case_id": "case-1",
        "question": "неустойка",
        "retrieval_task": {
            "search_query": "неустойка договор",
            "file_ids": ["f1"],
            "scope_mode": "resolved",
            "confidence": 0.9,
            "rationale": "api_pre_route",
        },
    }
    with patch(
        "app.services.chat.retrieval_router.create_case_retrieval_router",
        return_value=mock_router,
    ):
        out = extract_retrieval_task_node(state, db=MagicMock())
    assert out == {}
    mock_router.route.assert_not_called()
