"""Тесты загрузки полной статьи при graph expand по cross-ref."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat import legal_retrieval_agent as lra
from app.services.legal_norm_graph import (
    EDGE_TYPES_FORWARD,
    _resolve_fetch_norm_keys,
)


def test_resolve_fetch_norm_keys_expands_forward_article_target(monkeypatch):
    expanded = [
        "fz-127::art::3",
        "fz-127::art::3::clause::1",
        "fz-127::art::3::clause::2",
    ]

    monkeypatch.setattr(
        "app.services.legal_norm_graph._norm_keys_for_full_article",
        lambda key, **kw: expanded if key == "fz-127::art::3" else [key],
    )

    resolved = _resolve_fetch_norm_keys(
        ["fz-127::art::3", "fz-127::art::54::clause::1"],
        full_article_for_keys={"fz-127::art::3"},
    )
    assert resolved == [
        "fz-127::art::3",
        "fz-127::art::3::clause::1",
        "fz-127::art::3::clause::2",
        "fz-127::art::54::clause::1",
    ]


def test_expand_with_norm_graph_requests_full_article_on_forward_ref(monkeypatch):
    captured: dict = {}

    def fake_neighbor_edges(keys, **kw):
        return [("fz-127::art::3", "FORWARD_TO"), ("fz-127::art::54", "NEXT")]

    def fake_fetch(keys, *, reference_date=None, full_article_for_keys=None):
        captured["keys"] = list(keys)
        captured["full"] = set(full_article_for_keys or [])
        return [
            Document(
                page_content="п. 1 ст. 3",
                metadata={"norm_node_key": "fz-127::art::3::clause::1", "graph_expanded": True},
            )
        ]

    monkeypatch.setattr(
        "app.services.legal_norm_graph.expand_norm_neighbor_edges",
        fake_neighbor_edges,
    )
    monkeypatch.setattr(
        "app.services.legal_norm_graph.fetch_documents_by_norm_keys",
        fake_fetch,
    )

    source = [
        Document(
            page_content="п. 1 ст. 53",
            metadata={"norm_node_key": "fz-127::art::53::clause::1"},
        )
    ]
    merged = lra._expand_with_norm_graph(source, reference_date=None, limit=8)

    assert captured["full"] == {"fz-127::art::3"}
    assert captured["keys"] == ["fz-127::art::3", "fz-127::art::54"]
    assert EDGE_TYPES_FORWARD == ("FORWARD_TO", "REFERENCES", "DEVELOPS")
    assert len(merged) == 2
