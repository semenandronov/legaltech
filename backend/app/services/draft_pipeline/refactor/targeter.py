"""Section Targeter: map user edit command to blueprint section_id."""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.schemas import BlueprintSection
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

_KEYWORD_MAP = {
    "просительн": "prayer",
    "просим": "prayer",
    "обстоятельств": "facts",
    "фабул": "facts",
    "шапк": "header",
    "реквизит": "header",
    "правов": "legal",
    "мотив": "legal",
    "приложен": "attachments",
}


def _keyword_target(user_prompt: str, blueprint: List[BlueprintSection]) -> Optional[str]:
    q = (user_prompt or "").lower()
    ids = {s.section_id for s in blueprint}
    for needle, sid in _KEYWORD_MAP.items():
        if needle in q and sid in ids:
            return sid
    for spec in blueprint:
        if spec.title.lower() in q:
            return spec.section_id
    return None


def target_section_id(
    *,
    user_prompt: str,
    blueprint: List[BlueprintSection],
    document_context: str,
) -> Optional[str]:
    """Return section_id to refactor, or None if targeting failed."""
    kw = _keyword_target(user_prompt, blueprint)
    if kw:
        return kw

    if not blueprint:
        return None

    catalog = "\n".join(
        f"- id={s.section_id} | title={s.title}" for s in blueprint
    )
    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        prompt = f"""Определи, к какому разделу документа относится команда юриста.

РАЗДЕЛЫ:
{catalog}

КОМАНДА:
{user_prompt}

ФРАГМЕНТ ДОКУМЕНТА (начало):
{(document_context or "")[:2500]}

Ответь СТРОГО JSON: {{"section_id": "<id из списка или null>"}}"""
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group(0))
            sid = (data.get("section_id") or "").strip()
            allowed = {s.section_id for s in blueprint}
            if sid in allowed:
                return sid
    except Exception as exc:
        logger.warning("[draft_pipeline.targeter] LLM failed: %s", exc)

    return blueprint[0].section_id if blueprint else None
