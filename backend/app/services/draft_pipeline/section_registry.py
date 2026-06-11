"""Blueprint construction: template HTML sections or scratch defaults."""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.draft_pipeline.schemas import BlueprintSection, ExtractedFacts

_SECTION_BLOCK = re.compile(
    r"<section\b[^>]*>([\s\S]*?)</section>",
    re.IGNORECASE,
)
_H2_TITLE = re.compile(r"<h2\b[^>]*>([\s\S]*?)</h2>", re.IGNORECASE)


def _slugify(title: str, index: int) -> str:
    t = re.sub(r"<[^>]+>", "", title or "")
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    t = re.sub(r"\s+", "_", t.strip().lower())
    if not t:
        return f"section_{index}"
    return t[:48]


# Default scratch blueprint for documents without a fixed template.
SCRATCH_BLUEPRINT: List[BlueprintSection] = [
    BlueprintSection(
        section_id="header",
        title="Шапка и реквизиты",
        sample_html="<p>В [наименование суда]</p><p>Истец: …</p><p>Ответчик: …</p>",
        rag_query="стороны реквизиты суд наименование адрес ИНН ОГРН",
        rag_sources=["case"],
        section_index=0,
    ),
    BlueprintSection(
        section_id="facts",
        title="Обстоятельства",
        sample_html="<p>Изложите фактические обстоятельства дела…</p>",
        rag_query="обстоятельства договор исполнение нарушение события хронология",
        rag_sources=["case"],
        section_index=1,
    ),
    BlueprintSection(
        section_id="legal",
        title="Правовое обоснование",
        sample_html="<p>Ссылки на нормы права и позицию…</p>",
        rag_query="правовое обоснование нормы закон статья основание",
        rag_sources=["case", "legal"],
        section_index=2,
    ),
    BlueprintSection(
        section_id="prayer",
        title="Просительная часть",
        sample_html="<p>Прошу суд…</p>",
        rag_query="требования просительная часть что просим взыскать",
        rag_sources=["case"],
        section_index=3,
    ),
    BlueprintSection(
        section_id="attachments",
        title="Приложения",
        sample_html="<ol><li>Копия договора</li></ol>",
        rag_query="приложения документы перечень",
        rag_sources=["case"],
        section_index=4,
    ),
]


def parse_template_sections(template_html: str) -> List[BlueprintSection]:
    """Extract blueprint items from HTML <section> blocks."""
    html = (template_html or "").strip()
    if not html:
        return []

    blocks = _SECTION_BLOCK.findall(html)
    if not blocks:
        # Fallback: split by h2 outside sections
        parts = re.split(r"(?=<h2\b)", html, flags=re.IGNORECASE)
        blocks = [p for p in parts if p.strip()]
        if len(blocks) <= 1 and html:
            blocks = [html]

    out: List[BlueprintSection] = []
    for i, inner in enumerate(blocks):
        full_block = inner
        if not inner.strip().lower().startswith("<section"):
            full_block = f"<section>{inner}</section>"
        else:
            full_block = inner if inner.strip().startswith("<section") else f"<section>{inner}</section>"

        m = _H2_TITLE.search(full_block)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else f"Раздел {i + 1}"
        sid = _slugify(title, i)
        rag_q = f"{title} {re.sub(r'\\[.*?\\]', ' ', full_block)[:200]}"
        out.append(
            BlueprintSection(
                section_id=sid,
                title=title,
                sample_html=full_block.strip(),
                rag_query=rag_q.strip(),
                rag_sources=["case"] if i != len(blocks) - 2 else ["case", "legal"],
                section_index=i,
            )
        )
    return out


def build_blueprint(
    *,
    strategy: str,
    template_html: Optional[str],
    user_prompt: str,
    facts: Optional[ExtractedFacts] = None,
) -> List[BlueprintSection]:
    from app.services.draft_pipeline.nodes.scratch_planner import plan_scratch_blueprint

    if strategy == "template" and (template_html or "").strip():
        parsed = parse_template_sections(template_html)
        if parsed:
            return parsed
    return plan_scratch_blueprint(user_prompt=user_prompt, facts=facts or ExtractedFacts())
