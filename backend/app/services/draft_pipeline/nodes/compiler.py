"""Node 4: merge generated sections into final HTML."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from app.services.draft_pipeline.markers import html_tag_balance_ok, normalize_legacy_fillers
from app.services.draft_pipeline.schemas import BlueprintSection

logger = logging.getLogger(__name__)

_SECTION_BLOCK = re.compile(
    r"(<section\b[^>]*>)([\s\S]*?)(</section>)",
    re.IGNORECASE,
)


def _replace_section_inner(html: str, index: int, new_inner: str) -> str:
    """Replace inner content of the index-th <section> while keeping opening/closing tags."""
    matches = list(_SECTION_BLOCK.finditer(html))
    if index >= len(matches):
        return html
    m = matches[index]
    # Strip outer section wrapper from generated chunk if present
    inner = (new_inner or "").strip()
    inner = re.sub(r"^<section\b[^>]*>", "", inner, flags=re.IGNORECASE).strip()
    inner = re.sub(r"</section>\s*$", "", inner, flags=re.IGNORECASE).strip()
    return html[: m.start(2)] + inner + html[m.end(2) :]


def compile_template_document(
    template_html: str,
    blueprint: List[BlueprintSection],
    generated_sections: Dict[str, str],
) -> str:
    html = (template_html or "").strip()
    if not html:
        return compile_scratch_document(blueprint, generated_sections)

    section_blocks = list(_SECTION_BLOCK.finditer(html))
    if section_blocks:
        for spec in blueprint:
            gen = (generated_sections.get(spec.section_id) or "").strip()
            if not gen:
                continue
            html = _replace_section_inner(html, spec.section_index, gen)
    else:
        # No <section> tags: append generated bodies after template skeleton
        parts = [html]
        for spec in blueprint:
            gen = generated_sections.get(spec.section_id)
            if gen:
                parts.append(gen)
        html = "\n".join(parts)

    return normalize_legacy_fillers(html)


def compile_scratch_document(
    blueprint: List[BlueprintSection],
    generated_sections: Dict[str, str],
) -> str:
    parts = ['<article class="legal-draft">']
    for spec in blueprint:
        gen = (generated_sections.get(spec.section_id) or "").strip()
        if gen:
            if gen.lower().startswith("<section"):
                parts.append(gen)
            else:
                parts.append(f"<section><h2>{spec.title}</h2>{gen}</section>")
        else:
            parts.append(f"<section><h2>{spec.title}</h2><p>[раздел не сгенерирован]</p></section>")
    parts.append("</article>")
    return normalize_legacy_fillers("\n".join(parts))


def run_compiler(
    *,
    strategy: str,
    template_html: Optional[str],
    blueprint: List[BlueprintSection],
    generated_sections: Dict[str, str],
) -> str:
    if strategy == "template" and (template_html or "").strip():
        html = compile_template_document(template_html, blueprint, generated_sections)
    else:
        html = compile_scratch_document(blueprint, generated_sections)

    if not html_tag_balance_ok(html):
        logger.warning("[draft_pipeline.compiler] HTML tag balance check failed; returning anyway")
    return html
