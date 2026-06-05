"""Evidence scope — session-anchored file resolution."""
from app.services.chat.evidence_plan import build_evidence_plan
from app.services.chat.case_assistant_intent import resolve_case_assistant_intent
from app.services.chat.evidence_scope import resolve_evidence_scope
from app.services.chat.retrieval_router import CaseFileCatalogEntry


def _catalog() -> list[CaseFileCatalogEntry]:
    return [
        CaseFileCatalogEntry(
            file_id="f-obj",
            filename="00. возражения ШАК и ШЭР реализация на 6л.pdf",
            summary="Возражения должников ШАК и ШЭР на реализацию имущества",
            key_points=["ШАК", "ШЭР", "реализация"],
        ),
        CaseFileCatalogEntry(
            file_id="f-contract-1",
            filename="05. договор от 02.02.2024 на 5л.pdf",
            summary="Договор займа",
            key_points=["заём", "проценты"],
        ),
        CaseFileCatalogEntry(
            file_id="f-contract-2",
            filename="03. договор от 16.04.2024 на 14л.pdf",
            summary="Договор цессии",
            key_points=["цессия"],
        ),
    ]


def test_drill_down_scopes_to_session_anchor_file():
    scope = resolve_evidence_scope(
        primary_intent="drill_down",
        question="подробнее про Возражения должников (ШАК и ШЭР)",
        anchor_file_ids=["f-obj", "f-contract-1", "f-contract-2", "f-other"],
        catalog=_catalog(),
    )
    assert scope is not None
    assert scope.file_ids == ("f-obj",)
    assert scope.scope_mode == "resolved"
    assert scope.reason == "session_anchor_catalog_match"


def test_mandatory_inherited_file_ids_bypass_catalog():
    scope = resolve_evidence_scope(
        primary_intent="drill_down",
        question="эта сумма",
        anchor_file_ids=["f-obj", "f-contract-1", "f-contract-2"],
        catalog=_catalog(),
        inherited_file_ids=["f-obj"],
    )
    assert scope is not None
    assert scope.file_ids == ("f-obj",)
    assert scope.reason == "turn_context_mandatory_inheritance"


def test_evidence_plan_drill_down_uses_scoped_deep_read_path():
    intent = resolve_case_assistant_intent(question="подробнее про возражение")
    plan = build_evidence_plan(
        intent=intent,
        execution_tier="standard",
        rerank_enabled=True,
        max_retrieval_rounds=1,
    )
    assert plan.retrieval_path == "scoped_deep_read"
    assert plan.evidence_mode == "scoped_rag"


def test_open_scope_when_no_anchor_match():
    scope = resolve_evidence_scope(
        primary_intent="drill_down",
        question="xyz",
        anchor_file_ids=["f-contract-1", "f-contract-2"],
        catalog=_catalog()[1:],
    )
    assert scope is None
