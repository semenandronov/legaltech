"""Tests for Yandex server-side data logging policy."""

from __future__ import annotations

import pytest


def test_apply_data_logging_headers_defaults_to_false(monkeypatch):
    from app import config as cfg
    from app.services import yandex_privacy as privacy

    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)

    headers = privacy.apply_data_logging_headers({"Authorization": "Api-Key x"})
    assert headers["Authorization"] == "Api-Key x"
    assert headers[privacy.HEADER_NAME] == "false"
    assert privacy.langchain_disable_request_logging() is True
    assert privacy.ycloud_ml_enable_server_data_logging() is False


def test_apply_data_logging_headers_when_enabled(monkeypatch):
    from app import config as cfg
    from app.services import yandex_privacy as privacy

    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", True, raising=False)

    headers = privacy.apply_data_logging_headers({"x-folder-id": "b1"})
    assert headers[privacy.HEADER_NAME] == "true"
    assert privacy.langchain_disable_request_logging() is False
    assert privacy.ycloud_ml_enable_server_data_logging() is True


def test_apply_overwrites_stale_privacy_header(monkeypatch):
    from app import config as cfg
    from app.services import yandex_privacy as privacy

    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)

    headers = privacy.apply_data_logging_headers(
        {privacy.HEADER_NAME: "true", "x-folder-id": "b1"}
    )
    assert headers[privacy.HEADER_NAME] == "false"


def test_merge_grpc_metadata_replaces_prior(monkeypatch):
    from app import config as cfg
    from app.services import yandex_privacy as privacy

    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)

    merged = privacy.merge_grpc_metadata(
        [("authorization", "Api-Key x"), (privacy.HEADER_NAME, "true")]
    )
    assert ("authorization", "Api-Key x") in merged
    assert (privacy.HEADER_NAME, "false") in merged
    assert (privacy.HEADER_NAME, "true") not in merged


def test_new_ocr_headers_include_privacy_false(monkeypatch):
    from app import config as cfg
    from app.services.yandex_privacy import HEADER_NAME
    from app.services.yandex_vision_ocr import _new_ocr_headers

    monkeypatch.setattr(cfg.config, "YANDEX_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_OCR_DATA_LOGGING_ENABLED", False, raising=False)

    headers = _new_ocr_headers()
    assert headers["Authorization"].startswith("Api-Key ")
    assert "x-folder-id" not in headers
    assert headers[HEADER_NAME] == "false"


def test_openai_compat_embedding_headers_include_privacy(monkeypatch):
    from app import config as cfg
    from app.services.yandex_embedding_http import _yandex_openai_compat_http_headers
    from app.services.yandex_privacy import HEADER_NAME

    monkeypatch.setattr(cfg.config, "YANDEX_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_FOLDER_ID", "b1folder", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_GPT_MODEL_URI", "", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)

    headers = _yandex_openai_compat_http_headers()
    assert headers["x-folder-id"] == "b1folder"
    assert headers[HEADER_NAME] == "false"


@pytest.mark.parametrize(
    ("primary", "legacy", "expected"),
    [
        ("false", "true", False),
        ("true", "false", True),
        (None, "true", True),
        (None, "false", False),
        (None, None, False),
    ],
)
def test_resolve_yandex_data_logging_enabled(monkeypatch, primary, legacy, expected):
    from app import config as cfg_mod

    if primary is None:
        monkeypatch.delenv("YANDEX_DATA_LOGGING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("YANDEX_DATA_LOGGING_ENABLED", primary)

    if legacy is None:
        monkeypatch.delenv("YANDEX_OCR_DATA_LOGGING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("YANDEX_OCR_DATA_LOGGING_ENABLED", legacy)

    assert cfg_mod._resolve_yandex_data_logging_enabled() is expected
