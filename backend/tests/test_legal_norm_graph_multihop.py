"""Тесты многошагового обхода графа норм."""

from unittest.mock import patch

from app.services.legal_norm_graph import expand_norm_neighbor_edges_multihop


def test_multihop_bfs_calls_expand_per_hop():
    calls = []

    def fake_expand(keys, **kwargs):
        calls.append(list(keys))
        if keys == ["a"]:
            return [("b", "REFERENCES")]
        if keys == ["b"]:
            return [("c", "FORWARD_TO")]
        return []

    with patch(
        "app.services.legal_norm_graph.expand_norm_neighbor_edges",
        side_effect=fake_expand,
    ):
        out = expand_norm_neighbor_edges_multihop(
            ["a"],
            max_hops=2,
            limit_per_hop=5,
            total_limit=10,
        )

    assert ("b", "REFERENCES") in out
    assert ("c", "FORWARD_TO") in out
    assert calls == [["a"], ["b"]]


def test_multihop_respects_total_limit():
    def fake_expand(keys, **kwargs):
        return [(f"{k}-n", "REFERENCES") for k in keys]

    with patch(
        "app.services.legal_norm_graph.expand_norm_neighbor_edges",
        side_effect=fake_expand,
    ):
        out = expand_norm_neighbor_edges_multihop(
            ["root"],
            max_hops=3,
            limit_per_hop=10,
            total_limit=1,
        )

    assert len(out) == 1
