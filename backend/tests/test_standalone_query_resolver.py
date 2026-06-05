"""Standalone query resolver — step 0 before intent."""
from app.services.chat.standalone_query_resolver import resolve_standalone_query


def test_deictic_contract_resolved_from_history():
    history = (
        "Пользователь: о чем документы\n"
        "Ассистент: Договор аренды № 12 от 05.02.2024 — срок 11 месяцев."
    )
    out = resolve_standalone_query(
        "О чём этот договор?",
        dialog_history=history,
    )
    assert out.changed
    assert "договор" in out.resolved_question.lower()
    assert "05.02.2024" in out.resolved_question or "аренды" in out.resolved_question.lower()


def test_explicit_named_doc_not_rewritten():
    out = resolve_standalone_query("о чем Договор от 02.02.2024")
    assert not out.changed
    assert out.resolved_question == "о чем Договор от 02.02.2024"


def test_drill_down_gets_anchor_from_history():
    history = "Ассистент: В возражении от 12.03.2024 указано on waiver of penalty."
    out = resolve_standalone_query(
        "подробнее про возражение",
        dialog_history=history,
    )
    assert out.changed
    assert "возраж" in out.resolved_question.lower()
