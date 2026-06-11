"""Tests for workflow artifact mapping from tool outputs."""
from app.services.agent_runs.artifact_collector import artifact_from_tool_result, merge_artifact_items

CASE_ID = "case-abc-123"


def test_artifact_from_draft():
    out = artifact_from_tool_result(
        "agent_draft",
        {
            "document_id": "doc-1",
            "title": "Заявление в суд",
            "preview": "В Арбитражный суд...",
            "editor_path": f"/cases/{CASE_ID}/editor/doc-1",
        },
        case_id=CASE_ID,
    )
    assert out is not None
    assert out["type"] == "document"
    assert out["id"] == "doc-1"
    assert out["title"] == "Заявление в суд"
    assert out["path"] == f"/cases/{CASE_ID}/editor/doc-1"
    assert out["preview"].startswith("В Арбитражный")


def test_artifact_from_tabular():
    out = artifact_from_tool_result(
        "agent_tabular_review",
        {
            "review_id": "rev-9",
            "review_name": "Задолженность",
            "rows": [{"a": 1}, {"a": 2}],
            "saved_count": 4,
        },
        case_id=CASE_ID,
    )
    assert out is not None
    assert out["type"] == "tabular_review"
    assert out["row_count"] == 2
    assert out["saved_count"] == 4
    assert out["path"] == f"/cases/{CASE_ID}/tabular-review/rev-9"


def test_artifact_unknown_tool_returns_none():
    assert artifact_from_tool_result("agent_ping", {"ok": True}, case_id=CASE_ID) is None


def test_merge_dedupes_by_type_and_id():
    first = merge_artifact_items(
        None,
        {"type": "document", "id": "d1", "title": "A", "path": "/p"},
    )
    second = merge_artifact_items(
        first,
        {"type": "document", "id": "d1", "title": "B", "path": "/p2"},
    )
    assert len(second["items"]) == 1
    assert second["items"][0]["title"] == "A"

    third = merge_artifact_items(
        second,
        {"type": "tabular_review", "id": "t1", "title": "T", "path": "/t"},
    )
    assert len(third["items"]) == 2
