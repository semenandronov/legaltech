"""
Улучшение текста запроса пользователя (не «сборка промпта для модели»):

ассистент уже получает системные инструкции; здесь только яснее и структурнее
сформулировать то, что пользователь хочет получить — в духе ясности и конкретики
(Anthropic / исследовательские практики), без лишнего мета-языка.

Выход: один улучшенный текст запроса на русском, без обрамляющего комментария.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.llm_factory import create_llm, default_yandex_max_tokens

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 24_000

_SYSTEM_PROMPT = """Ты помогаешь отредактировать текст вопроса или задания, который пользователь вводит в чат с юридическим ассистентом.

Важно:
- Системные инструкции для модели уже заданы отдельно. Тебе НЕ нужно составлять «промпт для LLM», давать роль модели («Ты — …»), писать мета-инструкции в духе «следуй правилам» или «верни ответ в формате…» как отдельный слой — только то, что пользователь сам хотел спросить или поручить, но яснее и полнее.
- Результат должен звучать как улучшенная формулировка запроса пользователя своими словами (можно чуть официальнее), а не как шаблон для разработчика.

Что сделать с черновиком:
1) Сохрани смысл, тон и цель: не меняй тему и не добавляй новых фактов, которых не было (даты, номера дел, имена — только если пользователь их указал или явно просит обобщить).
2) Убери двусмысленность: что именно нужно в ответе (анализ, список шагов, сравнение, черновик текста и т.д.).
3) При необходимости структурируй: короткие абзацы или маркированный список (контекст → вопрос → пожелания к ответу), без избыточных заголовков вроде «Роль», «Критерии успеха», если это не помогает самому запросу.
4) Юридические темы: можно кратко напомнить в тексте запроса опору на факты/документы и не выдумывать реквизиты — как часть формулировки вопроса, а не как системный промпт.
5) Если исходный текст очень короткий — добавь только уместные уточняющие формулировки (что важно учесть), не раздувай.

Запрещено:
- Выдавать ответ ассистента на вопрос пользователя — только переписанный запрос.
- Начинать с «Вот улучшенный промпт», «Инструкция для модели:» и т.п.

Формат вывода:
- Только улучшенный текст запроса на русском языке, без markdown-ограждений и без преамбулы."""


def _strip_code_fences(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def improve_user_prompt_sync(draft: str) -> str:
    raw = (draft or "").strip()
    if not raw:
        return ""
    if len(raw) > _MAX_INPUT_CHARS:
        raw = raw[:_MAX_INPUT_CHARS]

    llm = create_llm(
        provider="yandex",
        model=config.YANDEX_GPT_MODEL_URI,
        temperature=0.2,
        use_rate_limiting=True,
        max_tokens=min(4096, default_yandex_max_tokens()),
    )

    human = HumanMessage(
        content=(
            "Черновик текста пользователя — улучши только формулировку (содержание задания то же):\n\n"
            f"<user_draft>\n{raw}\n</user_draft>"
        )
    )

    try:
        resp = llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), human])
        out = getattr(resp, "content", None) or str(resp)
        if isinstance(out, list):
            parts = []
            for block in out:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            out = "".join(parts)
        out = _strip_code_fences(str(out).strip())
        out = re.sub(
            r"^\s*(улучшенн(ый|ая)\s+промпт|улучшенная\s+формулировка|инструкция\s+для\s+модели|вот\s+улучшенн)[^.:\n]*[.:\n]\s*",
            "",
            out,
            flags=re.IGNORECASE,
        )
        return out.strip() if out.strip() else raw
    except Exception as e:
        logger.warning("improve_user_prompt_sync failed: %s", e, exc_info=True)
        raise
