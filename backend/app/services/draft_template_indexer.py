"""Индексация плейсхолдеров шаблона Draft при загрузке."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_template_catalog import content_sha256, load_catalog_snapshot, upsert_catalog
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\[[^\[\]]+\]")


@dataclass
class PlaceholderOccurrence:
    marker: str
    occurrence_index: int
    start_offset: int
    end_offset: int


def scan_placeholder_occurrences(html: str) -> List[PlaceholderOccurrence]:
    if not html or not str(html).strip():
        return []
    seen: Dict[str, int] = {}
    out: List[PlaceholderOccurrence] = []
    for m in _PLACEHOLDER_RE.finditer(html):
        ph = m.group(0)
        idx = seen.get(ph, 0)
        seen[ph] = idx + 1
        out.append(
            PlaceholderOccurrence(
                marker=ph,
                occurrence_index=idx,
                start_offset=m.start(),
                end_offset=m.end(),
            )
        )
    return out


def build_context_snippet(html: str, start: int, end: int, radius: int = 140) -> str:
    a = max(0, start - radius)
    b = min(len(html), end + radius)
    frag = html[a:b]
    frag = re.sub(r"\s+", " ", frag).strip()
    if len(frag) > 360:
        frag = frag[:357] + "…"
    return frag


def _heuristic_field_spec(occ: PlaceholderOccurrence, html: str, template_title: str) -> TemplateFieldSpec:
    inner = occ.marker.strip("[]").strip() or "поле"
    ctx = build_context_snippet(html, occ.start_offset, occ.end_offset)
    label = f"{inner} (контекст: {ctx[:120]})" if ctx else inner
    return TemplateFieldSpec(
        field_id=f"ph_{occ.occurrence_index:03d}_{re.sub(r'[^a-zA-Z0-9_]', '_', inner)[:24]}",
        marker=occ.marker,
        occurrence_index=occ.occurrence_index,
        start_offset=occ.start_offset,
        end_offset=occ.end_offset,
        context_snippet=ctx,
        semantic_label=label,
        what_to_find=f"Найти в материалах дела значение для поля «{inner}» с учётом контекста шаблона.",
        retrieval_query=f"{template_title}: {inner}. Контекст в шаблоне: {ctx[:280]}",
        data_type=_guess_data_type(inner),
        entity_role=_guess_entity_role(ctx),
    )


def _guess_data_type(marker_inner: str) -> str:
    low = marker_inner.lower()
    if "инн" in low:
        return "inn"
    if "огрн" in low:
        return "ogrn"
    if any(x in low for x in ("дата", "число", "год")):
        return "date"
    if any(x in low for x in ("сумм", "размер", "руб")):
        return "amount"
    if any(x in low for x in ("суд", "арбитраж")):
        return "court_name"
    if any(x in low for x in ("наименован", "фио", "имя", "организац")):
        return "party_name"
    if "адрес" in low:
        return "address"
    return "other"


def _guess_entity_role(context: str) -> Optional[str]:
    low = (context or "").lower()
    if any(x in low for x in ("кредитор", "заявител", "истец")):
        return "creditor"
    if any(x in low for x in ("должник", "ответчик")):
        return "debtor"
    if any(x in low for x in ("суд", "арбитраж")):
        return "court"
    return None


def inject_field_anchors(html: str, specs: List[TemplateFieldSpec]) -> str:
    """Оборачивает плейсхолдеры в span data-draft-field (с конца файла)."""
    if not html or not specs:
        return html
    ordered = sorted(specs, key=lambda s: s.start_offset, reverse=True)
    out = html
    for spec in ordered:
        if spec.start_offset < 0 or spec.end_offset > len(out) or spec.start_offset >= spec.end_offset:
            continue
        inner = out[spec.start_offset : spec.end_offset]
        wrapped = f'<span data-draft-field="{spec.field_id}">{inner}</span>'
        out = out[: spec.start_offset] + wrapped + out[spec.end_offset :]
    return out


def _parse_enrich_batch(raw: str, batch: List[PlaceholderOccurrence]) -> Dict[str, Dict[str, Any]]:
    if not raw or not str(raw).strip():
        return {}
    t = str(raw).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t, flags=re.IGNORECASE)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    if not isinstance(obj, dict):
        return {}
    fields = obj.get("fields")
    if not isinstance(fields, list):
        return {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in fields:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("field_id") or "").strip()
        if fid:
            by_id[fid] = item
    return by_id


def enrich_fields_via_llm(
    html: str,
    occurrences: List[PlaceholderOccurrence],
    *,
    template_title: str,
    batch_size: int = 10,
) -> List[TemplateFieldSpec]:
    """LLM-обогащение полей; при ошибке — эвристики."""
    if not occurrences:
        return []

    base_specs: List[TemplateFieldSpec] = []
    for i, occ in enumerate(occurrences):
        spec = _heuristic_field_spec(occ, html, template_title)
        spec.field_id = f"ph_{i:03d}"
        base_specs.append(spec)

    try:
        from langchain_core.messages import HumanMessage

        from app.services.llm_factory import create_legal_llm
    except Exception as e:
        logger.warning("[draft_template_indexer] LLM import failed: %s", e)
        return base_specs

    llm = create_legal_llm(provider="yandex", use_rate_limiting=False)
    enriched: List[TemplateFieldSpec] = []

    for i in range(0, len(base_specs), batch_size):
        batch = base_specs[i : i + batch_size]
        lines = []
        for s in batch:
            lines.append(
                f"- field_id={s.field_id} marker={s.marker!r} occurrence_index={s.occurrence_index}\n"
                f"  context: {s.context_snippet}"
            )
        prompt = (
            "Ты индексируешь юридический HTML-шаблон. Для каждого поля опиши, ЧТО именно нужно найти "
            "в материалах дела (учитывай контекст — одинаковый marker в разных местах = разные поля).\n"
            f"Шаблон: {template_title}\n\n"
            "ПОЛЯ:\n" + "\n".join(lines) + "\n\n"
            "Ответь ТОЛЬКО JSON:\n"
            '{"fields":[{"field_id":"ph_000","semantic_label":"...","what_to_find":"...","retrieval_query":"...",'
            '"data_type":"inn|party_name|court_name|date|amount|address|other","entity_role":"creditor|debtor|court|null"}]}\n'
        )
        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(raw, list):
                raw = "".join(str(x) for x in raw)
            by_id = _parse_enrich_batch(str(raw), [])
        except Exception as e:
            logger.warning("[draft_template_indexer] LLM enrich batch failed: %s", e)
            enriched.extend(batch)
            continue

        for s in batch:
            extra = by_id.get(s.field_id) or {}
            enriched.append(
                TemplateFieldSpec(
                    field_id=s.field_id,
                    marker=s.marker,
                    occurrence_index=s.occurrence_index,
                    start_offset=s.start_offset,
                    end_offset=s.end_offset,
                    context_snippet=s.context_snippet,
                    semantic_label=str(extra.get("semantic_label") or s.semantic_label).strip(),
                    what_to_find=str(extra.get("what_to_find") or s.what_to_find).strip(),
                    retrieval_query=str(extra.get("retrieval_query") or s.retrieval_query).strip(),
                    data_type=str(extra.get("data_type") or s.data_type).strip() or "other",
                    entity_role=extra.get("entity_role") if extra.get("entity_role") else s.entity_role,
                )
            )

    return enriched or base_specs


def index_template_html(
    db: Session,
    *,
    template_key: str,
    html: str,
    template_title: str = "",
    force: bool = False,
) -> Tuple[TemplateFieldCatalogSnapshot, str]:
    """
    Индексирует шаблон. Returns (snapshot, status).
    status: indexed | skipped_unchanged | skipped_disabled | no_placeholders
    """
    if not bool(getattr(config, "DRAFT_TEMPLATE_INDEX_ON_UPLOAD", True)):
        return (
            load_catalog_snapshot(db, template_key) or TemplateFieldCatalogSnapshot(
                template_key=template_key, indexed_html=html, field_specs=[]
            ),
            "skipped_disabled",
        )

    html = (html or "").strip()
    if not html:
        return TemplateFieldCatalogSnapshot(template_key=template_key, indexed_html="", field_specs=[]), "empty"

    sha = content_sha256(html)
    version = str(getattr(config, "DRAFT_TEMPLATE_INDEXER_VERSION", "1") or "1")

    if not force:
        existing = load_catalog_snapshot(db, template_key, require_sha256=sha)
        if existing and existing.field_specs:
            return existing, "skipped_unchanged"

    occs = scan_placeholder_occurrences(html)
    if not occs:
        snap = upsert_catalog(
            db,
            template_key=template_key,
            html=html,
            field_specs=[],
            indexed_html=html,
            indexer_version=version,
        )
        return snap, "no_placeholders"

    specs = enrich_fields_via_llm(html, occs, template_title=template_title or template_key)
    indexed_html = inject_field_anchors(html, specs)
    snap = upsert_catalog(
        db,
        template_key=template_key,
        html=html,
        field_specs=specs,
        indexed_html=indexed_html,
        indexer_version=version,
    )
    return snap, "indexed"
