"""Yandex Foundation Models через OpenAI-совместимый HTTPS (ai.api.cloud.yandex.net/v1).

Используется при ``YANDEX_LLM_TRANSPORT=openai``. Для LangChain — ``ChatOpenAI`` (chat.completions),
как и у остального приложения (bind_tools / ReAct).

Сырые вызовы OpenAI SDK (в т.ч. ``responses.create``) — см. ``yandex_openai_sdk_client``."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.config import config
from app.services.yandex_privacy import apply_data_logging_headers

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://ai.api.cloud.yandex.net/v1"


def resolve_yandex_folder_id() -> str:
    """``YANDEX_FOLDER_ID`` или первый сегмент после ``gpt://`` в ``YANDEX_GPT_MODEL_URI``."""
    fd = (config.YANDEX_FOLDER_ID or "").strip()
    if fd:
        return fd
    uri = (config.YANDEX_GPT_MODEL_URI or "").strip()
    if uri.startswith("gpt://"):
        rest = uri[6:]
        return rest.split("/", 1)[0] if rest else ""
    return ""


def yandex_openai_sdk_client():
    """
    Клиент OpenAI Python SDK для эндпоинта Yandex (как в консоли AI Studio).

    ``project`` — идентификатор каталога (folder id); для части сценариев также используют
    заголовок ``x-folder-id`` (см. ``create_yandex_chat_openai_llm``).
    """
    from openai import OpenAI

    api_key = (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN or "").strip()
    if not api_key:
        raise ValueError("Yandex OpenAI: задайте YANDEX_API_KEY или YANDEX_IAM_TOKEN.")

    folder = resolve_yandex_folder_id()
    if not folder:
        raise ValueError(
            "Yandex OpenAI: задайте YANDEX_FOLDER_ID или URI вида gpt://<folder-id>/model/latest."
        )

    base_url = (getattr(config, "YANDEX_OPENAI_COMPAT_BASE_URL", None) or _DEFAULT_BASE_URL).strip()
    # Yandex OpenAI-compat layer requires folder in header.
    # Keep `project` for compatibility, but `x-folder-id` is the critical piece.
    # Privacy: always set x-data-logging-enabled from the global policy.
    default_headers = apply_data_logging_headers({"x-folder-id": folder})
    try:
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            project=folder,
            default_headers=default_headers,
        )
    except TypeError:
        # Older OpenAI SDK: no default_headers in constructor.
        # Fall back to project-only; embeddings may still fail without the header.
        logger.warning(
            "OpenAI SDK without default_headers support; "
            "x-data-logging-enabled / x-folder-id may be missing on raw SDK calls"
        )
        return OpenAI(api_key=api_key, base_url=base_url, project=folder)


def _openai_reasoning_effort() -> Optional[str]:
    """Сопоставление env с полем ``reasoning_effort`` в Completions API."""
    e = (getattr(config, "YANDEX_REASONING_EFFORT", "") or "").strip().lower()
    if e in ("none", "low", "medium", "high"):
        return e
    rm = (getattr(config, "YANDEX_REASONING_MODE", "") or "").strip().lower()
    if rm == "disabled":
        return "none"
    return None


def create_yandex_chat_openai_llm(
    temperature: float = 0.1,
    model: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """
    ``langchain_openai.ChatOpenAI`` к ``https://ai.api.cloud.yandex.net/v1`` с каталогом в заголовке.

    ``model`` — полный URI (``gpt://.../deepseek-v32/latest``), иначе берётся из ``YANDEX_GPT_MODEL_URI``.
    """
    from app.services.chat_yandex_openai import ChatYandexOpenAI

    api_key = (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN or "").strip()
    if not api_key:
        raise ValueError("Yandex OpenAI: задайте YANDEX_API_KEY или YANDEX_IAM_TOKEN.")

    folder = resolve_yandex_folder_id()
    if not folder:
        raise ValueError(
            "Yandex OpenAI: задайте YANDEX_FOLDER_ID или URI вида gpt://<folder-id>/model/latest."
        )

    model_id = (model or "").strip() or (config.YANDEX_GPT_MODEL_URI or "").strip()
    if not model_id:
        raise ValueError("Yandex OpenAI: задайте YANDEX_GPT_MODEL_URI или model=…")

    base_url = (getattr(config, "YANDEX_OPENAI_COMPAT_BASE_URL", None) or _DEFAULT_BASE_URL).strip()

    kw = dict(kwargs)
    timeout = kw.pop("timeout", None)

    model_kwargs: Dict[str, Any] = dict(kw.pop("model_kwargs", {}) or {})
    rm_kw = kw.pop("reasoning_mode", None)
    effort = _openai_reasoning_effort()
    if effort:
        model_kwargs.setdefault("reasoning_effort", effort)
    if rm_kw:
        m = str(rm_kw).strip().lower()
        if m == "disabled":
            model_kwargs["reasoning_effort"] = "none"
        elif m in ("enabled_hidden", "enabled"):
            model_kwargs["reasoning_effort"] = "high"

    init: Dict[str, Any] = {
        "model": model_id,
        "openai_api_key": api_key,
        "openai_api_base": base_url,
        "default_headers": apply_data_logging_headers({"x-folder-id": folder}),
        "temperature": temperature,
        "model_kwargs": model_kwargs,
        **kw,
    }
    if timeout is not None:
        init["timeout"] = timeout

    llm = ChatYandexOpenAI(**init)
    logger.info(
        "Yandex LLM (OpenAI transport): model=%s base_url=%s folder=%s…",
        model_id[:64],
        base_url,
        folder[:8],
    )
    return llm


def yandex_responses_create(
    *,
    user_input: str,
    instructions: str = "",
    temperature: float = 0.3,
    max_output_tokens: int = 500,
    model: Optional[str] = None,
):
    """
    Прямой вызов ``client.responses.create`` (как в примере из AI Studio).

    Не используется агентами LangChain; удобно для проверки ключа и URI модели.
    """
    client = yandex_openai_sdk_client()
    model_id = (model or "").strip() or (config.YANDEX_GPT_MODEL_URI or "").strip()
    if not model_id:
        raise ValueError("yandex_responses_create: задайте model или YANDEX_GPT_MODEL_URI.")

    return client.responses.create(
        model=model_id,
        temperature=temperature,
        instructions=instructions,
        input=user_input,
        max_output_tokens=max_output_tokens,
    )
