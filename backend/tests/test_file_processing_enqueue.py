"""Тесты dispatch API → worker."""
import pytest

from app.config import config
from app.services import file_processing_enqueue as fpe


@pytest.fixture(autouse=True)
def _reset_worker_config(monkeypatch):
    monkeypatch.setattr(config, "APP_ROLE", "api", raising=False)
    monkeypatch.setattr(config, "WORKER_BASE_URL", "", raising=False)
    monkeypatch.setattr(config, "INTERNAL_WORKER_SECRET", "", raising=False)
    monkeypatch.setattr(config, "FILE_PROCESSING_MODE", "auto", raising=False)


def test_file_processing_via_worker_auto_requires_url_and_secret():
    config.WORKER_BASE_URL = ""
    config.INTERNAL_WORKER_SECRET = "secret"
    assert config.file_processing_via_worker() is False

    config.WORKER_BASE_URL = "https://worker.example"
    config.INTERNAL_WORKER_SECRET = ""
    assert config.file_processing_via_worker() is False

    config.INTERNAL_WORKER_SECRET = "secret"
    assert config.file_processing_via_worker() is True


def test_file_processing_local_mode():
    config.WORKER_BASE_URL = "https://worker.example"
    config.INTERNAL_WORKER_SECRET = "secret"
    config.FILE_PROCESSING_MODE = "local"
    assert config.file_processing_via_worker() is False


def test_worker_role_never_dispatches():
    config.APP_ROLE = "worker"
    config.WORKER_BASE_URL = "https://worker.example"
    config.INTERNAL_WORKER_SECRET = "secret"
    assert config.file_processing_via_worker() is False


@pytest.mark.asyncio
async def test_dispatch_files_to_worker_success(monkeypatch):
    config.WORKER_BASE_URL = "https://worker.test"
    config.INTERNAL_WORKER_SECRET = "s3cr3t"

    class _Resp:
        status_code = 202
        text = "ok"

    def _fake_post(url, json, headers, timeout):
        assert url == "https://worker.test/internal/process-files"
        assert json == {"file_ids": ["f1"], "case_id": "case-1"}
        assert headers["X-Internal-Worker-Secret"] == "s3cr3t"
        assert headers["Authorization"] == "Bearer test-iam-token"
        return _Resp()

    monkeypatch.setattr(
        "app.services.file_processing_enqueue.resolve_worker_invoke_iam_token",
        lambda: "test-iam-token",
    )
    monkeypatch.setattr("requests.post", _fake_post)
    ok = await fpe.dispatch_files_to_worker(["f1"], "case-1")
    assert ok is True


@pytest.mark.asyncio
async def test_dispatch_files_to_worker_failure(monkeypatch):
    config.WORKER_BASE_URL = "https://worker.test"
    config.INTERNAL_WORKER_SECRET = "s3cr3t"

    def _boom(*_a, **_k):
        raise ConnectionError("network down")

    monkeypatch.setattr("requests.post", _boom)
    ok = await fpe.dispatch_files_to_worker(["f1"], "case-1")
    assert ok is False
