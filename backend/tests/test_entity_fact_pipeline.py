from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.chat.entity_fact_pipeline import EntityFactPipeline


class _DummyRAG:
    def __init__(self, docs):
        self._docs = docs

    def retrieve_context(self, **_kwargs):
        return self._docs


def test_entity_pipeline_finds_judge():
    docs = [
        Document(
            page_content="Арбитражный суд ... Судья Иванов И.И. рассмотрел дело.",
            metadata={"file_id": "f1", "source_file": "decision.pdf", "source_page": 1},
        )
    ]
    pipeline = EntityFactPipeline(_DummyRAG(docs), db=SimpleNamespace())
    result = pipeline.run_judge_lookup(case_id="c1", question="кто судья в деле")
    assert result.kind == "entity_hit"
    assert "Иванов И.И." in result.answer
    assert result.citations


def test_entity_pipeline_blocks_negative_without_coverage():
    docs = []
    pipeline = EntityFactPipeline(_DummyRAG(docs), db=SimpleNamespace())
    result = pipeline.run_judge_lookup(case_id="c1", question="какие судьи вели дело")
    assert result.kind == "insufficient_coverage"
    assert result.coverage.negative_answer_allowed is False
