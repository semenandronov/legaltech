"""Basic Langfuse setup tests."""

from app.config import config
from app.services.observability import langfuse_service


def test_langfuse_config_fields_exist():
    assert hasattr(config, "LANGFUSE_ENABLED")
    assert hasattr(config, "LANGFUSE_PUBLIC_KEY")
    assert hasattr(config, "LANGFUSE_SECRET_KEY")
    assert hasattr(config, "LANGFUSE_HOST")
    assert hasattr(config, "LANGFUSE_SAMPLE_RATE")


def test_langfuse_init_does_not_crash():
    # Must never crash app startup even if keys are missing.
    result = langfuse_service.init_langfuse()
    assert isinstance(result, bool)


def test_prompt_fallback_without_client():
    text = langfuse_service.get_prompt_text(
        prompt_name="missing_prompt",
        fallback="fallback-text",
        variables={"x": 1},
    )
    assert text == "fallback-text"
