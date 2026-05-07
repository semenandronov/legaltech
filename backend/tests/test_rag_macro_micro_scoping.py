from types import SimpleNamespace

from app.services.rag_service import RAGService
from app.config import config


def test_retrieve_hybrid_macro_micro_prefers_scoped_micro(monkeypatch):
    service = RAGService.__new__(RAGService)

    macro_doc = SimpleNamespace(
        page_content="macro",
        metadata={"doc_id": "d1", "chunk_id": "m1", "macro_id": "m1", "chunk_level": "macro"},
    )
    micro_doc_global = SimpleNamespace(
        page_content="micro-global",
        metadata={"doc_id": "d1", "chunk_id": "x1", "chunk_level": "micro"},
    )
    micro_doc_scoped = SimpleNamespace(
        page_content="micro-scoped",
        metadata={"doc_id": "d1", "chunk_id": "s1", "chunk_level": "micro", "parent_macro_id": "m1"},
    )

    calls = []

    def _hybrid_search(**kwargs):
        calls.append(kwargs)
        levels = kwargs.get("chunk_levels") or []
        metadata_filter = kwargs.get("metadata_filter") or {}
        if levels == ["macro"]:
            return [macro_doc]
        if levels == ["micro"] and metadata_filter.get("parent_macro_id"):
            return [micro_doc_scoped]
        if levels == ["micro"]:
            return [micro_doc_global]
        return []

    service.document_processor = SimpleNamespace(hybrid_search=_hybrid_search)

    monkeypatch.setattr("app.services.rag_service.trace_contract_event", lambda *a, **k: None)
    monkeypatch.setattr("app.services.rag_service.get_active_trace_context", lambda: None)

    docs = service._retrieve_hybrid_macro_micro(
        case_id="case-1",
        query="тест",
        k=3,
        alpha=0.7,
        db=None,
    )
    assert any((d.metadata or {}).get("chunk_id") == "s1" for d in docs)
    assert not any((d.metadata or {}).get("chunk_id") == "x1" for d in docs)
    assert any(
        (call.get("metadata_filter") or {}).get("parent_macro_id")
        for call in calls
        if call.get("chunk_levels") == ["micro"]
    )


def test_retrieve_hybrid_macro_micro_strict_mode_no_global_fallback(monkeypatch):
    service = RAGService.__new__(RAGService)
    macro_doc = SimpleNamespace(
        page_content="macro",
        metadata={"doc_id": "d1", "chunk_id": "m1", "macro_id": "m1", "chunk_level": "macro"},
    )
    micro_doc_global = SimpleNamespace(
        page_content="micro-global",
        metadata={"doc_id": "d1", "chunk_id": "x1", "chunk_level": "micro"},
    )

    def _hybrid_search(**kwargs):
        levels = kwargs.get("chunk_levels") or []
        metadata_filter = kwargs.get("metadata_filter") or {}
        if levels == ["macro"]:
            return [macro_doc]
        if levels == ["micro"] and metadata_filter.get("parent_macro_id"):
            return []
        if levels == ["micro"]:
            return [micro_doc_global]
        return []

    service.document_processor = SimpleNamespace(hybrid_search=_hybrid_search)
    monkeypatch.setattr("app.services.rag_service.trace_contract_event", lambda *a, **k: None)
    monkeypatch.setattr("app.services.rag_service.get_active_trace_context", lambda: None)
    monkeypatch.setattr(config, "LEGAL_CHUNKING_GLOBAL_MICRO_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "LEGAL_CHUNKING_SCOPED_MICRO_MIN_DOCS", 2, raising=False)

    docs = service._retrieve_hybrid_macro_micro(
        case_id="case-1",
        query="тест",
        k=3,
        alpha=0.7,
        db=None,
    )
    assert any((d.metadata or {}).get("chunk_id") == "m1" for d in docs)
    assert not any((d.metadata or {}).get("chunk_id") == "x1" for d in docs)
