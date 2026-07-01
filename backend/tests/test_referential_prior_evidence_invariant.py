"""Prior evidence invariants for referential judge."""
from app.services.chat.referential_llm_judge import classify_referential_kind_judge
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence


def test_memory_synthesis_blocked_when_prior_has_citations_and_drill_down():
    prior = PriorTurnEvidence(
        message_id="a1",
        assistant_excerpt="Возражение ШАК о необоснованности банкротства.",
        citations=(
            CitationAnchor(
                source_id="f-obj",
                chunk_id="c-1",
                quote_excerpt="нет оснований для банкротства",
            ),
        ),
        retrieval_metadata={"file_ids": ["f-obj"]},
    )
    result = classify_referential_kind_judge(
        question="подробнее",
        has_prior=True,
        prior_evidence=prior,
        turns=[],
    )
    assert result.referential_kind == "scoped_deep_read"
    assert result.needs_document_retrieval is True
