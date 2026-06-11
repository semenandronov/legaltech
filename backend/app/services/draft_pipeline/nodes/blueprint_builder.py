"""Node 2: blueprint from template HTML or LLM scratch planner."""
from __future__ import annotations

from typing import List, Optional

from app.services.draft_pipeline.nodes.scratch_planner import plan_scratch_blueprint
from app.services.draft_pipeline.schemas import BlueprintSection, ExtractedFacts
from app.services.draft_pipeline.section_registry import parse_template_sections


def run_blueprint_builder(
    *,
    strategy: str,
    template_html: str | None,
    user_prompt: str,
    facts: Optional[ExtractedFacts] = None,
) -> List[BlueprintSection]:
    if strategy == "template" and (template_html or "").strip():
        parsed = parse_template_sections(template_html)
        if parsed:
            return parsed
    return plan_scratch_blueprint(
        user_prompt=user_prompt,
        facts=facts or ExtractedFacts(),
    )
