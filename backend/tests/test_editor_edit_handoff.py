"""Tests for Ask → Edit handoff (pending_edit_targets, minimum target count)."""
from app.services.langchain_agents.graphs.editor_edit_handoff import (
    build_pending_targets_from_assistant_text,
    count_explicit_issue_count,
    merge_pending_into_scope,
    parse_assistant_identified_issues,
    resolve_minimum_target_count,
    scope_meets_minimum,
)


def test_count_explicit_issue_count():
    assert count_explicit_issue_count("Нашёл 2 несоответствия по сумме") == 2
    assert count_explicit_issue_count("Сумма указана в двух местах") == 2
    assert count_explicit_issue_count("Одна опечатка") == 0


def test_parse_assistant_identified_issues_numbered():
    text = """
    В документе есть расхождения:
    1. В пункте 4 просительной части указано 4 000 000 руб.
    2. В расчёте в конце указано 5 000 000 руб.
    """
    issues = parse_assistant_identified_issues(text)
    assert len(issues) == 2
    assert "пункте 4" in issues[0]["location"].lower()


def test_build_pending_targets_from_explicit_count():
    text = "Обнаружено 2 несоответствия по сумме задолженности."
    pending = build_pending_targets_from_assistant_text(text)
    assert len(pending) == 2


def test_resolve_minimum_from_pending():
    state = {
        "pending_edit_targets": [
            {"location": "п.4", "change": "сумма"},
            {"location": "расчёт", "change": "сумма"},
        ],
        "messages": [],
    }
    assert resolve_minimum_target_count(state, "да сделай так") == 2


def test_resolve_minimum_from_dialogue_history():
    state = {
        "messages": [
            {"role": "user", "content": "о чем просительная часть"},
            {
                "role": "assistant",
                "content": (
                    "1. В пункте 4 просительной части — 4 млн.\n"
                    "2. В расчёте — 5 млн."
                ),
            },
            {"role": "user", "content": "да сделай так"},
        ],
    }
    assert resolve_minimum_target_count(state, "да сделай так") == 2


def test_scope_meets_minimum():
    scope = {"target_count": 1, "targets": [{"location": "a", "change": "x"}]}
    assert scope_meets_minimum(scope, 2) is False
    assert scope_meets_minimum(scope, None) is True


def test_merge_pending_into_scope():
    scope = {"target_count": 1, "targets": [{"location": "a", "change": "x"}]}
    pending = [
        {"location": "п.4", "change": "6 млн"},
        {"location": "расчёт", "change": "6 млн"},
    ]
    merged = merge_pending_into_scope(scope, pending)
    assert merged["target_count"] == 2
    assert len(merged["targets"]) == 2
