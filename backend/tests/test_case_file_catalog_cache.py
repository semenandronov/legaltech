"""TTL cache for case file catalog."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.chat.case_file_catalog_cache import (
    get_case_file_catalog_cached,
    invalidate_case_catalog_cache,
)


def test_catalog_cache_hit_avoids_rebuild(monkeypatch):
    db = MagicMock()
    entries = [MagicMock(file_id="f1")]
    build_mock = MagicMock(return_value=entries)
    count_mock = MagicMock(return_value=2)
    monkeypatch.setattr(
        "app.services.chat.retrieval_router.build_case_file_catalog",
        build_mock,
    )
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._count_case_files",
        count_mock,
    )
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_CATALOG_CACHE_ENABLED", True)
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_CATALOG_CACHE_TTL_SEC", 600)

    out1 = get_case_file_catalog_cached(db, "case-a", limit=80)
    out2 = get_case_file_catalog_cached(db, "case-a", limit=80)
    assert out1 == entries
    assert out2 == entries
    build_mock.assert_called_once()
    count_mock.assert_called()


def test_invalidate_forces_rebuild(monkeypatch):
    db = MagicMock()
    build_mock = MagicMock(side_effect=[[MagicMock()], [MagicMock(), MagicMock()]])
    monkeypatch.setattr(
        "app.services.chat.retrieval_router.build_case_file_catalog",
        build_mock,
    )
    monkeypatch.setattr(
        "app.services.chat.retrieval_router._count_case_files",
        MagicMock(return_value=1),
    )
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_CATALOG_CACHE_ENABLED", True)

    get_case_file_catalog_cached(db, "case-b")
    invalidate_case_catalog_cache("case-b")
    get_case_file_catalog_cached(db, "case-b")
    assert build_mock.call_count == 2
