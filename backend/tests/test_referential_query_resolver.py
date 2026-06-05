"""Referential query resolver — Phase 2 PriorTurnEvidence query expansion."""
from unittest.mock import MagicMock, patch

from app.services.chat.referential_query_resolver import (
    ReferentialQueryResolution,
    ReferentialQueryResult,
    resolve_referential_query,
)
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence


def _prior() -> PriorTurnEvidence:
    return PriorTurnEvidence(
        message_id="a1",
        assistant_excerpt=(
            "В возражениях должников ШАК указана сумма требований 1 234 567,89 руб. "
            "по пункту 3.2 договора займа."
        ),
        citations=(
            CitationAnchor(
                source_id="f-obj",
                chunk_id="c-1",
                quote_excerpt="сумма требований 1 234 567,89 руб.",
            ),
        ),
        retrieval_metadata={"file_ids": ["f-obj"]},
    )


def test_llm_disabled_uses_prior_excerpt_fallback():
    with patch(
        "app.services.chat.referential_query_resolver.referential_query_llm_enabled",
        return_value=False,
    ):
        result = resolve_referential_query(
            question="А эта сумма — откуда?",
            prior_evidence=_prior(),
            referential_kind="scoped_deep_read",
        )
    assert isinstance(result, ReferentialQueryResult)
    assert result.resolver == "prior_excerpt_fallback"
    assert result.changed
    assert "сумм" in result.standalone_query.lower() or "1" in result.standalone_query


def test_llm_expands_deictic_query():
    mock_decision = ReferentialQueryResolution(
        standalone_query="откуда в возражениях ШАК указана сумма 1 234 567,89 руб.",
        confidence=0.9,
        reason="resolved_entity",
    )
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = mock_decision
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    with patch(
        "app.services.chat.referential_query_resolver.referential_query_llm_enabled",
        return_value=True,
    ), patch("app.services.llm_factory.create_llm", return_value=mock_llm):
        result = resolve_referential_query(
            question="А эта сумма — откуда?",
            prior_evidence=_prior(),
            referential_kind="scoped_deep_read",
        )

    assert result.resolver == "llm"
    assert result.changed
    assert "1 234 567" in result.standalone_query
    mock_llm.with_structured_output.assert_called_once()


def test_non_referential_kind_unchanged():
    result = resolve_referential_query(
        question="о чем договор?",
        prior_evidence=_prior(),
        referential_kind="none",
    )
    assert not result.changed
    assert result.resolver == "unchanged"
