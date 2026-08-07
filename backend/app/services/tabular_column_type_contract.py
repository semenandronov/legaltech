"""
Tabular column type contract — canonical types, inference, and strict normalization.

Single source of truth for:
- allowed column_type values
- heuristic type inference at column creation
- deterministic post-LLM value normalization (invalid → «—»)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.date_validator import extract_parseable_date_from_text, parse_and_normalize_date
from app.services.tabular_extraction_policy import (
    TABULAR_NA_VALUE,
    coerce_source_references,
    compact_extraction_provenance,
    ensure_na_reasoning,
    is_explicit_na_token,
    is_na_cell_value,
)

TABULAR_COLUMN_TYPES: Tuple[str, ...] = (
    "text",
    "number",
    "currency",
    "yes_no",
    "date",
    "tag",
    "verbatim",
    "manual_input",
)

# Legacy DB rows may still store removed types; treat them as text at runtime.
_LEGACY_COLUMN_TYPE_ALIASES: Dict[str, str] = {"document_type": "text"}

_AI_COLUMN_TYPES: Tuple[str, ...] = tuple(t for t in TABULAR_COLUMN_TYPES if t != "manual_input")

_BLANK_PLACEHOLDER_RE = re.compile(r"^[_\-\.\s\d«»«»гГ\.]+$")


@dataclass(frozen=True)
class ColumnTypeInference:
    column_type: str
    confidence: float
    reason: str
    source: str = "heuristic"


def validate_column_type(column_type: str) -> str:
    normalized = (column_type or "").strip().lower()
    normalized = _LEGACY_COLUMN_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in TABULAR_COLUMN_TYPES:
        allowed = ", ".join(TABULAR_COLUMN_TYPES)
        raise ValueError(f"Invalid column_type '{column_type}'. Allowed: {allowed}")
    return normalized


def validate_column_config(column_type: str, column_config: Optional[Dict[str, Any]]) -> None:
    cfg = column_config if isinstance(column_config, dict) else {}
    if column_type == "tag":
        options = cfg.get("options") or []
        labels = [str(o.get("label", "")).strip() for o in options if isinstance(o, dict)]
        labels = [label for label in labels if label]
        if not labels:
            raise ValueError("column_type 'tag' requires column_config.options with at least one label")

    raw_zones = cfg.get("preferred_zones")
    if raw_zones is None:
        pass
    else:
        from app.services.document_zones import DOCUMENT_ZONE_SET, normalize_zone

        if isinstance(raw_zones, str):
            values = [p.strip() for p in raw_zones.split(",") if p.strip()]
        elif isinstance(raw_zones, (list, tuple)):
            values = list(raw_zones)
        else:
            raise ValueError("column_config.preferred_zones must be a list or comma-separated string")
        if values:
            bad = []
            for v in values:
                z = normalize_zone(v)
                if not z or z not in DOCUMENT_ZONE_SET:
                    bad.append(str(v))
            if bad:
                allowed = ", ".join(sorted(DOCUMENT_ZONE_SET))
                raise ValueError(
                    f"Invalid preferred_zones {bad}. Allowed: {allowed}"
                )

    raw_field = cfg.get("field_id")
    if raw_field is not None and str(raw_field).strip():
        from app.services.contract_field_catalog import normalize_field_id, known_field_ids

        if normalize_field_id(raw_field) is None:
            allowed = ", ".join(known_field_ids())
            raise ValueError(
                f"Invalid field_id '{raw_field}'. Allowed: {allowed}"
            )

    raw_kind = cfg.get("column_kind")
    if raw_kind is not None and str(raw_kind).strip():
        from app.services.tabular_column_kind import COLUMN_KINDS, normalize_column_kind

        if normalize_column_kind(raw_kind) is None:
            allowed = ", ".join(COLUMN_KINDS)
            raise ValueError(
                f"Invalid column_kind '{raw_kind}'. Allowed: {allowed}"
            )

    # Structural validation only (source existence / cycles checked in service layer).
    from app.services.tabular_column_condition import parse_run_condition
    from app.services.tabular_cell_flags import parse_flag_rules

    parse_run_condition(cfg)
    parse_flag_rules(cfg)


def _combined_text(label: str, prompt: str) -> str:
    return f"{(label or '').strip()} {(prompt or '').strip()}".lower()


def _score_patterns(text: str, patterns: List[Tuple[str, float]]) -> float:
    score = 0.0
    for pattern, weight in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            score += weight
    return score


def infer_column_type_heuristic(column_label: str, prompt: str) -> ColumnTypeInference:
    """
    Deterministic column type inference from label + extraction question.

    Used at column creation so the stored type matches user intent (e.g. date, not verbatim).
    """
    text = _combined_text(column_label, prompt)
    if not text.strip():
        return ColumnTypeInference("text", 0.5, "empty input", "heuristic")

    scores: Dict[str, float] = {t: 0.0 for t in _AI_COLUMN_TYPES}

    scores["verbatim"] = _score_patterns(
        text,
        [
            (r"\bдословн", 4.0),
            (r"\bverbatim\b", 4.0),
            (r"точн(ая|ую)\s+цитат", 4.0),
            (r"\bцитат[аыу]?\b", 2.5),
            (r"\bquote\b", 3.0),
            (r"word\s+for\s+word", 3.0),
            (r"выпиши\s+текст", 3.0),
            (r"буквально", 2.0),
        ],
    )
    scores["text"] += _score_patterns(
        text,
        [
            (r"тип\s+документ", 4.0),
            (r"вид\s+документ", 4.0),
            (r"\bdocument\s+type\b", 4.0),
            (r"категори[яи]\s+документ", 3.5),
            (r"классифицир", 2.5),
            (r"к\s+какому\s+типу\s+относ", 3.0),
        ],
    )
    scores["yes_no"] = _score_patterns(
        text,
        [
            (r"\bесть\s+ли\b", 3.5),
            (r"\bимеется\s+ли\b", 3.5),
            (r"\bуказан\s+ли\b", 3.0),
            (r"\bявляется\s+ли\b", 3.0),
            (r"\bwhether\b", 3.0),
            (r"\byes/no\b", 3.5),
            (r"\bда/нет\b", 3.5),
            (r"\bналичи[ея]\b", 2.0),
        ],
    )
    scores["date"] = _score_patterns(
        text,
        [
            (r"\bдата\b", 4.0),
            (r"\bdate\b", 3.5),
            (r"\bкогда\b", 2.5),
            (r"\bсрок\b", 2.5),
            (r"\bdeadline\b", 2.5),
            (r"подписан", 3.0),
            (r"заключен", 2.5),
            (r"вступлен", 2.5),
            (r"истечен", 2.0),
            (r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", 2.0),
        ],
    )
    scores["currency"] = _score_patterns(
        text,
        [
            (r"\bсумм[аы]?\b", 3.0),
            (r"\bруб", 3.5),
            (r"\busd\b", 3.0),
            (r"\beur\b", 3.0),
            (r"\bвалют", 2.5),
            (r"\bстоимост", 2.5),
            (r"\bцена\b", 2.0),
            (r"\bнеустойк", 2.0),
            (r"\bштраф", 2.0),
            (r"\b₽\b", 3.0),
            (r"\$", 2.5),
        ],
    )
    scores["number"] = _score_patterns(
        text,
        [
            (r"\bчисл[оа]?\b", 3.0),
            (r"\bколичеств", 3.0),
            (r"\bpercent\b", 2.5),
            (r"\bпроцент", 2.5),
            (r"\b%\b", 2.0),
            (r"\bномер\b", 1.5),
            (r"\bnumber\b", 2.5),
        ],
    )
    scores["tag"] = _score_patterns(
        text,
        [
            (r"\bтег\b", 3.0),
            (r"\bкатегори[яи]\b", 2.0),
            (r"\bclassif", 2.0),
            (r"\bстатус\b", 2.0),
            (r"\boption\b", 1.5),
        ],
    )

    # Reduce yes_no when date signals dominate (e.g. "дата подписания", not "подписан ли")
    if scores["date"] >= 3.0 and scores["yes_no"] > 0:
        scores["yes_no"] *= 0.35

    # Currency beats generic number when both match
    if scores["currency"] > 0 and scores["number"] > 0:
        scores["number"] *= 0.5

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    if best_score <= 0:
        return ColumnTypeInference("text", 0.55, "no strong type signal; default text", "heuristic")

    confidence = min(0.97, 0.62 + best_score * 0.08)
    return ColumnTypeInference(
        column_type=best_type,
        confidence=round(confidence, 3),
        reason=f"strongest signal for '{best_type}' (score={best_score:.1f})",
        source="heuristic",
    )


def is_blank_placeholder(value: str) -> bool:
    stripped = (value or "").strip()
    if not stripped or is_na_cell_value(stripped):
        return True
    if stripped in ("—", "-", "–"):
        return True
    if _BLANK_PLACEHOLDER_RE.match(stripped) and re.search(r"_{2,}", stripped):
        return True
    return False


def _match_tag_option(raw: str, options: List[str]) -> Optional[str]:
    candidate = raw.strip()
    if not candidate:
        return None
    lower_map = {opt.lower(): opt for opt in options}
    if candidate.lower() in lower_map:
        return lower_map[candidate.lower()]
    for opt in options:
        if opt.lower() in candidate.lower() or candidate.lower() in opt.lower():
            return opt
    return None


def strict_normalize_cell_value(
    raw_value: Optional[str],
    column_type: str,
    *,
    column_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Normalize a single cell_value for column_type.

    Returns (cell_value, normalized_value, rejection_reason).
    rejection_reason is set when value is coerced to «—».
    """
    column_type = validate_column_type(column_type)
    value = (raw_value or "").strip()

    # Explicit «—» / legacy N/A — canonicalize without a validation rejection.
    if is_explicit_na_token(value):
        return TABULAR_NA_VALUE, TABULAR_NA_VALUE, None

    if is_blank_placeholder(value):
        return TABULAR_NA_VALUE, TABULAR_NA_VALUE, "blank or placeholder value"

    if column_type == "date":
        extracted = extract_parseable_date_from_text(value)
        if extracted:
            return extracted, extracted, None
        try:
            normalized = parse_and_normalize_date(value)
            datetime.strptime(normalized, "%Y-%m-%d")
            return normalized, normalized, None
        except Exception:
            return TABULAR_NA_VALUE, TABULAR_NA_VALUE, f"invalid date format: {value!r}"

    if column_type == "number":
        from app.services.tabular_review_models import validate_number

        try:
            normalized = validate_number(value)
            return normalized, normalized, None
        except ValueError:
            return TABULAR_NA_VALUE, TABULAR_NA_VALUE, f"invalid number: {value!r}"

    if column_type == "currency":
        from app.services.ru_contract_value_normalize import normalize_ru_money_amount
        from app.services.tabular_review_models import validate_currency

        try:
            normalized_num = validate_currency(value)
            display = normalize_ru_money_amount(value) or value
            return display, normalized_num, None
        except ValueError:
            return TABULAR_NA_VALUE, TABULAR_NA_VALUE, f"invalid currency: {value!r}"

    if column_type == "yes_no":
        from app.services.tabular_review_models import (
            YES_NO_UNKNOWN,
            validate_yes_no,
            yes_no_normalized_key,
        )

        validated = validate_yes_no(value)
        if validated == YES_NO_UNKNOWN:
            return TABULAR_NA_VALUE, TABULAR_NA_VALUE, f"ambiguous yes/no answer: {value!r}"
        norm_key = yes_no_normalized_key(validated)
        return validated, norm_key, None

    if column_type == "tag":
        cfg = column_config if isinstance(column_config, dict) else {}
        options_raw = cfg.get("options") or []
        labels = [
            str(item.get("label", "")).strip()
            for item in options_raw
            if isinstance(item, dict) and str(item.get("label", "")).strip()
        ]
        if not labels:
            return value, value.lower(), None
        matched = _match_tag_option(value, labels)
        if matched is None:
            return TABULAR_NA_VALUE, TABULAR_NA_VALUE, f"value not in tag options: {value!r}"
        return matched, matched.lower(), None

    # text, verbatim, manual_input
    return value, value.lower(), None


