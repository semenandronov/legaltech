"""Тесты internal worker endpoint."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.worker_app import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_WORKER_SECRET", "test-secret", raising=False)
    return TestClient(app)


def test_process_files_requires_secret(client):
    resp = client.post(
        "/internal/process-files",
        json={"file_ids": ["f1"], "case_id": "case-1"},
    )
    assert resp.status_code == 401


def test_process_files_accepts_job(client):
    with patch("app.routes.internal_worker.asyncio.create_task") as mock_task:
        resp = client.post(
            "/internal/process-files",
            json={"file_ids": ["f1", "f2"], "case_id": "case-1"},
            headers={"X-Internal-Worker-Secret": "test-secret"},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["file_ids"] == ["f1", "f2"]
    assert data["case_id"] == "case-1"
    mock_task.assert_called_once()
