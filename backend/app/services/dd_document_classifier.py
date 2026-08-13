"""
Rules-first DD document classifier (no LLM on ingest hot path).

Evidence window: filename + first ~150 chars of text (title/header only).
Mid-document mentions of «приложение №» must not reclassify a master contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from app.services.dd_document_taxonomy import (
    DD_CLASSIFIER_HEAD_CHARS,
    DD_CLASSIFIER_VERSION,
    DD_DOC_TYPES,
    DD_NEEDS_REVIEW_CONFIDENCE,
    is_valid_dd_doc_type,
)

_CONFIDENCE_THRESHOLD = DD_NEEDS_REVIEW_CONFIDENCE

_ZONE_FILENAME = "filename"
_ZONE_HEAD = "head"

# Explicit subject contracts in the header / filename.
_SUBJECT_CUES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "lease_commercial",
        (
            "договор аренды",
            "аренды недвижимого",
            "аренды движимого",
            "арендная плата",
            "арендодатель",
            "арендатор",
        ),
    ),
    (
        "supply",
        (
            "договор поставки",
            "договор купли-продажи",
            "поставщик",
            "покупатель",
        ),
    ),
    (
        "services",
        (
            "договор оказания услуг",
            "договор на оказание услуг",
            "оказания услуг",
        ),
    ),
    (
        "works",
        (
            "договор подряда",
            "договор выполнения работ",
            "подрядчик",
            "выполнение работ",
        ),
    ),
)

_FORM_CUES: Tuple[Tuple[str, Tuple[str, ...], float], ...] = (
    ("payment_order", ("платежное поручение", "0401060"), 0.92),
    ("bank_statement", ("выписка по счету", "банковская выписка", "остаток на начало"), 0.9),
    (
        "addendum",
        ("дополнительное соглашение", "доп. соглашение", "дополнительное соглашение к"),
        0.9,
    ),
    (
        "appendix_spec",
        ("приложение №", "приложение no", "спецификация к договору", "спецификация"),
        0.88,
    ),
    (
        "litigation",
        (
            "арбитражный суд",
            "исковое заявление",
            "встречный иск",
            "определение суда",
            "возражения",
            "судебный акт",
        ),
        0.9,
    ),
    (
        "correspondence",
        (
            "претензия",
            "уважаемый",
            "уважаемая",
            "исх. №",
            "настоящим уведомляем",
            "уведомление о",
        ),
        0.88,
    ),
)

_FILENAME_FORM: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("payment_order", ("платеж", "платёж", "payment order", "pp_", "п/п")),
    ("bank_statement", ("выписк", "statement", "bank_")),
    ("addendum", ("дс ", "дс_", "ds_", "дополн", "addendum", "допсоглаш")),
    ("appendix_spec", ("прилож", "spec", "специф", "appendix")),
    ("litigation", ("иск", "жалоб", "возражен", "определен", "решение суда", "a40-", "а40-")),
    ("correspondence", ("письм", "претенз", "уведом", "notice")),
)

_FILENAME_SUBJECT: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("lease_commercial", ("аренд", "lease", "arenda")),
    ("supply", ("постав", "supply", "купл-продаж")),
    ("services", ("услуг", "service")),
    ("works", ("подряд", "works", "строитель")),
)

_CONTRACT_NAME_RE = re.compile(r"(?i)(?:^|[^a-zа-яё])(?:договор|dogovor|contract)(?:[^a-zа-яё]|$)")
_CONTRACT_HEAD_RE = re.compile(r"(?i)\bдоговор\b")
_GENERIC_NAME_RE = re.compile(
    r"(?i)^(scan|скан|img|image|photo|фото|document|документ|file|файл|untitled|"
    r"безымян|новый\s*документ|new\s*document|copy\s*of|dsc_|whatsapp|telegram|"
    r"screenshot|снимок|doc\d*|file\d*)"
)


@dataclass(frozen=True)
class DdClassificationResult:
    doc_type: str
    confidence: float
    source: str
    rationale: str
    version: str = DD_CLASSIFIER_VERSION

    @property
    def needs_review(self) -> bool:
        return dd_classification_needs_review(
            self.doc_type,
            self.confidence,
            self.source,
        )

    def to_json(self) -> dict:
        return {
            "doc_type": self.doc_type,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "rationale": self.rationale,
            "version": self.version,
            "needs_review": self.needs_review,
        }


def _norm(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t.strip())


def _first_match(blob: str, cues: Tuple[str, ...]) -> Optional[str]:
    for cue in cues:
        if cue in blob:
            return cue
    return None


def _match_group(
    groups: Tuple[Tuple[str, Tuple[str, ...]], ...],
    blob: str,
) -> Tuple[str, Optional[str]]:
    for doc_type, cues in groups:
        hit = _first_match(blob, cues)
        if hit:
            return doc_type, hit
    return "unknown", None


def _looks_like_contract(*, name: str, head: str) -> bool:
    if _CONTRACT_NAME_RE.search(name):
        return True
    # Header often has OCR junk before the title — still require «договор» early.
    return bool(_CONTRACT_HEAD_RE.search(head[: min(len(head), DD_CLASSIFIER_HEAD_CHARS)]))


def classify_dd_document(
    *,
    text: str,
    filename: str = "",
    title_hint: Optional[str] = None,
    head_chars: int = DD_CLASSIFIER_HEAD_CHARS,
) -> DdClassificationResult:
    """
    Classify using filename + first ``head_chars`` of text only.

    Order: payment/bank/litigation/correspondence/addendum → appendix (only if
    not a master contract) → subject contract → generic contract → other/unknown.
    """
    head = _norm((text or "")[: max(80, int(head_chars))])
    name = _norm(filename)
    hint = _norm(title_hint or "")
    name_blob = f"{name} {hint}".strip()

    # 1) Strong form from filename or head (not appendix yet).
    for doc_type, cues, weight in _FORM_CUES:
        if doc_type == "appendix_spec":
            continue
        hit_name = _first_match(name_blob, _FILENAME_FORM_DICT.get(doc_type, ()))
        hit_head = _first_match(head, cues)
        if hit_name or hit_head:
            reason = f"filename:{hit_name}" if hit_name else f"head:{hit_head}"
            return DdClassificationResult(
                doc_type=doc_type,
                confidence=weight if hit_head else weight * 0.98,
                source="rules",
                rationale=reason,
            )

    is_contract = _looks_like_contract(name=name_blob, head=head)

    # 2) Appendix only when the *document itself* is an appendix — never when
    # the header is already a master «ДОГОВОР …».
    if not is_contract:
        app_name = _first_match(name_blob, _FILENAME_FORM_DICT["appendix_spec"])
        app_head = _first_match(
            head,
            ("приложение №", "приложение no", "спецификация к договору", "спецификация"),
        )
        # Prefer explicit appendix title at start.
        if app_name or (app_head and (head.startswith("приложен") or "спецификац" in head[:40])):
            return DdClassificationResult(
                doc_type="appendix_spec",
                confidence=0.88,
                source="rules",
                rationale=f"filename:{app_name}" if app_name else f"head:{app_head}",
            )
        if app_head and head.find(app_head) < 40:
            return DdClassificationResult(
                doc_type="appendix_spec",
                confidence=0.86,
                source="rules",
                rationale=f"head:{app_head}",
            )

    # 3) Subject matter for contracts (and informative filenames).
    subj, subj_hit = _match_group(_FILENAME_SUBJECT, name_blob)
    zone = _ZONE_FILENAME
    if subj == "unknown":
        subj, subj_hit = _match_group(_SUBJECT_CUES, head)
        zone = _ZONE_HEAD
    if subj != "unknown" and subj_hit:
        # Filename-only subject without contract cue → still OK for clear names.
        if is_contract or zone == _ZONE_FILENAME:
            return DdClassificationResult(
                doc_type=subj,
                confidence=0.9 if zone == _ZONE_FILENAME else 0.86,
                source="rules",
                rationale=f"{zone}:{subj_hit}",
            )

    # 4) Generic contract (diverse commercial agreements).
    if is_contract:
        return DdClassificationResult(
            doc_type="contract_other",
            confidence=0.8,
            source="rules",
            rationale="contract_header_or_filename",
        )

    # 5) Late appendix cue without contract header (standalone spec file with OCR junk).
    app_head = _first_match(head, ("приложение №", "спецификация"))
    if app_head:
        return DdClassificationResult(
            doc_type="appendix_spec",
            confidence=0.7,
            source="rules",
            rationale=f"head:{app_head}",
        )

    return DdClassificationResult(
        doc_type="unknown",
        confidence=0.0,
        source="rules",
        rationale="below_threshold",
    )


_FILENAME_FORM_DICT = {doc_type: cues for doc_type, cues in _FILENAME_FORM}


def save_dd_classification_on_file(file_model, result: DdClassificationResult) -> None:
    """Persist DD classification on File columns + mirror in processing_progress."""
    file_model.dd_doc_type = result.doc_type
    file_model.dd_doc_type_confidence = f"{result.confidence:.4f}"
    file_model.dd_doc_type_source = result.source

    progress = file_model.processing_progress
    if not isinstance(progress, dict):
        progress = {}
    progress = dict(progress)
    progress["dd_classification"] = result.to_json()
    file_model.processing_progress = progress


def get_file_dd_doc_type(file_model) -> Optional[str]:
    """Return persisted DD type or fall back to processing_progress mirror."""
    direct = getattr(file_model, "dd_doc_type", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    progress = getattr(file_model, "processing_progress", None)
    if isinstance(progress, dict):
        payload = progress.get("dd_classification")
        if isinstance(payload, dict):
            t = str(payload.get("doc_type") or "").strip()
            if t:
                return t
    return None


def parse_dd_confidence(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def dd_classification_needs_review(
    doc_type: Optional[str],
    confidence: Optional[float],
    source: Optional[str] = None,
) -> bool:
    """True when a lawyer should confirm the auto label."""
    if str(source or "").strip().lower() == "user":
        return False
    t = str(doc_type or "unknown").strip() or "unknown"
    if t in {"unknown", "other"}:
        return True
    if confidence is None:
        return True
    return float(confidence) < DD_NEEDS_REVIEW_CONFIDENCE


def apply_user_dd_doc_type(file_model, doc_type: str) -> DdClassificationResult:
    """Persist a lawyer override as the canonical DD type (source=user)."""
    cleaned = str(doc_type or "").strip()
    if not is_valid_dd_doc_type(cleaned):
        raise ValueError(f"invalid_dd_doc_type:{cleaned}")
    result = DdClassificationResult(
        doc_type=cleaned,
        confidence=1.0,
        source="user",
        rationale="user_override",
    )
    save_dd_classification_on_file(file_model, result)
    return result


def file_dd_classification_payload(file_model) -> dict:
    """Stable API shape for case file library rows."""
    from app.services.dd_document_taxonomy import dd_doc_type_label

    doc_type = get_file_dd_doc_type(file_model) or "unknown"
    confidence = parse_dd_confidence(getattr(file_model, "dd_doc_type_confidence", None))
    source = getattr(file_model, "dd_doc_type_source", None)
    if isinstance(source, str):
        source = source.strip() or None
    else:
        source = None
    progress = getattr(file_model, "processing_progress", None)
    rationale = None
    if isinstance(progress, dict):
        payload = progress.get("dd_classification")
        if isinstance(payload, dict):
            rationale = payload.get("rationale")
            if confidence is None:
                confidence = parse_dd_confidence(payload.get("confidence"))
            if not source:
                source = str(payload.get("source") or "").strip() or None
    needs_review = dd_classification_needs_review(doc_type, confidence, source)
    return {
        "dd_doc_type": doc_type,
        "dd_doc_type_label": dd_doc_type_label(doc_type),
        "dd_doc_type_short_label": dd_doc_type_label(doc_type, short=True),
        "dd_doc_type_confidence": confidence,
        "dd_doc_type_source": source,
        "dd_needs_review": needs_review,
        "dd_classification_rationale": rationale,
    }


def reclassify_file_from_text(
    file_model,
    *,
    text: Optional[str] = None,
    filename: Optional[str] = None,
) -> DdClassificationResult:
    """Re-run rules classifier; does not overwrite a user override."""
    existing_source = str(getattr(file_model, "dd_doc_type_source", None) or "").strip().lower()
    if existing_source == "user":
        return DdClassificationResult(
            doc_type=get_file_dd_doc_type(file_model) or "unknown",
            confidence=parse_dd_confidence(getattr(file_model, "dd_doc_type_confidence", None))
            or 1.0,
            source="user",
            rationale="kept_user_override",
        )
    result = classify_dd_document(
        text=text if text is not None else (getattr(file_model, "original_text", None) or ""),
        filename=filename if filename is not None else (getattr(file_model, "filename", None) or ""),
    )
    save_dd_classification_on_file(file_model, result)
    return result


def filename_looks_generic(filename: str) -> bool:
    """True for dump names like Scan_1.pdf / Безымянный.pdf."""
    stem = re.sub(r"\.[^.]+$", "", (filename or "").strip())
    stem = stem.replace("_", " ").replace("-", " ").strip()
    if not stem:
        return True
    if _GENERIC_NAME_RE.match(stem):
        return True
    # Pure numbers / very short codes
    compact = re.sub(r"\s+", "", stem)
    if len(compact) <= 2:
        return True
    if re.fullmatch(r"\d{1,4}", compact):
        return True
    return False
