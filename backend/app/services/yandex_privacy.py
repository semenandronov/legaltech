"""Yandex Cloud / AI Studio server-side request logging policy.

Official opt-out (Foundation Models, Vision OCR, embeddings, ML SDK):
https://yandex.cloud/docs/foundation-models/operations/disable-logging

When logging is disabled, every outbound call must carry::

    x-data-logging-enabled: false

(as an HTTP header or gRPC metadata). Yandex then does not retain request
payloads on its servers for quality control / model improvement.

Legaltech default: logging **disabled** (``YANDEX_DATA_LOGGING_ENABLED=false``).
"""

from __future__ import annotations

from typing import Mapping, MutableMapping, Optional, Sequence

HEADER_NAME = "x-data-logging-enabled"


def server_data_logging_enabled() -> bool:
    """Whether Yandex may log request/response payloads server-side."""
    from app.config import config

    return bool(getattr(config, "YANDEX_DATA_LOGGING_ENABLED", False))


def data_logging_header_value() -> str:
    """Wire value for ``x-data-logging-enabled`` (``\"true\"`` / ``\"false\"``)."""
    return "true" if server_data_logging_enabled() else "false"


def data_logging_http_headers() -> dict[str, str]:
    """Minimal header dict to merge into Yandex HTTP clients."""
    return {HEADER_NAME: data_logging_header_value()}


def apply_data_logging_headers(
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """
    Return a new header map with the privacy header always set.

    Call sites must not invent their own ``x-data-logging-enabled`` value —
    this is the single writer for that key.
    """
    out: dict[str, str] = dict(headers or {})
    out[HEADER_NAME] = data_logging_header_value()
    return out


def ensure_data_logging_header(headers: MutableMapping[str, str]) -> None:
    """In-place set of the privacy header on an existing mutable mapping."""
    headers[HEADER_NAME] = data_logging_header_value()


def data_logging_grpc_metadata() -> tuple[tuple[str, str], ...]:
    """gRPC metadata pairs for Foundation Models Completions."""
    return ((HEADER_NAME, data_logging_header_value()),)


def langchain_disable_request_logging() -> bool:
    """
    LangChain ``ChatYandexGPT.disable_request_logging``.

    ``True`` means the client appends ``x-data-logging-enabled: false``.
    """
    return not server_data_logging_enabled()


def ycloud_ml_enable_server_data_logging() -> bool:
    """
    Value for ``YCloudML(enable_server_data_logging=...)``.

    The ML SDK documents that a bool adds ``x-data-logging-enabled`` to all
    requests for backends that support the option.
    """
    return server_data_logging_enabled()


def merge_grpc_metadata(
    base: Optional[Sequence[tuple[str, str]]] = None,
) -> list[tuple[str, str]]:
    """
    Merge privacy metadata into existing gRPC metadata.

    Replaces any prior ``x-data-logging-enabled`` entry so the policy cannot
    be overridden by stale tuples.
    """
    merged: list[tuple[str, str]] = []
    for key, value in base or ():
        if str(key).lower() == HEADER_NAME:
            continue
        merged.append((key, value))
    merged.append((HEADER_NAME, data_logging_header_value()))
    return merged
