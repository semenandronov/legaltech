"""Tests for legal-data confidentiality controls."""

from __future__ import annotations


def test_redact_observability_strips_question(monkeypatch):
    from app import config as cfg
    from app.security.sensitive_data import redact_observability_value

    monkeypatch.setattr(cfg.config, "LANGFUSE_CAPTURE_CONTENT", False, raising=False)

    payload = {
        "case_id": "c1",
        "question": "Секретный договор займа на 10 млн",
        "latency_ms": 12,
    }
    redacted = redact_observability_value(payload)
    assert redacted["case_id"] == "c1"
    assert redacted["latency_ms"] == 12
    assert redacted["question"]["redacted"] is True
    assert "Секретный" not in str(redacted)


def test_redact_observability_passthrough_when_capture_on(monkeypatch):
    from app import config as cfg
    from app.security.sensitive_data import redact_observability_value

    monkeypatch.setattr(cfg.config, "LANGFUSE_CAPTURE_CONTENT", True, raising=False)

    payload = {"question": "keep me"}
    assert redact_observability_value(payload)["question"] == "keep me"


def test_langfuse_safe_event_payload_redacts(monkeypatch):
    from app import config as cfg
    from app.services.observability import langfuse_service as lf

    monkeypatch.setattr(cfg.config, "LANGFUSE_CAPTURE_CONTENT", False, raising=False)

    safe = lf._safe_event_payload({"question": "тайна клиента", "route": "/api/v2/assistant/chat"})
    assert safe["route"] == "/api/v2/assistant/chat"
    assert "тайна" not in str(safe)


def test_get_langchain_callbacks_empty_without_capture(monkeypatch):
    from app import config as cfg
    from app.services.observability import langfuse_service as lf

    monkeypatch.setattr(cfg.config, "LANGFUSE_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg.config, "LANGFUSE_PUBLIC_KEY", "pk", raising=False)
    monkeypatch.setattr(cfg.config, "LANGFUSE_SECRET_KEY", "sk", raising=False)
    monkeypatch.setattr(cfg.config, "LANGFUSE_CAPTURE_CONTENT", False, raising=False)

    assert lf.get_langchain_callbacks(user_id="u1") == []


def test_production_security_rejects_yandex_logging(monkeypatch):
    from app import config as cfg_mod

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(cfg_mod.config, "JWT_SECRET_KEY", "x" * 40, raising=False)
    monkeypatch.setattr(cfg_mod.config, "JWT_ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(cfg_mod.config, "CORS_ORIGINS", ["https://app.example.com"], raising=False)
    monkeypatch.setattr(cfg_mod.config, "YANDEX_DATA_LOGGING_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg_mod.config, "AGENT_DEBUG_FILE_LOG", False, raising=False)
    monkeypatch.setattr(cfg_mod.config, "LANGFUSE_ENABLED", False, raising=False)
    monkeypatch.setattr(cfg_mod.config, "LANGFUSE_CAPTURE_CONTENT", False, raising=False)
    monkeypatch.setattr(cfg_mod.config, "GIGACHAT_VERIFY_SSL", True, raising=False)
    monkeypatch.setattr(cfg_mod.config, "TABULAR_ONLY_MODE", True, raising=False)

    try:
        cfg_mod.validate_production_security()
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "YANDEX_DATA_LOGGING" in str(exc)
    assert raised
