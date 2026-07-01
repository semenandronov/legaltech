"""Tests for structured-data LLM router (SQL vs RAG)."""

from unittest.mock import MagicMock, patch

from app.services.chat.structured_data_router import (
    StructuredDataRouterDecision,
    route_structured_data_plane,
)


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_rag_for_objection_question(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    mock_catalog.return_value = []
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="rag",
        statement_file_ids=[],
        confidence=0.92,
        rationale="вопрос о сути возражения",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="О чём возражение ШАК и ШЭР?",
    )

    assert result.data_plane == "rag"
    assert result.statement_file_ids == []
    assert result.resolver == "llm"
    mock_llm.assert_called_once()


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_rag_for_statement_summary_question(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    mock_catalog.return_value = []
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="rag",
        confidence=0.88,
        rationale="общее описание выписки",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="О чём эта выписка?",
    )

    assert result.data_plane == "rag"


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1", "stmt-2"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_sql_for_operation_question(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    mock_catalog.return_value = []
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="sql",
        statement_file_ids=["stmt-1"],
        confidence=0.95,
        rationale="конкретная операция по дате",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="11.06.2026 в 19:28 какая была операция?",
    )

    assert result.data_plane == "sql"
    assert result.statement_file_ids == ["stmt-1"]


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_low_confidence_defaults_to_rag(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    mock_catalog.return_value = []
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="sql",
        confidence=0.4,
        rationale="unsure",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="что по выписке?",
    )

    assert result.data_plane == "rag"
    assert result.resolver == "llm_low_confidence"


@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=[],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
def test_router_skips_without_sql_files(_mock_feature, _mock_sql_ids):
    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="сколько операций?",
    )
    assert result.data_plane == "rag"
    assert result.resolver == "precondition_skip"


@patch("app.services.chat.structured_data_graph.route_after_execution_tier", return_value="extract_retrieval_task")
def test_graph_route_sql_rag_hybrid(_mock_tier_route):
    from app.services.chat.structured_data_graph import route_after_structured_data_router

    assert route_after_structured_data_router({"structured_data_plane": "sql"}) == "case_transaction_agent"
    assert route_after_structured_data_router({"structured_data_plane": "hybrid"}) == "hybrid_structured_agent"
    assert (
        route_after_structured_data_router({"structured_data_plane": "rag"})
        == "extract_retrieval_task"
    )


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_hybrid_for_compare_question(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    from app.services.chat.structured_data_router import StatementFileCatalogEntry

    mock_catalog.return_value = [
        StatementFileCatalogEntry(
            file_id="stmt-1", filename="vypiska.pdf", doc_type="bank_statement", has_sql_table=True
        ),
        StatementFileCatalogEntry(
            file_id="doc-2", filename="vozrazhenie.pdf", doc_type="objection", has_sql_table=False
        ),
    ]
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="hybrid",
        statement_file_ids=["stmt-1"],
        rag_file_ids=["doc-2"],
        confidence=0.91,
        rationale="сверка выписки с возражением",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="Совпадают ли платежи в выписке с доводами возражения?",
    )

    assert result.data_plane == "hybrid"
    assert result.statement_file_ids == ["stmt-1"]


@patch("app.services.chat.structured_data_router._invoke_llm_router")
@patch(
    "app.services.chat.structured_data_router.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.structured_data_router.transactions_feature_enabled", return_value=True)
@patch("app.services.chat.structured_data_router.build_statement_file_catalog")
def test_router_narrative_need_overrides_sql_plane(
    mock_catalog,
    _mock_feature,
    _mock_sql_ids,
    mock_llm,
):
    mock_catalog.return_value = []
    mock_llm.return_value = StructuredDataRouterDecision(
        data_plane="sql",
        confidence=0.9,
        information_need="document_narrative",
        rationale="владелец счёта в шапке выписки",
    )

    result = route_structured_data_plane(
        MagicMock(),
        case_id="case-1",
        question="Кто владелец счёта в выписке?",
    )

    assert result.data_plane == "rag"
    assert result.information_need == "document_narrative"
    assert result.resolver == "capability_invariant"
