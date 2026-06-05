from __future__ import annotations

from typing import Any, Dict, List

from app.services.langchain_agents.graphs.chat_graph import court_practice_retrieval_node


def test_case_chat_court_practice_retrieval_passes_search_queries(monkeypatch):
    captured: Dict[str, Any] = {}

    def _fake_plan(question: str):
        assert "субсидиар" in question.lower()
        return (["статья 61.11 127-ФЗ субсидиарная ответственность"], "ok")

    class _FakeDoc:
        def __init__(self):
            self.page_content = "текст"
            self.metadata = {"source_type": "court_practice", "source_id": "c1", "case_number": "А40-1/2024"}

    class _FakeRetrieval:
        def __init__(self):
            self.context = "<document id=\"1\" case=\"А40-1/2024\"></document>"
            self.documents = [_FakeDoc()]
            self.hits_count = 1
            self.meta = {}

    def _fake_retrieve(
        question: str,
        final_k: int = 7,
        use_reranker=None,
        search_queries: List[str] | None = None,
        **kwargs,
    ):
        captured["question"] = question
        captured["final_k"] = final_k
        captured["search_queries"] = list(search_queries or [])
        captured["trace_kwargs"] = kwargs
        return _FakeRetrieval()

    def _fake_build_retrieval_citations(docs, source_type: str):
        return [{"source_type": source_type, "source_id": "c1", "file_name": "А40-1/2024", "quote": "текст"}]

    monkeypatch.setattr(
        "app.services.chat.court_practice_planner.plan_court_practice_search_queries",
        _fake_plan,
    )
    monkeypatch.setattr(
        "app.services.court_practice_service.retrieve_court_practice",
        _fake_retrieve,
    )
    monkeypatch.setattr(
        "app.services.chat.citation_payload.build_retrieval_citations",
        _fake_build_retrieval_citations,
    )

    state = {
        "question": "субсидиарная ответственность контролирующих лиц",
        "enable_court_practice": True,
        "citations": [],
        "errors": [],
    }
    out = court_practice_retrieval_node(state)  # type: ignore[arg-type]

    assert captured["search_queries"], "planner queries were not passed to retrieve_court_practice"
    assert out.get("court_practice_search_queries") == captured["search_queries"]
    assert (out.get("court_practice_context") or "").strip()
    assert out.get("citations"), "citations should be produced for included docs"

