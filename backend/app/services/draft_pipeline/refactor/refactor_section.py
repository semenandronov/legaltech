"""Qwen refactor: rewrite a single section preserving user-filled values."""
from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def refactor_section_text(
    *,
    section_title: str,
    current_section_html: str,
    user_prompt: str,
    document_context: str,
) -> str:
    llm = create_legal_llm(
        provider="yandex",
        model=config.YANDEX_GPT_MODEL_URI,
        use_rate_limiting=False,
        temperature=0.15,
        streaming=False,
    )
    prompt = f"""Перед тобой текущий текст раздела «{section_title}»:
\"\"\"
{current_section_html}
\"\"\"

Полный документ (контекст, фрагмент):
\"\"\"
{(document_context or "")[:6000]}
\"\"\"

Юрист дал команду:
{user_prompt}

Перепиши ТОЛЬКО этот раздел. Измени только то, о чём просит юрист.
Данные, которые юрист уже заполнил вместо маркеров [поле], оставь без изменений.
Не возвращай старые маркеры, если юрист их стёр.
Верни HTML-фрагмент раздела (можно с <section>…</section>), без markdown."""

    resp = llm.invoke([HumanMessage(content=prompt)])
    raw = resp.content if hasattr(resp, "content") else str(resp)
    text = raw.strip()
    text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    logger.info("[draft_pipeline.refactor] section=%s chars=%s", section_title, len(text))
    return text
