"""Validation tests for RAG and legal corpus agent tool schemas."""
import pytest

from app.services.agent_runs.schemas import CaseRagToolInput, LegalCorpusToolInput


def test_case_rag_input_bounds():
    req = CaseRagToolInput(query="сумма договора", k=10)
    assert req.k == 10


def test_case_rag_rejects_short_query():
    with pytest.raises(ValueError):
        CaseRagToolInput(query="x")


def test_legal_corpus_input():
    req = LegalCorpusToolInput(query="статья 395 ГК РФ", k=4)
    assert req.k == 4
