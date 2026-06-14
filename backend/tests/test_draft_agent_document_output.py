"""Tests for draft document output routing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_agent.document_output import produce_draft_html
from app.services.draft_agent.session import DraftAgentSession
from app.services.draft_agent.template_session import ResolvedDraftTemplate
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec


def test_produce_draft_html_catalog_fill():
    catalog = TemplateFieldCatalogSnapshot(
        template_key="bankruptcy:test",
        indexed_html='<p><span data-draft-field="ph_0">[ИНН]</span></p>',
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
    tmpl = ResolvedDraftTemplate(
        mode="catalog_fill",
        template_html=catalog.indexed_html,
        template_label="Тест",
        template_key="bankruptcy:test",
        placeholders=("[ИНН]",),
        field_count=1,
        catalog=catalog,
    )
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    session = DraftAgentSession(ctx=ctx, template=tmpl, user_question="заполни")

    with patch("app.services.draft_agent.document_output.RAGService") as mock_rag_cls:
        with patch("app.services.draft_agent.document_output.execute_catalog_field_fill") as mock_fill:
            mock_fill.return_value = ("<p>7701000000</p>", {"fields_filled": 1, "fields_total": 1})
            title, html, meta = produce_draft_html(
                MagicMock(),
                session=session,
                document_instruction="ИНН истца: 7701000000",
                document_title="Заявление",
            )
    assert title == "Заявление"
    assert "7701000000" in html
    assert meta["fill_mode"] == "catalog_fill"
    mock_fill.assert_called_once()
    mock_rag_cls.assert_called_once()


def test_produce_draft_html_template_guide():
    tmpl = ResolvedDraftTemplate(
        mode="template_guide",
        template_html="<article><h1>Иск</h1><p>Образец текста.</p></article>",
        template_label="Исковое",
        template_key="adhoc:abc",
    )
    ctx = DraftAgentContext(user_id="u1", case_id="c1", session_id="s1")
    session = DraftAgentSession(ctx=ctx, template=tmpl, user_question="иск")

    with patch("app.services.draft_agent.document_output.write_draft_document_html") as mock_write:
        mock_write.return_value = "<article><h1>Иск</h1><p>ООО Альфа</p></article>"
        title, html, meta = produce_draft_html(
            MagicMock(),
            session=session,
            document_instruction="Истец: ООО Альфа",
            document_title="Иск",
        )
    mock_write.assert_called_once()
    call_kw = mock_write.call_args.kwargs
    assert call_kw.get("structure_guide") is True
    assert call_kw.get("template_html")
    assert title == "Иск"
    assert meta["fill_mode"] == "template_guide"
