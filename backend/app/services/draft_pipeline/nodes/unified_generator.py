"""Unified draft generation — single LLM pass with full case RAG (assistant-parity)."""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.draft_pipeline.markers import gap_marker, normalize_legacy_fillers
from app.services.draft_pipeline.schemas import ExtractedFacts
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def _strip_html_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:html)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _max_rag_chars() -> int:
    return int(getattr(config, "DRAFT_UNIFIED_RAG_MAX_CHARS", 24000) or 24000)


def _max_output_tokens() -> int:
    explicit = int(getattr(config, "DRAFT_UNIFIED_MAX_TOKENS", 0) or 0)
    if explicit > 0:
        return explicit
    return int(getattr(config, "YANDEX_GPT_MAX_TOKENS", 8192) or 8192)


def _compact_facts_json(facts: ExtractedFacts) -> str:
    return json.dumps(facts.to_prompt_json(), ensure_ascii=False, indent=2)


def _build_system_prompt(*, strategy: str) -> str:
    gap = gap_marker("название поля")
    if strategy == "template":
        return f"""Ты — опытный юрист. Заполняешь готовый HTML-шаблон процессуального документа.

ПРАВИЛА:
1. Сохрани структуру, разметку и порядок разделов шаблона. Не удаляй теги и каркас.
2. Замени плейсхолдеры `[ … ]`, `[ЗАПОЛНИТЬ]` и пустые поля фактами из дела.
3. Если значения нет в материалах — вставь маркер {gap}, не выдумывай.
4. Суммы, даты просрочки и неустойку бери ТОЛЬКО из financial.verified / financial в паспорте фактов.
5. Не пересчитывай неустойку самостоятельно.
6. Верни один цельный HTML-документ без markdown-обёрток и без пояснений вне HTML."""

    return f"""Ты — опытный юрист. Составляешь полный процессуальный документ с нуля в HTML.

ПРАВИЛА:
1. Документ должен быть готов к подаче: шапка, факты, правовое обоснование (если уместно), просительная часть.
2. Используй только факты из материалов дела и паспорта фактов; не галлюцинируй ИНН, суммы, даты.
3. Если данных нет — маркер {gap}.
4. Денежные показатели — только из financial.verified / financial.
5. Юридический стиль, русский язык.
6. Верни один цельный HTML (<section>, <p>, <h2>…) без markdown-обёрток."""


def _build_user_prompt(
    *,
    strategy: str,
    user_prompt: str,
    facts: ExtractedFacts,
    rag_context: str,
    template_html: Optional[str],
    template_label: Optional[str],
) -> str:
    rag = (rag_context or "").strip()
    if len(rag) > _max_rag_chars():
        rag = rag[:_max_rag_chars()] + "\n…"

    parts = [
        f"ЗАДАНИЕ ЮРИСТА:\n{(user_prompt or '').strip()}",
        f"ТИП ДОКУМЕНТА (из паспорта): {(facts.document_type or '—').strip()}",
        f"\nПАСПОРТ ФАКТОВ И РАСЧЁТЫ (источник правды):\n{_compact_facts_json(facts)}",
        f"\nМАТЕРИАЛЫ ДЕЛА (фрагменты поиска — как у case assistant):\n{rag or '(контекст не передан — опирайся на паспорт фактов)'}",
    ]

    if strategy == "template" and (template_html or "").strip():
        label = (template_label or "шаблон").strip()
        parts.append(
            f"\nHTML-ШАБЛОН «{label}» (сохрани структуру, заполни содержимое):\n"
            f"{template_html.strip()}"
        )
    elif strategy == "template":
        parts.append(
            "\nРежим template выбран, но тело шаблона пусто — составь документ по типу из задания."
        )

    parts.append("\nВерни только HTML документа.")
    return "\n".join(parts)


def run_unified_draft_generation(
    *,
    strategy: str,
    user_prompt: str,
    facts: ExtractedFacts,
    rag_context: str = "",
    template_html: Optional[str] = None,
    template_label: Optional[str] = None,
) -> str:
    """
    Generate complete draft HTML in one LLM invocation.

    Uses the same ingredients as case assistant answer quality: full RAG context
    plus structured fact passport (incl. verified financials).
    """
    strat = "template" if strategy == "template" and (template_html or "").strip() else "scratch"
    if strategy == "template" and strat == "scratch":
        logger.warning("[draft.unified] template strategy but empty HTML — falling back to scratch")

    system = _build_system_prompt(strategy=strat)
    user = _build_user_prompt(
        strategy=strat,
        user_prompt=user_prompt,
        facts=facts,
        rag_context=rag_context,
        template_html=template_html,
        template_label=template_label,
    )

    llm = create_legal_llm(max_tokens=_max_output_tokens())
    logger.info(
        "[draft.unified] generating strategy=%s rag_chars=%s facts_type=%s",
        strat,
        len(rag_context or ""),
        (facts.document_type or "-")[:40],
    )

    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)

    html = normalize_legacy_fillers(_strip_html_fences(str(raw)))
    if not html.strip():
        raise RuntimeError("unified draft generation returned empty HTML")

    logger.info("[draft.unified] done html_chars=%s", len(html))
    return html
