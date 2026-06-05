"""Извлечение значений полей и подстановка в indexed_html Draft."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.services.draft_template_schemas import TemplateFieldSpec

logger = logging.getLogger(__name__)

_FIELD_SPAN_RE = re.compile(
    r'<span\s+data-draft-field="([^"]+)"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


def _parse_extract_json(raw: str) -> Dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    t = str(raw).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t, flags=re.IGNORECASE)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}\s*$", t)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def extract_field_value(
    field: TemplateFieldSpec,
    rag_context: str,
    *,
    user_context: str = "",
    llm=None,
) -> Tuple[Optional[str], float]:
    """
    Извлечь значение для поля из RAG-контекста.

    Returns (value or None, confidence).
    """
    ctx = (rag_context or "").strip()
    if not ctx:
        return None, 0.0

    if llm is None:
        try:
            from langchain_core.messages import HumanMessage

            from app.services.llm_factory import create_legal_llm

            llm = create_legal_llm(provider="yandex", use_rate_limiting=False)
        except Exception as e:
            logger.warning("[draft_field_fill] LLM unavailable: %s", e)
            return None, 0.0

    from langchain_core.messages import HumanMessage

    prompt = (
        "Извлеки значение для одного поля юридического шаблона из фрагментов материалов дела.\n"
        "Ответь ТОЛЬКО JSON: {\"value\": \"строка\" или null, \"confidence\": 0.0-1.0}\n"
        "null если в фрагментах нет однозначного значения. Не выдумывай.\n\n"
        f"ПОЛЕ: {field.semantic_label or field.marker}\n"
        f"ЧТО ИСКАТЬ: {field.what_to_find or field.retrieval_query}\n"
        f"МАРКЕР В ШАБЛОНЕ: {field.marker}\n"
    )
    if user_context.strip():
        prompt += f"\nКОНТЕКСТ ЗАПРОСА:\n{user_context[:2000]}\n"
    prompt += f"\nФРАГМЕНТЫ ИЗ ДЕЛА:\n{ctx[:8000]}\n"

    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(raw, list):
            raw = "".join(str(x) for x in raw)
        obj = _parse_extract_json(str(raw))
        val = obj.get("value")
        conf = float(obj.get("confidence") or 0.0)
        if val is None:
            return None, conf
        s = str(val).strip()
        if not s or s.lower() in ("null", "none", "н/д", "n/a"):
            return None, conf
        return s, conf
    except Exception as e:
        logger.warning("[draft_field_fill] extract failed field=%s: %s", field.field_id, e)
        return None, 0.0


def extract_fields_batch(
    fields: List[TemplateFieldSpec],
    rag_by_field_id: Dict[str, str],
    *,
    user_context: str = "",
    llm=None,
) -> Dict[str, Optional[str]]:
    """Per-field extract (для точечного дожима с отдельным RAG-контекстом)."""
    out: Dict[str, Optional[str]] = {}
    for f in fields:
        ctx = rag_by_field_id.get(f.field_id) or ""
        val, _conf = extract_field_value(f, ctx, user_context=user_context, llm=llm)
        out[f.field_id] = val
    return out


def _normalize_extracted_value(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "н/д", "n/a"):
        return None
    return s


def _fields_chunk_size() -> int:
    """Сколько полей за один вызов LLM (по умолчанию — весь шаблон за 1–2 вызова)."""
    return max(8, int(getattr(config, "DRAFT_BULK_UNIFIED_MAX_FIELDS_PER_CALL", 48) or 48))


def _parse_unified_extract_payload(raw: str, fields: List[TemplateFieldSpec]) -> Dict[str, Tuple[Optional[str], float]]:
    obj = _parse_extract_json(raw)
    by_id: Dict[str, Tuple[Optional[str], float]] = {}
    allowed = {f.field_id for f in fields}

    # {"fields": {"ph_000": {"value": "...", "confidence": 0.9}}}
    nested = obj.get("fields")
    if isinstance(nested, dict):
        for fid, entry in nested.items():
            if fid not in allowed:
                continue
            if isinstance(entry, dict):
                val = _normalize_extracted_value(entry.get("value"))
                conf = float(entry.get("confidence") or 0.0)
            else:
                val = _normalize_extracted_value(entry)
                conf = 0.5 if val else 0.0
            by_id[fid] = (val, conf)

    # {"ph_000": "value"} legacy flat
    for fid in allowed:
        if fid in by_id:
            continue
        if fid in obj and not isinstance(obj[fid], dict):
            val = _normalize_extracted_value(obj[fid])
            by_id[fid] = (val, 0.5 if val else 0.0)

    for f in fields:
        by_id.setdefault(f.field_id, (None, 0.0))
    return by_id


def extract_fields_unified(
    fields: List[TemplateFieldSpec],
    shared_rag_context: str,
    *,
    user_context: str = "",
    llm=None,
) -> Tuple[Dict[str, Optional[str]], Dict[str, float]]:
    """
    Один (или несколько чанков) вызов LLM: все поля из общего контекста дела.

    Returns:
        (values_by_field_id, confidence_by_field_id)
    """
    ctx = (shared_rag_context or "").strip()
    values: Dict[str, Optional[str]] = {f.field_id: None for f in fields}
    confidences: Dict[str, float] = {f.field_id: 0.0 for f in fields}
    if not fields:
        return values, confidences
    if not ctx:
        return values, confidences

    if llm is None:
        try:
            from app.services.llm_factory import create_legal_llm

            llm = create_legal_llm(provider="yandex", use_rate_limiting=False)
        except Exception as e:
            logger.warning("[draft_field_fill] unified LLM unavailable: %s", e)
            return values, confidences

    from langchain_core.messages import HumanMessage

    chunk_n = _fields_chunk_size()
    for i in range(0, len(fields), chunk_n):
        chunk = fields[i : i + chunk_n]
        field_lines: List[str] = []
        for f in chunk:
            label = (f.semantic_label or f.marker or f.field_id).strip()
            hint = (f.what_to_find or f.retrieval_query or "").strip()
            field_lines.append(
                f'- id="{f.field_id}" | поле: {label} | искать: {hint or "—"}'
            )
        prompt = (
            "Заполни поля юридического шаблона по фрагментам материалов дела.\n"
            "Ответь ТОЛЬКО JSON одного вида:\n"
            '{"fields": {"<field_id>": {"value": "строка" или null, "confidence": 0.0-1.0}, ...}}\n'
            "null и низкая confidence, если в фрагментах нет однозначного значения. Не выдумывай.\n\n"
        )
        if user_context.strip():
            prompt += f"КОНТЕКСТ ЗАПРОСА:\n{user_context[:2000]}\n\n"
        prompt += "ПОЛЯ:\n" + "\n".join(field_lines) + "\n\n"
        prompt += f"ФРАГМЕНТЫ ИЗ ДЕЛА:\n{ctx[:18000]}\n"

        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(raw, list):
                raw = "".join(str(x) for x in raw)
            parsed = _parse_unified_extract_payload(str(raw), chunk)
            for fid, (val, conf) in parsed.items():
                values[fid] = val
                confidences[fid] = conf
        except Exception as e:
            logger.warning("[draft_field_fill] unified extract chunk failed: %s", e)
    return values, confidences


def fields_needing_targeted_retry(
    fields: List[TemplateFieldSpec],
    values: Dict[str, Optional[str]],
    confidences: Dict[str, float],
    *,
    max_fields: Optional[int] = None,
) -> List[TemplateFieldSpec]:
    """Поля без значения или с низкой уверенностью — для точечного RAG-дожима."""
    min_conf = float(getattr(config, "DRAFT_BULK_MIN_CONFIDENCE", 0.25) or 0.25)
    cap = max_fields
    if cap is None:
        cap = int(getattr(config, "DRAFT_BULK_RETRY_MAX_FIELDS", 4) or 4)
    cap = max(0, cap)
    out: List[TemplateFieldSpec] = []
    for f in fields:
        val = values.get(f.field_id)
        conf = float(confidences.get(f.field_id) or 0.0)
        if not val or not str(val).strip():
            out.append(f)
        elif conf < min_conf:
            out.append(f)
        if len(out) >= cap:
            break
    return out


def apply_field_values(indexed_html: str, values_by_field_id: Dict[str, Optional[str]]) -> Tuple[str, int]:
    """
    Подставляет значения в span data-draft-field.
    Убирает обёртку span, оставляя только текст значения (или исходный marker если null).
    """
    if not indexed_html:
        return indexed_html, 0
    applied = 0

    def _repl(m: re.Match) -> str:
        nonlocal applied
        fid = m.group(1)
        inner = m.group(2)
        val = values_by_field_id.get(fid)
        if val is None or (isinstance(val, str) and not str(val).strip()):
            return inner
        applied += 1
        return str(val).strip()

    out = _FIELD_SPAN_RE.sub(_repl, indexed_html)
    return out, applied


def probe_fields_in_case(
    fields: List[TemplateFieldSpec],
    rag_by_field_id: Dict[str, str],
) -> Dict[str, str]:
    """Грубый статус для плана: found_in_case / partial / missing по наличию контекста."""
    status: Dict[str, str] = {}
    for f in fields:
        ctx = (rag_by_field_id.get(f.field_id) or "").strip()
        if len(ctx) < 40:
            status[f.field_id] = "missing"
        elif len(ctx) < 200:
            status[f.field_id] = "partial"
        else:
            status[f.field_id] = "found_in_case"
    return status
