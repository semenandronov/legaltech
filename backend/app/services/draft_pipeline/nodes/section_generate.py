"""Node 3: generate one section — state-only (Layer 4, no raw document RAG)."""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.legal_context import retrieve_legal_reference_context
from app.services.draft_pipeline.markers import gap_marker
from app.services.draft_pipeline.schemas import BlueprintSection, ExtractedFacts
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def _strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:html)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def build_section_prompt(
    *,
    section: BlueprintSection,
    facts: ExtractedFacts,
    user_prompt: str,
    legal_context: str = "",
) -> str:
    facts_json = json.dumps(facts.to_prompt_json(), ensure_ascii=False, indent=2)
    sample = (section.sample_html or "").strip() or f"<section><h2>{section.title}</h2><p>…</p></section>"
    gap_example = gap_marker("название пропущенного поля")
    legal_block = f"\n\nСПРАВОЧНЫЕ НОРМЫ (только для правовых формулировок):\n{legal_context}" if legal_context else ""

    return f"""Ты — опытный юрист. Напиши раздел «{section.title}» для процессуального документа.

ОБРАЗЕЦ РАЗДЕЛА (структура и стиль):
\"\"\"
{sample}
\"\"\"

ИСХОДНЫЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{user_prompt}

ПАСПОРТ ФАКТОВ И РАСЧЁТЫ (единственный источник правды — не придумывай факты):
{facts_json}
{legal_block}

ЖЁСТКИЕ ПРАВИЛА:
1. Верни только HTML-фрагмент раздела (можно обернуть в <section>…</section>).
2. Если в паспорте нет значения — вставь маркер {gap_example}.
3. Не придумывай ИНН, суммы, даты, ФИО без опоры в JSON.
4. Суммы и даты просрочки бери ТОЛЬКО из financial.verified / financial.
5. Не пересчитывай неустойку самостоятельно.
6. Сохраняй юридический стиль образца.
7. Не используй markdown-обёртки."""


def generate_one_section(
    *,
    section: BlueprintSection,
    facts: ExtractedFacts,
    user_prompt: str,
) -> str:
    legal_ctx = ""
    if "legal" in (section.rag_sources or []):
        legal_query = (section.rag_query or section.title or "").strip()
        legal_ctx = retrieve_legal_reference_context(query=legal_query)

    prompt = build_section_prompt(
        section=section,
        facts=facts,
        user_prompt=user_prompt,
        legal_context=legal_ctx,
    )
    llm = create_legal_llm(
        provider="yandex",
        model=config.YANDEX_GPT_MODEL_URI,
        use_rate_limiting=False,
        temperature=0.1,
        streaming=False,
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    raw = resp.content if hasattr(resp, "content") else str(resp)
    return _strip_markdown_fences(raw)
