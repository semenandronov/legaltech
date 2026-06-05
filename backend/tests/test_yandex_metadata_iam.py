"""Тесты IAM metadata для вызова worker."""
from app.config import config
from app.services.yandex_metadata_iam import resolve_worker_invoke_iam_token


def test_resolve_prefers_metadata(monkeypatch):
    monkeypatch.setattr(config, "WORKER_DISPATCH_USE_METADATA_IAM", True, raising=False)
    monkeypatch.setattr(config, "YANDEX_IAM_TOKEN", "static-token", raising=False)
    monkeypatch.setattr(
        "app.services.yandex_metadata_iam.fetch_sa_iam_token_from_metadata",
        lambda timeout_sec=2.0: "metadata-token",
    )
    assert resolve_worker_invoke_iam_token() == "metadata-token"


def test_resolve_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(config, "WORKER_DISPATCH_USE_METADATA_IAM", True, raising=False)
    monkeypatch.setattr(config, "YANDEX_IAM_TOKEN", "static-token", raising=False)
    monkeypatch.setattr(
        "app.services.yandex_metadata_iam.fetch_sa_iam_token_from_metadata",
        lambda timeout_sec=2.0: None,
    )
    assert resolve_worker_invoke_iam_token() == "static-token"
