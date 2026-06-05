#!/usr/bin/env python3
"""Замер latency Yandex LLM (те же ключи/модели, что у case assistant)."""
from __future__ import annotations

import os
import sys
import time

# backend root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.llm_factory import create_llm


def _mask(s: str) -> str:
    if not s or len(s) < 8:
        return "(not set)"
    return s[:4] + "…" + s[-4:]


def timed_invoke(label: str, llm, messages) -> tuple[float, int]:
    t0 = time.perf_counter()
    resp = llm.invoke(messages)
    wall = time.perf_counter() - t0
    text = getattr(resp, "content", None) or str(resp)
    return wall, len(text or "")


def main() -> None:
    print("=== Yandex LLM latency benchmark ===\n")
    print(f"LLM_PROVIDER: {config.LLM_PROVIDER}")
    print(f"YANDEX_GPT_MODEL_URI: {config.YANDEX_GPT_MODEL_URI or '(empty)'}")
    print(f"YANDEX_GPT_MODEL: {config.YANDEX_GPT_MODEL}")
    print(f"YANDEX_FOLDER_ID: {_mask(config.YANDEX_FOLDER_ID or '')}")
    print(f"API key set: {bool(config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN)}")
    print(f"Transport: {getattr(config, 'YANDEX_LLM_TRANSPORT', 'grpc')}")
    print()

    if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
        print("ERROR: нет YANDEX_API_KEY / YANDEX_IAM_TOKEN в .env")
        sys.exit(1)

    short_q = "О чем этот документ? Ответь в 3 предложениях на русском."
    short_msgs = [
        SystemMessage(content="Ты юрист. Отвечай кратко."),
        HumanMessage(content=short_q),
    ]

    # 1) Lite — как router
    try:
        lite = create_llm(
            model="yandexgpt-lite/latest",
            temperature=0.0,
            max_tokens=256,
            use_rate_limiting=False,
            cache_enabled=False,
        )
        w, chars = timed_invoke("yandexgpt-lite", lite, short_msgs)
        print(f"[1] yandexgpt-lite/latest     {w:.2f}s   chars={chars}")
    except Exception as e:
        print(f"[1] yandexgpt-lite FAILED: {e}")

    # 2) Основная модель из URI (как generate_response)
    main_uri = (config.YANDEX_GPT_MODEL_URI or "").strip()
    if main_uri:
        try:
            main_llm = create_llm(
                model=main_uri,
                temperature=0.1,
                max_tokens=1024,
                use_rate_limiting=False,
                cache_enabled=False,
            )
            w, chars = timed_invoke(main_uri, main_llm, short_msgs)
            print(f"[2] main URI (short)          {w:.2f}s   chars={chars}")
        except Exception as e:
            print(f"[2] main URI FAILED: {e}")
    else:
        print("[2] YANDEX_GPT_MODEL_URI не задан — пропуск")

    # 3) Симуляция case chat: 6 фрагментов × ~1200 символов + structured-style prompt
    rag_context = "\n\n".join(
        f"[{i}] doc.pdf, стр. {i}:\n"
        + ("Текст фрагмента о возражениях кредиторов и реализации активов. " * 40)[:1200]
        for i in range(1, 7)
    )
    heavy_msgs = [
        SystemMessage(
            content=(
                "Ты эксперт-юрист. В ответе используй только ссылки [1]–[6] после тезисов."
            )
        ),
        HumanMessage(
            content=f"""ИСТОЧНИКИ:
{rag_context}

ВОПРОС: о чем документы?

Дай ответ на русском со ссылками [N]."""
        ),
    ]
    if main_uri:
        try:
            main_llm2 = create_llm(
                model=main_uri,
                temperature=0.1,
                max_tokens=2048,
                use_rate_limiting=False,
                cache_enabled=False,
            )
            w, chars = timed_invoke("main URI + RAG-like ctx", main_llm2, heavy_msgs)
            ctx_chars = len(rag_context)
            print(
                f"[3] main URI + ~6 chunks      {w:.2f}s   chars={chars}  prompt_ctx≈{ctx_chars}"
            )
        except Exception as e:
            print(f"[3] heavy prompt FAILED: {e}")

    # 4) Прямой OpenAI-compat (если transport=openai)
    transport = (getattr(config, "YANDEX_LLM_TRANSPORT", None) or "grpc").strip().lower()
    if transport == "openai":
        print("\n(OpenAI transport — вызовы выше уже через OpenAI-compat)")
    else:
        print(f"\nTransport={transport} (gRPC). Для OpenAI-compat: YANDEX_LLM_TRANSPORT=openai")

    print("\nГотово.")


if __name__ == "__main__":
    main()
