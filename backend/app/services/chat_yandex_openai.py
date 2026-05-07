"""Подкласс ChatOpenAI для Yandex OpenAI-совместимого API: сохранение полей рассуждений.

В ``langchain_openai`` до версии с полной поддержкой провайдеров поля
``reasoning_content`` / ``reasoning`` из ответа **не копируются** в ``AIMessage``
(см. комментарии в ``base.py``). Yandex DeepSeek может возвращать их в ``message`` и в
стриминговых ``delta`` — здесь они переносятся в ``additional_kwargs``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

_REASON_KEYS = ("reasoning_content", "reasoning", "thinking")


def _merge_reasoning_dict(target: dict, source: Mapping[str, Any]) -> None:
    for key in _REASON_KEYS:
        if key not in source:
            continue
        val = source[key]
        if val is None or val == "":
            continue
        if isinstance(val, (dict, list)):
            target[key] = json.dumps(val, ensure_ascii=False)
        else:
            target[key] = val


def _raw_assistant_message_dict(response: Any) -> dict[str, Any]:
    """Извлечь сырой ``message`` первого choice (dict или pydantic)."""
    try:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if not choices:
                return {}
            msg = choices[0].get("message")
            return dict(msg) if isinstance(msg, dict) else {}

        choices = getattr(response, "choices", None) or []
        if not choices:
            return {}
        message = choices[0].message
        out: dict[str, Any] = {}
        if hasattr(message, "model_dump"):
            out.update(message.model_dump(exclude_unset=False))
        for key in _REASON_KEYS:
            if hasattr(message, key):
                v = getattr(message, key)
                if v is not None:
                    out[key] = v
        extras = getattr(message, "model_extra", None)
        if isinstance(extras, dict):
            for key in _REASON_KEYS:
                if key in extras and extras[key] is not None:
                    out[key] = extras[key]
        return out
    except Exception as ex:
        logger.debug("chat_yandex_openai: raw message parse: %s", ex)
        return {}


class ChatYandexOpenAI(ChatOpenAI):
    """ChatOpenAI + проброс рассуждений Yandex/DeepSeek в ``additional_kwargs``."""

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):  # type: ignore[override]
        result = super()._create_chat_result(response, generation_info)
        raw = _raw_assistant_message_dict(response)
        if not raw or not result.generations:
            return result
        msg = result.generations[0].message
        if not isinstance(msg, AIMessage):
            return result
        ak = dict(msg.additional_kwargs or {})
        _merge_reasoning_dict(ak, raw)
        msg.additional_kwargs = ak
        return result

    def _convert_chunk_to_generation_chunk(  # type: ignore[override]
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):
        gen = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen is None:
            return None
        if not isinstance(gen.message, AIMessageChunk):
            return gen

        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return gen
        delta = choices[0].get("delta") or {}
        if not isinstance(delta, dict):
            return gen

        ak = dict(gen.message.additional_kwargs or {})
        for key in _REASON_KEYS:
            if key in delta and delta[key] is not None:
                piece = delta[key]
                prev = ak.get(key)
                if isinstance(piece, str) and isinstance(prev, str):
                    ak[key] = prev + piece
                else:
                    ak[key] = piece
        gen.message.additional_kwargs = ak
        return gen
