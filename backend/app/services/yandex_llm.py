"""YandexGPT / Model Gallery (DeepSeek и др.) для LangChain через langchain-community.

Режим рассуждений (два слоя в экосистеме Yandex):

- **gRPC Foundation Models** (этот клиент): `CompletionOptions.reasoning_options` — `YANDEX_REASONING_MODE`:
  пусто = поле не передаётся; `disabled` | `enabled_hidden`. См. text_common.proto.

- **OpenAI-совместимый Completions/Responses API** (другой транспорт): реализовано в ``app.services.yandex_openai_llm``
  при ``YANDEX_LLM_TRANSPORT=openai`` (``ChatOpenAI`` + ``YANDEX_REASONING_EFFORT`` / ``reasoning_effort``).
  У DeepSeek-V3.2 рассуждения по умолчанию включены; отключение — ``reasoning_effort: "none"``.
  Для gRPC значение `YANDEX_REASONING_EFFORT=none` по-прежнему сопоставляется с `reasoning_mode=disabled`
  и лимитом выхода ~4096 (см. `default_yandex_max_tokens` в llm_factory).

**DeepSeek-V3.2** (справочно): контекст до 131 072 токенов на вход; выход — до 32 768 при рассуждениях,
до 8 192 без (часто 4096 по умолчанию). Лимит `max_tokens` под deepseek настраивается через `YANDEX_GPT_MAX_TOKENS` или авто.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, cast

from grpc import RpcError
from langchain_community.chat_models.yandex import ChatYandexGPT as LangChainChatYandexGPT
from langchain_community.llms.utils import enforce_stop_tokens
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import config
from app.services.yandex_privacy import langchain_disable_request_logging

logger = logging.getLogger(__name__)


def _parse_message(role: str, text: str) -> Dict[str, str]:
    return {"role": role, "text": text}


def _parse_chat_history(history: List[BaseMessage]) -> List[Dict[str, str]]:
    chat_history: List[Dict[str, str]] = []
    for message in history:
        content = cast(str, message.content)
        if isinstance(message, HumanMessage):
            chat_history.append(_parse_message("user", content))
        if isinstance(message, AIMessage):
            chat_history.append(_parse_message("assistant", content))
        if isinstance(message, SystemMessage):
            chat_history.append(_parse_message("system", content))
    return chat_history


def _resolve_reasoning_proto(mode: Optional[str]) -> Optional[Any]:
    """ReasoningOptions из text_common_pb2 или None (поле не задавать)."""
    if mode is None:
        return None
    m = mode.strip().lower()
    if not m:
        return None
    try:
        from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import ReasoningOptions
    except ImportError:
        logger.warning(
            "YANDEX_REASONING_MODE задан, но в установленном yandexcloud нет ReasoningOptions; "
            "обновите пакет yandexcloud."
        )
        return None
    try:
        rm = ReasoningOptions.ReasoningMode
        disabled, hidden = rm.DISABLED, rm.ENABLED_HIDDEN
    except AttributeError:
        # Значения из text_common.proto (ReasoningMode)
        disabled, hidden = 1, 2
    if m == "disabled":
        return ReasoningOptions(mode=disabled)
    if m in ("enabled_hidden", "enabled"):
        return ReasoningOptions(mode=hidden)
    logger.warning("Неизвестный YANDEX_REASONING_MODE=%r — режим рассуждений не задаётся.", mode)
    return None


def _create_retry_decorator(llm: LangChainChatYandexGPT) -> Callable[[Any], Any]:
    min_seconds = llm.sleep_interval
    max_seconds = 60
    return retry(
        reraise=True,
        stop=stop_after_attempt(llm.max_retries),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=(retry_if_exception_type((RpcError,))),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def _build_completion_options(llm: LangChainChatYandexGPT, reasoning_proto: Optional[Any]) -> Any:
    from google.protobuf.wrappers_pb2 import DoubleValue, Int64Value

    try:
        from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import CompletionOptions
    except ModuleNotFoundError:
        from yandex.cloud.ai.foundation_models.v1.foundation_models_pb2 import CompletionOptions

    opts = CompletionOptions(
        temperature=DoubleValue(value=llm.temperature),
        max_tokens=Int64Value(value=llm.max_tokens),
    )
    if reasoning_proto is not None and hasattr(opts, "reasoning_options"):
        opts.reasoning_options.CopyFrom(reasoning_proto)
    elif reasoning_proto is not None:
        logger.warning("CompletionOptions без поля reasoning_options — обновите yandexcloud.")
    return opts


def _make_request_sync(llm: LangChainChatYandexGPT, messages: List[BaseMessage], reasoning_proto: Optional[Any]) -> str:
    try:
        import grpc
    except ImportError as e:
        raise ImportError("Нужен пакет grpcio: pip install grpcio") from e

    try:
        from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import Message
        from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2 import CompletionRequest
        from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2_grpc import (
            TextGenerationServiceStub,
        )
    except ModuleNotFoundError:
        from yandex.cloud.ai.foundation_models.v1.foundation_models_pb2 import CompletionRequest, Message
        from yandex.cloud.ai.foundation_models.v1.foundation_models_service_pb2_grpc import TextGenerationServiceStub

    if not messages:
        raise ValueError("You should provide at least one message to start the chat!")
    message_history = _parse_chat_history(messages)
    channel_credentials = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(llm.url, channel_credentials)
    request = CompletionRequest(
        model_uri=llm.model_uri,
        completion_options=_build_completion_options(llm, reasoning_proto),
        messages=[Message(**message) for message in message_history],
    )
    stub = TextGenerationServiceStub(channel)
    res = stub.Completion(request, metadata=llm.grpc_metadata)
    return list(res)[0].alternatives[0].message.text


async def _make_request_async(
    llm: LangChainChatYandexGPT, messages: List[BaseMessage], reasoning_proto: Optional[Any]
) -> str:
    try:
        import grpc
    except ImportError as e:
        raise ImportError("Нужен пакет grpcio: pip install grpcio") from e

    try:
        from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import Message
        from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2 import (
            CompletionRequest,
            CompletionResponse,
        )
        from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2_grpc import (
            TextGenerationAsyncServiceStub,
        )
    except ModuleNotFoundError:
        from yandex.cloud.ai.foundation_models.v1.foundation_models_pb2 import CompletionRequest, CompletionResponse, Message
        from yandex.cloud.ai.foundation_models.v1.foundation_models_service_pb2_grpc import TextGenerationAsyncServiceStub

    from yandex.cloud.operation.operation_service_pb2 import GetOperationRequest
    from yandex.cloud.operation.operation_service_pb2_grpc import OperationServiceStub

    if not messages:
        raise ValueError("You should provide at least one message to start the chat!")
    message_history = _parse_chat_history(messages)
    operation_api_url = "operation.api.cloud.yandex.net:443"
    channel_credentials = grpc.ssl_channel_credentials()
    async with grpc.aio.secure_channel(llm.url, channel_credentials) as channel:
        request = CompletionRequest(
            model_uri=llm.model_uri,
            completion_options=_build_completion_options(llm, reasoning_proto),
            messages=[Message(**message) for message in message_history],
        )
        stub = TextGenerationAsyncServiceStub(channel)
        operation = await stub.Completion(request, metadata=llm.grpc_metadata)
        async with grpc.aio.secure_channel(operation_api_url, channel_credentials) as operation_channel:
            operation_stub = OperationServiceStub(operation_channel)
            while not operation.done:
                await asyncio.sleep(1)
                operation_request = GetOperationRequest(operation_id=operation.id)
                operation = await operation_stub.Get(operation_request, metadata=llm.grpc_metadata)

            completion_response = CompletionResponse()
            operation.response.Unpack(completion_response)
            return completion_response.alternatives[0].message.text


def _completion_with_retry_sync(llm: LangChainChatYandexGPT, reasoning_proto: Optional[Any], **kwargs: Any) -> Any:
    retry_decorator = _create_retry_decorator(llm)

    @retry_decorator
    def _inner(**_kwargs: Any) -> Any:
        return _make_request_sync(llm, _kwargs["messages"], reasoning_proto)

    return _inner(**kwargs)


async def _completion_with_retry_async(llm: LangChainChatYandexGPT, reasoning_proto: Optional[Any], **kwargs: Any) -> Any:
    retry_decorator = _create_retry_decorator(llm)

    @retry_decorator
    async def _inner(**_kwargs: Any) -> Any:
        return await _make_request_async(llm, _kwargs["messages"], reasoning_proto)

    return await _inner(**kwargs)


class ChatYandexGPT(LangChainChatYandexGPT):
    """
    Обёртка над ChatYandexGPT: ключи и URI из config.
    Если задан YANDEX_GPT_MODEL_URI (например gpt://.../deepseek-v32/latest), он уходит в API как есть.

    Режим рассуждений: переменная YANDEX_REASONING_MODE или аргумент reasoning_mode:
    пусто — поле не передаётся (поведение API по умолчанию);
    disabled — явно DISABLED;
    enabled_hidden или enabled — ENABLED_HIDDEN (поддерживается для моделей с reasoning_options, напр. YandexGPT Pro).
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        model_uri: Optional[str] = None,
        temperature: float = 0.1,
        reasoning_mode: Optional[str] = None,
        **kwargs: Any,
    ):
        kwargs = dict(kwargs)
        if reasoning_mode is None:
            reasoning_mode = kwargs.pop("reasoning_mode", None)
        else:
            kwargs.pop("reasoning_mode", None)

        api_key = api_key or config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN
        folder_id = (folder_id if folder_id is not None else config.YANDEX_FOLDER_ID) or ""
        folder_id = folder_id.strip()
        uri = (model_uri or config.YANDEX_GPT_MODEL_URI or "").strip()

        if not api_key:
            logger.warning("YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. Yandex LLM will not work.")

        init_kwargs: dict[str, Any] = {"temperature": temperature, **kwargs}
        if api_key:
            init_kwargs["api_key"] = api_key

        if uri:
            init_kwargs["model_uri"] = uri
            if folder_id:
                init_kwargs["folder_id"] = folder_id
        else:
            if not folder_id:
                logger.warning("YANDEX_FOLDER_ID not set and no YANDEX_GPT_MODEL_URI — specify one of them.")
            init_kwargs["folder_id"] = folder_id
            model_name = model or config.YANDEX_GPT_MODEL or "yandexgpt-lite"
            if "/" in model_name:
                model_name = model_name.split("/")[0]
            init_kwargs["model_name"] = model_name

        # LangChain maps disable_request_logging=True → x-data-logging-enabled: false.
        if "disable_request_logging" not in init_kwargs:
            init_kwargs["disable_request_logging"] = langchain_disable_request_logging()

        super().__init__(**init_kwargs)

        mode_raw = reasoning_mode if reasoning_mode is not None else config.YANDEX_REASONING_MODE
        if not str(mode_raw or "").strip():
            effort = getattr(config, "YANDEX_REASONING_EFFORT", "") or ""
            if effort.strip().lower() == "none":
                mode_raw = "disabled"
        self._reasoning_options_proto = _resolve_reasoning_proto(mode_raw)
        if self._reasoning_options_proto is not None:
            logger.info("Yandex CompletionOptions: reasoning_options задан (mode=%r)", mode_raw)

        log_ref = uri or init_kwargs.get("model_name", "yandexgpt")
        fd = folder_id or "—"
        logger.info("✅ ChatYandexGPT: model_uri/model=%s, folder=%s…", log_ref, fd[:8])

    def is_available(self) -> bool:
        return bool(self.api_key and (self.model_uri or self.folder_id))

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = _completion_with_retry_sync(self, self._reasoning_options_proto, messages=messages)
        text = text if stop is None else enforce_stop_tokens(text, stop)
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = await _completion_with_retry_async(self, self._reasoning_options_proto, messages=messages)
        text = text if stop is None else enforce_stop_tokens(text, stop)
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])
