"""Legacy case assistant pipeline flag (commit 0018729 parity)."""

from unittest.mock import MagicMock, patch

from app.config import config


def test_legacy_pipeline_skips_http_structured_router():
    from app.services.chat.case_chat_request_prep import (
        CaseChatPrepParams,
        prepare_case_chat_request,
    )

    user = MagicMock()
    user.id = "user-1"

    with patch.object(config, "CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED", True):
        with patch(
            "app.services.chat.structured_data_router.case_has_sql_statement_tables",
            return_value=True,
        ) as has_sql:
            with patch(
                "app.services.chat.structured_data_router.route_structured_data_plane",
            ) as route_plane:
                db = MagicMock()
                result = prepare_case_chat_request(
                    db,
                    CaseChatPrepParams(
                        case_id="case-1",
                        question="о чём возражение",
                        current_user=user,
                        session_id="sess-1",
                    ),
                )
                has_sql.assert_not_called()
                route_plane.assert_not_called()
                assert result.chat_request.structured_data_plane is None


def test_modern_graph_wires_structured_data_nodes():
    with patch.object(config, "CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED", False):
        with patch(
            "app.services.langchain_agents.graphs.chat_graph.get_checkpointer_instance",
            return_value=None,
        ):
            with patch(
                "app.services.langchain_agents.graphs.chat_graph.get_store_instance",
                return_value=None,
            ):
                from app.services.langchain_agents.graphs.chat_graph import create_chat_graph

                graph = create_chat_graph(db=MagicMock(), rag_service=MagicMock())
                node_names = set(graph.nodes.keys())
                assert "structured_data_router" in node_names
                assert "case_transaction_agent" in node_names
                assert "hybrid_structured_agent" in node_names


def test_legacy_graph_wires_tier_router_not_structured_data():
    with patch.object(config, "CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED", True):
        with patch(
            "app.services.langchain_agents.graphs.chat_graph.get_checkpointer_instance",
            return_value=None,
        ):
            with patch(
                "app.services.langchain_agents.graphs.chat_graph.get_store_instance",
                return_value=None,
            ):
                from app.services.langchain_agents.graphs.chat_graph import create_chat_graph

                graph = create_chat_graph(db=MagicMock(), rag_service=MagicMock())
                node_names = set(graph.nodes.keys())
                assert "structured_data_router" not in node_names
                assert "case_transaction_agent" not in node_names
                assert "hybrid_structured_agent" not in node_names
                assert "extract_retrieval_task" in node_names
