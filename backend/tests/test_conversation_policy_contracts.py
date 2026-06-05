from app.services.chat.conversation_policy_service import ConversationPolicyService


def test_task_family_mapping():
    assert ConversationPolicyService.map_task_family("fact_lookup") == "entity_fact"
    assert ConversationPolicyService.map_task_family("single_doc_extraction") == "single_doc"
    assert ConversationPolicyService.map_task_family("multi_doc_synthesis") == "multi_doc"
    assert ConversationPolicyService.map_task_family("legal_reasoning") == "reasoning"
    assert ConversationPolicyService.map_task_family("drafting") == "drafting"


def test_case_card_metadata_routes_to_fact_lookup():
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="сколько лкументов загружено в дело",
        attached_files_count=4,
    )
    assert task_type == "fact_lookup"
    assert depth_tier == "fast"
    assert clarify is False
    assert reason == "case_card_metadata"
    assert conf >= 0.9


def test_timeline_query_routes_to_deep():
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="Построй хронологию дела по всем документам",
        attached_files_count=4,
    )
    assert task_type in {"multi_doc_synthesis", "legal_reasoning"}
    assert depth_tier == "deep"
    assert clarify is False
    assert reason
    assert conf > 0


def test_short_fact_query_routes_to_case_rag_not_clarify():
    """Короткие факт-вопросы идут в RAG по материалам дела, без эвристики длины."""
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="какой инн у ооо нв-строй",
        attached_files_count=0,
    )
    assert task_type in {"single_doc_extraction", "fact_lookup"}
    assert depth_tier == "fast"
    assert clarify is False
    assert reason in {"narrow_fact_semantics", "standard_case_qa_short", "short_single_doc_query"}
    assert conf > 0


def test_vague_short_query_still_uses_rag():
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="что это?",
        attached_files_count=0,
    )
    assert task_type == "single_doc_extraction"
    assert clarify is False
    assert conf > 0


def test_clarification_marker_routes_to_clarification():
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="Уточни, по какому документу делать вывод?",
        attached_files_count=2,
    )
    assert task_type == "clarification"
    assert depth_tier == "fast"
    assert clarify is True
    assert reason == "clarification_request"
    assert conf >= 0.8


def test_plural_documents_overview_routes_to_multi_doc_synthesis():
    """«о чем документы» + несколько файлов — обзор, не single_doc_extraction."""
    task_type, depth_tier, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="о чем документы",
        attached_files_count=4,
    )
    assert task_type == "multi_doc_synthesis"
    assert depth_tier == "fast"
    assert clarify is False
    assert reason == "case_corpus_overview"
    assert conf >= 0.85


def test_multi_doc_overview_fast_execution_tier():
    from app.services.chat.execution_tier import infer_execution_tier_heuristic

    tier, reason = infer_execution_tier_heuristic(
        question="о чем документы",
        task_type="multi_doc_synthesis",
        depth_tier="fast",
    )
    assert tier == "standard"
    assert reason == "multi_doc_overview_fast"


def test_user_toggles_priority_draft_over_codex():
    mode = ConversationPolicyService.map_mode(
        draft_mode=True,
        legal_research=True,
        deep_think=True,
        document_context=None,
        mode_hint=None,
    )
    assert mode == "drafting"


def test_user_toggles_priority_codex_over_default():
    mode = ConversationPolicyService.map_mode(
        draft_mode=False,
        legal_research=True,
        deep_think=False,
        document_context=None,
        mode_hint=None,
    )
    assert mode == "research"


def test_case_state_contract_contains_required_fields():
    contract = ConversationPolicyService.build_case_state_contract(
        case_id="case-1",
        session_id="session-1",
        trace_id="trace-1",
        question="Кто истец?",
        attached_file_ids=["file-1"],
        legal_research=False,
        draft_mode=False,
        task_type="fact_lookup",
        route_confidence=0.87,
        route_reason="fast_fact_markers",
    )
    payload = contract.to_dict()
    assert payload["case_id"] == "case-1"
    assert payload["task_type"] == "fact_lookup"
    assert payload["task_family"] == "entity_fact"
    assert payload["depth_tier"] == "fast"
    assert isinstance(payload["budget_profile"], dict)


def test_multi_doc_budget_profile_uses_size_bucket():
    small = ConversationPolicyService.budget_profile_for_depth(
        "deep",
        "multi_doc_synthesis",
        corpus_size=4,
    )
    medium = ConversationPolicyService.budget_profile_for_depth(
        "deep",
        "multi_doc_synthesis",
        corpus_size=18,
    )
    large = ConversationPolicyService.budget_profile_for_depth(
        "deep",
        "multi_doc_synthesis",
        corpus_size=120,
    )
    assert small["size_bucket"] == "small"
    assert medium["size_bucket"] == "medium"
    assert large["size_bucket"] == "large"
    assert small["max_wall_time_ms"] == 0
    assert medium["max_wall_time_ms"] == 0
    assert large["max_wall_time_ms"] == 0
