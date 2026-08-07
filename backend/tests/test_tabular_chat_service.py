"""Tests for tabular chat table formatting and session ids."""
from app.services.tabular_chat_service import (
    TabularChatService,
    format_cell_display,
    tabular_chat_session_id,
)


def test_tabular_chat_session_id():
    assert tabular_chat_session_id("abc-123") == "tabular:abc-123"


def test_format_cell_display_empty_and_na():
    assert "не заполнено" in format_cell_display({"cell_value": None, "status": "pending"})
    assert "—" in format_cell_display({"cell_value": "N/A", "status": "completed"})


def test_build_llm_messages_includes_readability_guidance():
    svc = TabularChatService.__new__(TabularChatService)
    messages = svc._build_llm_messages(
        table_text="Название таблицы: Тест",
        schema_text="1. «Дата»",
        question="Сколько договоров?",
        history=[],
    )
    system = messages[0].content
    assert "Markdown" in system or "markdown" in system.lower()
    assert "Сколько договоров?" in messages[-1].content


def test_extract_citations_from_answer():
    table_data = {
        "rows": [
            {"file_name": "dogovor.pdf", "file_id": "f1"},
            {"file_name": "akt.pdf", "file_id": "f2"},
        ]
    }
    cites = TabularChatService._extract_citations(
        "В таблице есть dogovor.pdf с датой 01.01.2024",
        table_data,
    )
    assert len(cites) == 1
    assert cites[0]["file"] == "dogovor.pdf"


def test_format_table_data_includes_schema_and_rows():
    svc = TabularChatService.__new__(TabularChatService)
    table_data = {
        "review": {"name": "Тест", "description": "Описание"},
        "columns": [
            {
                "id": "col-1",
                "column_label": "Дата",
                "column_type": "date",
                "prompt": "Дата подписания",
            }
        ],
        "rows": [
            {
                "file_id": "f1",
                "file_name": "dogovor.pdf",
                "cells": {
                    "col-1": {"cell_value": "01.02.2024", "status": "completed"},
                },
            }
        ],
    }
    text = svc.format_table_data_for_llm(table_data)
    assert "Тест" in text
    assert "Дата" in text
    assert "date" in text
    assert "dogovor.pdf" in text
    assert "01.02.2024" in text
