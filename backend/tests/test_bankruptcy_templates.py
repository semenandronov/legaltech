"""Системные шаблоны Draft и сборка draft template context."""

import pytest


def test_list_public_templates_has_docxtpl_entries():
    from app.services.bankruptcy_templates import clear_manifest_cache, list_public_templates

    clear_manifest_cache()
    items = list_public_templates()
    assert isinstance(items, list)
    assert len(items) == 4
    assert all(i.get("engine") == "docxtpl" for i in items)


def test_get_manifest_placeholders_docxtpl():
    from app.services.bankruptcy_templates import clear_manifest_cache, get_manifest_placeholders

    clear_manifest_cache()
    ph = get_manifest_placeholders("creditor_ul_general")
    assert len(ph) == 22
    assert ph[0]["variable"] == "court_name"


def test_load_system_template_body_docxtpl():
    from app.services.bankruptcy_templates import clear_manifest_cache, load_system_template_body

    clear_manifest_cache()
    text, title = load_system_template_body("creditor_ul_general")
    assert text is not None
    assert "{{ court_name }}" in text
    assert title


def test_find_best_system_template_match_creditor_ul():
    from app.services.bankruptcy_templates import clear_manifest_cache, find_best_system_template_match

    clear_manifest_cache()
    tid = find_best_system_template_match(
        "заявление кредитора о банкротстве юридического лица",
        min_score=8,
    )
    assert tid == "creditor_ul_general"


def test_resolve_draft_auto_template_no_manifest(monkeypatch):
    from app.services import draft_template_context as dtc

    monkeypatch.setattr(dtc, "auto_pick_system_template_id", lambda q, db=None, **kwargs: None)

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

    text, label, tkey = resolve_draft_template_context(
        _Db(),
        template_file_content=None,
        template_file_id=None,
        user_question="Составь заявление кредитора о банкротстве",
    )
    assert text == ""
    assert label is None
    assert tkey is None


def test_resolve_priority_file_content_over_auto_match(monkeypatch):
    from app.services import draft_template_context as dtc

    monkeypatch.setattr(
        dtc,
        "auto_pick_system_template_id",
        lambda q, db=None, **kwargs: "debtor_ul_general",
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
        template_file_content="<p>USER FILE</p>",
        template_file_id=None,
        user_question="заявление должника",
    )
    assert text == "<p>USER FILE</p>"
    assert label is None
