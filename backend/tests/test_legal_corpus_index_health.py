"""Тесты health-check индекса справочника."""

from app.services.legal_corpus_index_health import CorpusFileIndexHealth, assert_corpus_file_index_health


def test_assert_health_skipped_when_ok():
    health = CorpusFileIndexHealth(
        corpus_file_id="f1",
        instrument_id="fz-127",
        chunk_count=10,
        norm_chunk_count=8,
        norm_node_count=8,
        graph_edge_count=3,
        articles_with_numbers=4,
        ok=True,
        issues=[],
    )
    assert_corpus_file_index_health(health)


def test_assert_health_raises_when_strict(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "LEGAL_CORPUS_INDEX_GRAPH_VALIDATION_STRICT", True)
    health = CorpusFileIndexHealth(
        corpus_file_id="f1",
        instrument_id="fz-127",
        chunk_count=10,
        norm_chunk_count=0,
        norm_node_count=0,
        graph_edge_count=0,
        articles_with_numbers=0,
        ok=False,
        issues=["no_norm_nodes_for_file"],
    )
    try:
        assert_corpus_file_index_health(health)
        raised = False
    except ValueError:
        raised = True
    assert raised
