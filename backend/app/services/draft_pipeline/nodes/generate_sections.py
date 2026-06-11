"""Node 3 (orchestrator): parallel section generation (state-only)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from app.config import config
from app.services.draft_pipeline.nodes.section_generate import generate_one_section
from app.services.draft_pipeline.schemas import BlueprintSection, ExtractedFacts

logger = logging.getLogger(__name__)


def run_parallel_section_generation(
    *,
    blueprint: List[BlueprintSection],
    facts: ExtractedFacts,
    user_prompt: str,
) -> Dict[str, str]:
    if not blueprint:
        return {}

    max_workers = min(
        len(blueprint),
        max(1, int(getattr(config, "DRAFT_SECTION_MAX_PARALLEL", 5) or 5)),
    )
    results: Dict[str, str] = {}

    def _job(spec: BlueprintSection) -> tuple[str, str]:
        text = generate_one_section(section=spec, facts=facts, user_prompt=user_prompt)
        return spec.section_id, text

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_job, spec): spec.section_id for spec in blueprint}
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                section_id, text = fut.result()
                results[section_id] = text
            except Exception as exc:
                logger.error("[draft_pipeline.sections] failed section_id=%s: %s", sid, exc, exc_info=True)
                results[sid] = f"<section><h2>{sid}</h2><p>[? ошибка генерации раздела ?]</p></section>"

    return results
