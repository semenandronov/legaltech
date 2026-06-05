"""Итеративный добор legal_corpus в global assistant: чистые хелперы."""

from app.services.chat.global_langgraph_service import (
    _dedupe_extend_law_hits,
    _legal_digest_for_iterative_planner,
    _global_hit_merge_key,
)


def test_dedupe_extend_law_hits_skips_duplicates():
    a = [{"source_type": "legal_corpus", "source_id": "1", "text": "hello world", "score": 1.0}]
    b = [
        {"source_type": "legal_corpus", "source_id": "1", "text": "hello world", "score": 0.5},
        {"source_type": "legal_corpus", "source_id": "2", "text": "other chunk", "score": 0.9},
    ]
    out = _dedupe_extend_law_hits(a, b)
    assert len(out) == 2
    keys = {_global_hit_merge_key(x) for x in out}
    assert len(keys) == 2


def test_legal_digest_includes_only_legal_corpus():
    merged = [
        {"source_type": "document", "text": "x" * 100, "score": 99.0, "file_name": "d.docx"},
        {
            "source_type": "legal_corpus",
            "text": "статья 61.2 подозрительная сделка",
            "score": 0.5,
            "file_name": "127.pdf",
        },
    ]
    d = _legal_digest_for_iterative_planner(merged, max_fragments=3, frag_chars=80)
    assert "127.pdf" in d
    assert "61.2" in d
    assert "d.docx" not in d
