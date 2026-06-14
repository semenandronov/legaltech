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
from app.services.draft_template_questions import (
    assign_question_metadata,
    audit_template_questions,
    build_fill_question,
    sanitize_fill_question,
    unify_semantic_duplicate_questions,
)
from app.services.draft_template_schemas import TemplateFieldCatalogSnapshot, TemplateFieldSpec

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\[[^\[\]]+\]")
_DOCXTPL_MARKER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass
class PlaceholderOccurrence:
    marker: str
    occurrence_index: int
    start_offset: int
    end_offset: int


def scan_docxtpl_placeholder_occurrences(html: str) -> List[PlaceholderOccurrence]:
    """Найти все {{ variable }} в HTML preview."""
    if not html or not str(html).strip():
        return []
    seen: Dict[str, int] = {}
    out: List[PlaceholderOccurrence] = []
    for m in _DOCXTPL_MARKER_RE.finditer(html):
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
    entity_role = _guess_entity_role(ctx)
    spec = TemplateFieldSpec(
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
        entity_role=entity_role,
    )
    fq = build_fill_question(spec)
    from app.services.draft_template_questions import question_key_for_fill_question

    return spec.model_copy(
        update={
            "fill_question": fq,
            "question_key": question_key_for_fill_question(fq),
        }
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


def _pick_manifest_placeholder_def(
    defs: List[Dict[str, Any]],
    occ: PlaceholderOccurrence,
    html: str,
) -> Dict[str, Any]:
    """Выбор определения placeholder при нескольких вариантах одного marker."""
    if len(defs) == 1:
        return defs[0]
    ctx = build_context_snippet(html, occ.start_offset, occ.end_offset).lower()
    for item in defs:
        hint = str(item.get("context_hint") or "").strip().lower()
        if hint and hint in ctx:
            return item
    if occ.occurrence_index < len(defs):
        return defs[occ.occurrence_index]
    return defs[0]


def build_specs_from_manifest_placeholders(
    html: str,
    occurrences: List[PlaceholderOccurrence],
    *,
    placeholders: List[Dict[str, Any]],
    template_title: str,
) -> List[TemplateFieldSpec]:
    """Индексация по вопросам из manifest.json — без LLM."""
    if not occurrences:
        return []
    if not placeholders:
        raise ValueError("manifest placeholders: пустой список")

    by_marker: Dict[str, List[Dict[str, Any]]] = {}
    for item in placeholders:
        marker = str(item.get("marker") or "").strip()
        if marker:
            by_marker.setdefault(marker, []).append(item)

    specs: List[TemplateFieldSpec] = []
    missing: List[str] = []

    for i, occ in enumerate(occurrences):
        defs = by_marker.get(occ.marker)
        if not defs:
            missing.append(occ.marker)
            continue
        defn = _pick_manifest_placeholder_def(defs, occ, html)
        base = _heuristic_field_spec(occ, html, template_title)
        fill_q = sanitize_fill_question(str(defn.get("fill_question") or ""), base)
        entity_role = defn.get("entity_role") or base.entity_role
        data_type = str(defn.get("data_type") or base.data_type).strip() or "other"
        what = str(defn.get("what_to_find") or fill_q).strip()
        specs.append(
            base.model_copy(
                update={
                    "field_id": f"ph_{i:03d}",
                    "fill_question": fill_q,
                    "entity_role": entity_role,
                    "data_type": data_type,
                    "what_to_find": what,
                    "semantic_label": str(defn.get("semantic_label") or base.semantic_label).strip(),
                    "retrieval_query": str(defn.get("retrieval_query") or what).strip(),
                }
            )
        )

    if missing:
        unique_missing = sorted(set(missing))
        raise ValueError(
            "в HTML есть плейсхолдеры без вопросов в manifest: " + ", ".join(unique_missing[:12])
        )

    specs = unify_semantic_duplicate_questions(specs)
    finalized, unique = assign_question_metadata(specs)
    logger.info(
        "[draft_template_indexer] manifest questions unique=%s occurrences=%s",
        len(unique),
        len(finalized),
    )
    return finalized


def build_specs_from_manifest_variables(
    html: str,
    occurrences: List[PlaceholderOccurrence],
    *,
    placeholders: List[Dict[str, Any]],
    template_title: str,
) -> List[TemplateFieldSpec]:
    """Индексация docxtpl: variables[] + каталог вопросов."""
    if not occurrences:
        return []
    if not placeholders:
        raise ValueError("manifest variables: пустой список")

    from app.services.bankruptcy_field_catalog import get_field_description, get_field_meta

    by_var: Dict[str, Dict[str, Any]] = {}
    for item in placeholders:
        var = str(item.get("variable") or "").strip()
        if not var:
            marker = str(item.get("marker") or "")
            m = _DOCXTPL_MARKER_RE.search(marker)
            if m:
                var = m.group(1)
        if var:
            by_var[var] = item

    specs: List[TemplateFieldSpec] = []
    missing: List[str] = []

    for i, occ in enumerate(occurrences):
        m = _DOCXTPL_MARKER_RE.search(occ.marker)
        if not m:
            continue
        var = m.group(1)
        defn = by_var.get(var)
        if not defn:
            missing.append(var)
            continue
        meta = get_field_meta(var)
        fill_q = str(defn.get("fill_question") or get_field_description(var)).strip()
        ctx = build_context_snippet(html, occ.start_offset, occ.end_offset)
        specs.append(
            TemplateFieldSpec(
                field_id=f"var_{var}_{occ.occurrence_index:03d}",
                marker=occ.marker,
                occurrence_index=occ.occurrence_index,
                start_offset=occ.start_offset,
                end_offset=occ.end_offset,
                context_snippet=ctx,
                semantic_label=var,
                what_to_find=fill_q,
                retrieval_query=f"{template_title}: {var}. {ctx[:200]}",
                data_type=str(defn.get("data_type") or meta.get("data_type") or "other"),
                entity_role=defn.get("entity_role") or meta.get("entity_role"),
                fill_question=fill_q,
                question_key=var,
                variable=var,
            )
        )

    if missing:
        unique_missing = sorted(set(missing))
        raise ValueError(
            "в шаблоне есть переменные без описания в manifest/каталоге: "
            + ", ".join(unique_missing[:12])
        )

    finalized, unique = assign_question_metadata(specs)
    logger.info(
        "[draft_template_indexer] docxtpl variables unique=%s occurrences=%s",
        len(unique),
        len(finalized),
    )
    return finalized


def _resolve_manifest_placeholders(template_key: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """('bankruptcy'|'db'|..., placeholders или None)."""
    from app.services.draft_template_keys import parse_template_key
    from app.services.bankruptcy_templates import get_manifest_placeholders

    kind, ident = parse_template_key(template_key)
    if kind == "bankruptcy" and ident:
        return kind, get_manifest_placeholders(ident)
    return kind, None


def _build_heuristic_specs(html: str, occurrences: List[PlaceholderOccurrence], template_title: str) -> List[TemplateFieldSpec]:
    specs: List[TemplateFieldSpec] = []
    for i, occ in enumerate(occurrences):
        spec = _heuristic_field_spec(occ, html, template_title)
        specs.append(spec.model_copy(update={"field_id": f"ph_{i:03d}"}))
    specs = unify_semantic_duplicate_questions(specs)
    finalized, _ = assign_question_metadata(specs)
    return finalized


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
        finalized, _ = assign_question_metadata(unify_semantic_duplicate_questions(base_specs))
        return finalized

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
            "Ты готовишь вопросы для автозаполнения юридического шаблона банкротства.\n"
            "Для КАЖДОГО плейсхолдера сформулируй fill_question — один чёткий вопрос на русском, "
            "заканчивающийся «?».\n\n"
            "ПРАВИЛА:\n"
            "1. Вопрос должен быть самодостаточным: LLM ответит только по запросу юриста и материалам дела.\n"
            "2. Указывай роль стороны, если видна из контекста: кредитор / должник / суд.\n"
            "3. Одинаковый смысл в разных местах шаблона → ДОСЛОВНО одинаковый fill_question "
            "(например, все [наименование кредитора] → «Какое полное наименование кредитора?»).\n"
            "4. Одинаковый marker, но разный контекст → РАЗНЫЕ вопросы "
            "(например, [дата составления] ≠ дата договора).\n"
            "5. Не используй общие фразы «найти в материалах», «заполните поле».\n"
            "6. Примеры хороших вопросов:\n"
            "   - Какое полное наименование кредитора?\n"
            "   - Какой ИНН должника?\n"
            "   - Какова сумма основного долга по требованию кредитора?\n"
            "   - Какой размер государственной пошлины?\n"
            "   - В какой арбитражный суд подаётся заявление?\n"
            "   - Какая дата составления заявления?\n\n"
            f"Шаблон: {template_title}\n\n"
            "ПОЛЯ:\n" + "\n".join(lines) + "\n\n"
            "Ответь ТОЛЬКО JSON:\n"
            '{"fields":[{"field_id":"ph_000","fill_question":"Какой ИНН кредитора?",'
            '"semantic_label":"ИНН кредитора","what_to_find":"ИНН организации-кредитора",'
            '"retrieval_query":"ИНН кредитора из договора или выписки",'
            '"data_type":"inn","entity_role":"creditor"}]}\n'
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
            raw_fill_q = str(extra.get("fill_question") or "").strip()
            entity_role = extra.get("entity_role") if extra.get("entity_role") else s.entity_role
            draft = TemplateFieldSpec(
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
                entity_role=entity_role,
            )
            fill_q = sanitize_fill_question(raw_fill_q, draft) if raw_fill_q else build_fill_question(draft)
            enriched.append(draft.model_copy(update={"fill_question": fill_q}))

    specs_out = enriched or base_specs
    specs_out = unify_semantic_duplicate_questions(specs_out)
    finalized, unique = assign_question_metadata(specs_out)
    logger.info(
        "[draft_template_indexer] questions unique=%s occurrences=%s",
        len(unique),
        len(finalized),
    )
    return finalized


def _enrich_snapshot_meta(
    snap: TemplateFieldCatalogSnapshot,
    template_key: str,
) -> TemplateFieldCatalogSnapshot:
    """Добавить engine/docx_file из manifest для bankruptcy-шаблонов."""
    from app.services.draft_template_keys import parse_template_key
    from app.services.bankruptcy_templates import get_template_engine, get_template_meta

    kind, ident = parse_template_key(template_key)
    if kind != "bankruptcy" or not ident:
        return snap
    meta = get_template_meta(ident)
    if not meta:
        return snap
    engine = get_template_engine(ident)
    docx_file = str(meta.get("file") or "") if engine == "docxtpl" else ""
    return snap.model_copy(update={"engine": engine, "docx_file": docx_file})


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
    version = str(getattr(config, "DRAFT_TEMPLATE_INDEXER_VERSION", "3") or "3")

    if not force:
        existing = load_catalog_snapshot(db, template_key, require_sha256=sha)
        if existing and existing.field_specs and str(existing.indexer_version or "") == version:
            return _enrich_snapshot_meta(existing, template_key), "skipped_unchanged"

    docxtpl_occs = scan_docxtpl_placeholder_occurrences(html)
    bracket_occs = scan_placeholder_occurrences(html) if not docxtpl_occs else []
    occs = docxtpl_occs or bracket_occs
    if not occs:
        snap = upsert_catalog(
            db,
            template_key=template_key,
            html=html,
            field_specs=[],
            indexed_html=html,
            indexer_version=version,
        )
        return _enrich_snapshot_meta(snap, template_key), "no_placeholders"

    kind, manifest_placeholders = _resolve_manifest_placeholders(template_key)
    llm_enrich = bool(getattr(config, "DRAFT_TEMPLATE_INDEX_LLM_ENRICH", False))
    is_docxtpl = bool(docxtpl_occs)

    try:
        if kind == "bankruptcy":
            if not manifest_placeholders:
                logger.error(
                    "[draft_template_indexer] bankruptcy key=%s: добавьте variables в manifest.json",
                    template_key,
                )
                return (
                    _enrich_snapshot_meta(
                        TemplateFieldCatalogSnapshot(template_key=template_key, indexed_html=html, field_specs=[]),
                        template_key,
                    ),
                    "missing_manifest_placeholders",
                )
            if is_docxtpl:
                specs = build_specs_from_manifest_variables(
                    html,
                    occs,
                    placeholders=manifest_placeholders,
                    template_title=template_title or template_key,
                )
            else:
                specs = build_specs_from_manifest_placeholders(
                    html,
                    occs,
                    placeholders=manifest_placeholders,
                    template_title=template_title or template_key,
                )
        elif llm_enrich:
            specs = enrich_fields_via_llm(html, occs, template_title=template_title or template_key)
        else:
            specs = _build_heuristic_specs(html, occs, template_title or template_key)
    except ValueError as e:
        logger.error("[draft_template_indexer] manifest index failed key=%s: %s", template_key, e)
        return (
            _enrich_snapshot_meta(
                TemplateFieldCatalogSnapshot(template_key=template_key, indexed_html=html, field_specs=[]),
                template_key,
            ),
            "manifest_error",
        )

    indexed_html = inject_field_anchors(html, specs)
    snap = upsert_catalog(
        db,
        template_key=template_key,
        html=html,
        field_specs=specs,
        indexed_html=indexed_html,
        indexer_version=version,
    )
    return _enrich_snapshot_meta(snap, template_key), "indexed"
