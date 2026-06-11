"""LLM blueprint planner for scratch documents (no HTML template)."""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.json_utils import parse_llm_json_object
from app.services.draft_pipeline.schemas import BlueprintSection, ExtractedFacts
from app.services.draft_pipeline.section_registry import SCRATCH_BLUEPRINT, _slugify
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

_MAX_SECTIONS = 8


def _fallback_scratch(user_prompt: str) -> List[BlueprintSection]:
    sections = [s.model_copy(deep=True) for s in SCRATCH_BLUEPRINT]
    q = (user_prompt or "").strip()[:120]
    if q:
        for s in sections:
            s.rag_query = f"{s.rag_query} {q}".strip()
    return sections


def _legal_sources_for_title(title: str) -> List[str]:
    t = (title or "").lower()
    if any(k in t for k in ("прав", "мотив", "норм", "127", "закон", "ст.")):
        return ["case", "legal"]
    return ["case"]


def plan_scratch_blueprint(
    *,
    user_prompt: str,
    facts: ExtractedFacts,
) -> List[BlueprintSection]:
    """
    LLM plans document structure and per-section RAG queries when no template is selected.
    Falls back to SCRATCH_BLUEPRINT on failure.
    """
    if not bool(getattr(config, "DRAFT_SCRATCH_LLM_BLUEPRINT", True)):
        return _fallback_scratch(user_prompt)

    doc_type = facts.document_type or "процессуальный документ"
    facts_json = facts.to_prompt_json()

    prompt = f"""Ты юридический архитектор документов. Спланируй структуру процессуального документа.

ЗАДАНИЕ ЮРИСТА:
{user_prompt}

ТИП ДОКУМЕНТА (из паспорта фактов):
{doc_type}

ПАСПОРТ ФАКТОВ (JSON):
{facts_json}

Составь от 3 до {_MAX_SECTIONS} разделов. Для каждого:
- section_id: латиница snake_case (header, facts, legal, prayer, …)
- title: заголовок раздела на русском
- sample_html: минимальный HTML-каркас <section><h2>…</h2><p>…</p></section>
- rag_query: точный поисковый запрос к материалам дела для этого раздела
- rag_sources: ["case"] или ["case","legal"] для правовых блоков

Верни СТРОГО JSON:
{{
  "sections": [
    {{
      "section_id": "header",
      "title": "Шапка",
      "sample_html": "<section><h2>Шапка</h2><p>…</p></section>",
      "rag_query": "…",
      "rag_sources": ["case"]
    }}
  ]
}}"""

    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.1,
            streaming=False,
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        parsed = parse_llm_json_object(raw)
        sections_raw = (parsed or {}).get("sections") if isinstance(parsed, dict) else None
        if not isinstance(sections_raw, list) or not sections_raw:
            raise ValueError("empty sections in LLM plan")

        out: List[BlueprintSection] = []
        used_ids: set[str] = set()
        for i, item in enumerate(sections_raw[:_MAX_SECTIONS]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or f"Раздел {i + 1}").strip()
            sid = str(item.get("section_id") or "").strip() or _slugify(title, i)
            sid = re.sub(r"[^\w]+", "_", sid.lower())[:48] or f"section_{i}"
            if sid in used_ids:
                sid = f"{sid}_{i}"
            used_ids.add(sid)
            sample = str(item.get("sample_html") or "").strip()
            if not sample:
                sample = f"<section><h2>{title}</h2><p>…</p></section>"
            rag_q = str(item.get("rag_query") or f"{title} {user_prompt[:120]}").strip()
            sources = item.get("rag_sources")
            if isinstance(sources, list):
                rag_sources = [str(s) for s in sources if str(s) in ("case", "legal")] or ["case"]
            else:
                rag_sources = _legal_sources_for_title(title)
            out.append(
                BlueprintSection(
                    section_id=sid,
                    title=title,
                    sample_html=sample,
                    rag_query=rag_q,
                    rag_sources=rag_sources,  # type: ignore[arg-type]
                    section_index=i,
                )
            )

        if len(out) >= 2:
            logger.info("[draft_pipeline.scratch_plan] sections=%s ids=%s", len(out), [s.section_id for s in out])
            return out
    except Exception as exc:
        logger.warning("[draft_pipeline.scratch_plan] LLM plan failed, fallback: %s", exc)

    return _fallback_scratch(user_prompt)
