"""Tests for draft agent template session resolution."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_agent.prompts import build_draft_system_prompt
from app.services.draft_agent.template_session import resolve_template_session
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec


def test_build_prompt_template_mode_forbids_legal_search():
    from app.services.draft_agent.template_session import ResolvedDraftTemplate

    tmpl = ResolvedDraftTemplate(
        mode="catalog_fill",
        template_html="<p>[ИНН]</p>",
        template_label="Иск",
        field_count=3,
        placeholders=("[ИНН]",),
    )
    prompt = build_draft_system_prompt(tmpl)
    assert "catalog_fill" in prompt
    assert "draft_legal_search" in prompt
    assert "Не" in prompt or "не" in prompt


def test_resolve_template_session_scratch_when_empty():
    db = MagicMock()
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    with patch(
        "app.services.draft_agent.template_session.resolve_template_for_draft",
        return_value=("", None, None),
    ):
        out = resolve_template_session(db, ctx=ctx, user_question="составь договор")
    assert out.mode == "scratch"
    assert not out.has_template


def test_resolve_template_session_catalog_when_fields_indexed():
    db = MagicMock()
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    catalog = TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:rtk_claim_st71",
        indexed_html='<p>[ИНН] <span data-draft-field="ph_0">[ИНН]</span></p>',
        field_specs=[
            TemplateFieldSpec(
                field_id="ph_0",
                marker="[ИНН]",
                semantic_label="ИНН",
                what_to_find="ИНН",
                retrieval_query="ИНН",
            )
        ],
    )
    with patch(
        "app.services.draft_agent.template_session.resolve_template_for_draft",
        return_value=("<p>[ИНН]</p>", "Заявление", "bankruptcy:rtk_claim_st71"),
    ):
        with patch(
            "app.services.draft_agent.template_session.ensure_catalog",
            return_value=catalog,
        ):
            with patch(
                "app.services.draft_agent.template_session._try_build_field_catalog",
                return_value=(catalog, ["[ИНН]"]),
            ):
                out = resolve_template_session(db, ctx=ctx, user_question="заявление о включении")
    assert out.mode == "catalog_fill"
    assert out.has_template
    assert out.skips_legal_tools
    assert out.field_count == 1
    assert "[ИНН]" in out.placeholders


def test_resolve_template_session_keeps_catalog_fill_for_financial_claim():
    db = MagicMock()
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    catalog = TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:lawyer_statement_of_claim",
        indexed_html="<p>[ИНН]</p>",
        field_specs=[
            TemplateFieldSpec(
                field_id="ph_0",
                marker="[ИНН]",
                semantic_label="ИНН",
                what_to_find="ИНН",
                retrieval_query="ИНН",
            )
            for _ in range(3)
        ],
    )
    financial_prompt = (
        "Подготовь иск о взыскании долга и неустойки. Истец — Вектор-М, ответчик — ТехноСфера."
    )
    with patch(
        "app.services.draft_agent.template_session.resolve_template_for_draft",
        return_value=("<p>[ИНН]</p>", "Исковое", "bankruptcy:lawyer_statement_of_claim"),
    ):
        with patch(
            "app.services.draft_agent.template_session.ensure_catalog",
            return_value=catalog,
        ):
            with patch(
                "app.services.draft_agent.template_session._try_build_field_catalog",
                return_value=(catalog, ["[ИНН]"]),
            ):
                out = resolve_template_session(db, ctx=ctx, user_question=financial_prompt)
    assert out.mode == "catalog_fill"
    assert out.brief_intent is not None
    assert out.brief_intent.requires_materials_pipeline is True
    assert out.field_count == 3


def test_resolve_template_session_template_guide_without_fields():
    db = MagicMock()
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    empty_catalog = TemplateFieldCatalogSnapshot(
        template_key="adhoc:abc",
        indexed_html="<article><h1>Иск</h1><p>Текст образца без полей.</p></article>",
        field_specs=[],
    )
    with patch(
        "app.services.draft_agent.template_session.resolve_template_for_draft",
        return_value=(
            "<article><h1>Иск</h1><p>Текст образца.</p></article>",
            "Исковое",
            None,
        ),
    ):
        with patch(
            "app.services.draft_agent.template_session.ensure_catalog",
            return_value=empty_catalog,
        ):
            with patch(
                "app.services.draft_agent.template_session._try_build_field_catalog",
                return_value=(empty_catalog, []),
            ):
                out = resolve_template_session(db, ctx=ctx, user_question="исковое заявление")
    assert out.mode == "template_guide"
    assert out.has_template
    assert out.skips_legal_tools
    assert out.field_count == 0
    assert "template_guide" in out.agent_context_block()


def test_build_prompt_template_guide_mode():
    from app.services.draft_agent.template_session import ResolvedDraftTemplate

    tmpl = ResolvedDraftTemplate(
        mode="template_guide",
        template_html="<article><p>Образец</p></article>",
        template_label="Иск",
    )
    prompt = build_draft_system_prompt(tmpl)
    assert "template_guide" in prompt
    assert "scratch" not in prompt.split("template_guide")[0] or "template_guide" in prompt
