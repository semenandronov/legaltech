from app.services.tabular_coverage_gate import evaluate_tabular_coverage
from langchain_core.documents import Document


def test_coverage_weak_without_docs():
    result = evaluate_tabular_coverage(
        question="неустойка",
        docs=[],
        lexical_terms=("неустойка",),
        exact_literals=(),
        column_type="text",
    )
    assert result.verdict == "weak"


def test_coverage_sufficient_with_lexical_hit():
    docs = [
        Document(
            page_content="Неустойка составляет 0.1%",
            metadata={"lexical_match": True, "rerank_score": 0.5},
        )
    ]
    result = evaluate_tabular_coverage(
        question="неустойка",
        docs=docs,
        lexical_terms=("неустойка",),
        exact_literals=(),
        column_type="text",
        recall_meta={"recall_docs": 1},
    )
    assert result.verdict == "sufficient"
