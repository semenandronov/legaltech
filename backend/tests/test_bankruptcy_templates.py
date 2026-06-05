"""Системные шаблоны банкротства и сборка draft template context."""

import pytest


def test_list_public_templates_non_empty():
    from app.services.bankruptcy_templates import list_public_templates

    items = list_public_templates()
    assert isinstance(items, list)
    assert len(items) >= 1
    assert all("id" in x and "title" in x for x in items)


def test_load_system_template_body():
    from app.services.bankruptcy_templates import load_system_template_body

    text, title = load_system_template_body("rtk_claim_st71")
    assert text
    assert "ЗАЯВЛЕНИЕ" in text or "заявлен" in text.lower()
    assert title


def test_uploaded_pdf_template_when_file_present():
    """Если doc1.pdf лежит в templates/bankruptcy/, проверяем конвертацию в HTML."""
    from pathlib import Path

    from app.services.bankruptcy_templates import _DIR, load_system_template_body

    if not (Path(_DIR) / "doc1.pdf").is_file():
        pytest.skip("doc1.pdf не найден в каталоге шаблонов — скопируйте файл из Downloads")

    text, title = load_system_template_body("uploaded_doc1")
    assert text
    assert "pdf-content" in text or "<p>" in text
    assert title


def test_find_best_system_template_match_isk():
    from app.services.bankruptcy_templates import find_best_system_template_match

    tid = find_best_system_template_match(
        "Пожалуйста составь исковое заявление о взыскании долга",
        min_score=8,
    )
    assert tid == "lawyer_statement_of_claim"


def test_find_best_system_template_match_rtk():
    from app.services.bankruptcy_templates import find_best_system_template_match

    tid = find_best_system_template_match(
        "заявление о включении требования в реестр требований кредиторов, ст. 71",
        min_score=8,
    )
    assert tid == "rtk_claim_st71"


def test_resolve_draft_auto_template_from_question(monkeypatch):
    from app.services import draft_template_context as dtc

    monkeypatch.setattr(
        dtc,
        "auto_pick_system_template_id",
        lambda q, db=None: "lawyer_statement_of_claim",
    )

    from app.services.draft_template_context import resolve_draft_template_context

    class _Q:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, *a):
            return _Q()

    text, label, _tkey = resolve_draft_template_context(
        _Db(),
        template_system_id=None,
        template_file_content=None,
        template_file_id=None,
        user_question="Составь исковое заявление",
    )
    assert text
    assert "ИСКОВОЕ ЗАЯВЛЕНИЕ" in text
    assert label


def test_resolve_priority_system_over_file_content():
    from app.services.draft_template_context import resolve_draft_template_context

    class _Q:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, *a):
            return _Q()

    text, label, _tkey = resolve_draft_template_context(
        _Db(),
        template_system_id="rtk_claim_st71",
        template_file_content="<p>USER FILE</p>",
        template_file_id=None,
    )
    assert "USER FILE" not in text
    assert "ЗАЯВЛЕНИЕ" in text or "заявлен" in text.lower()