def map_llm_field_aliases(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Map common LLM field name variants to canonical extraction keys."""
    out = dict(result_dict)
    if not out.get("cell_value"):
        for alias in ("answer", "value", "result", "text"):
            if out.get(alias):
                out["cell_value"] = out[alias]
                break
    if not out.get("reasoning"):
        for alias in ("explanation", "rationale"):
            if out.get(alias):
                out["reasoning"] = out[alias]
                break
    if not out.get("source_references"):
        for alias in ("citations", "sources"):
            if out.get(alias):
                out["source_references"] = out[alias]
                break
    return out


def finalize_extraction_dict(
    result_dict: Dict[str, Any],
    *,
    column_type: str,
    column_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Apply alias mapping + strict type normalization to a raw LLM extraction dict.
    """
    column_type = validate_column_type(column_type)
    normalized = map_llm_field_aliases(result_dict)

    raw_cell = normalized.get("cell_value")
    raw_str = str(raw_cell) if raw_cell is not None else ""
    if is_blank_placeholder(raw_str) and not normalized.get("reasoning"):
        normalized["reasoning"] = (
            "В документе найдено только пустое поле-шаблон (прочерки, подчёркивания). "
            "Конкретная информация не указана."
        )

    cell_value, norm_value, rejection = strict_normalize_cell_value(
        raw_str,
        column_type,
        column_config=column_config,
    )

    if is_na_cell_value(cell_value):
        cell_value = TABULAR_NA_VALUE
        norm_value = TABULAR_NA_VALUE
        normalized["reasoning"] = ensure_na_reasoning(
            normalized.get("reasoning") if isinstance(normalized.get("reasoning"), str) else None,
            rejection=rejection,
        )

    normalized["cell_value"] = cell_value
    normalized["normalized_value"] = norm_value
    normalized["column_type"] = column_type
    normalized["source_references"] = coerce_source_references(normalized.get("source_references"))
    normalized = compact_extraction_provenance(normalized)

    if column_type == "verbatim" and not normalized.get("verbatim_extract") and not is_na_cell_value(
        cell_value
    ):
        normalized["verbatim_extract"] = cell_value

    normalized.setdefault("confidence", 0.8)
    normalized.setdefault("extraction_method", "llm_rag")

    return normalized
