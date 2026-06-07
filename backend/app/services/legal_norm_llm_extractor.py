"""LLM-резолвер сложных отсылочных конструкций (фаза E)."""
from __future__ import annotations

import json
import logging
from typing import List, Optional, Sequence

from app.config import config
from app.services.legal_norm_cross_ref import ParsedCrossRef, parse_cross_reference

logger = logging.getLogger(__name__)


def resolve_unresolved_refs_llm(
    source_text: str,
    *,
    source_instrument_id: str,
    unresolved_raw: Sequence[str],
) -> List[ParsedCrossRef]:
    """
    Структурированное извлечение отсылок, которые regex не смог привязать к узлу графа.
    Вызывается только при LEGAL_NORM_LLM_EXTRACTOR_ENABLED=true.
    """
    if not unresolved_raw or not (source_text or "").strip():
        return []

    model = (
        getattr(config, "LEGAL_NORM_LLM_EXTRACTOR_MODEL", None)
        or getattr(config, "LEGAL_CORPUS_LLM_PLANNER_MODEL", None)
        or getattr(config, "DEFAULT_LLM_MODEL", "")
    ).strip()
    if not model:
        return []

    snippet = (source_text or "")[:4000]
    refs_list = "\n".join(f"- {r}" for r in unresolved_raw[:8])

    prompt = f"""Ты юридический парсер отсылочных норм РФ.
Источник: акт {source_instrument_id}.
Фрагмент:
{snippet}

Неразрешённые отсылки (regex):
{refs_list}

Верни JSON-массив объектов:
[{{"raw_text": "...", "article_number": "61.3", "clause_ref": "", "target_instrument_id": "gk-rf", "edge_type": "FORWARD_TO"}}]

edge_type: REFERENCES | FORWARD_TO | DEVELOPS | EXCEPTS
target_instrument_id: fz-127 | gk-rf | apk-rf | gpk-rf | plenum-63 | null (если тот же акт)
Только JSON, без пояснений."""

    try:
        from app.services.llm_factory import create_llm

        llm = create_llm(model=model, temperature=0, max_tokens=1024)
        resp = llm.invoke(prompt)
        content = getattr(resp, "content", None) or str(resp)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
    except Exception as exc:
        logger.debug("LLM cross-ref parse failed: %s", exc)
        return []

    if not isinstance(data, list):
        return []

    out: List[ParsedCrossRef] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw_text") or "").strip()
        art = str(item.get("article_number") or "").strip()
        if not art:
            continue
        parsed = parse_cross_reference(
            raw or f"ст. {art}",
            source_text=source_text,
            default_instrument_id=item.get("target_instrument_id") or source_instrument_id,
        )
        if parsed:
            out.append(
                ParsedCrossRef(
                    raw_text=raw or parsed.raw_text,
                    article_number=art,
                    clause_ref=str(item.get("clause_ref") or parsed.clause_ref or ""),
                    part_ref=parsed.part_ref,
                    target_instrument_id=item.get("target_instrument_id") or parsed.target_instrument_id,
                    edge_type=str(item.get("edge_type") or parsed.edge_type).upper(),
                )
            )
    return out
