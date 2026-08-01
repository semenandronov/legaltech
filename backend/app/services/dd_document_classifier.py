"""
Rules-first DD document classifier (no LLM on ingest hot path).

Phase 1: filename + first ~2k chars of text. Returns ``unknown`` below confidence threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.services.dd_document_taxonomy import DD_CLASSIFIER_VERSION, DD_DOC_TYPES

_DEFAULT_HEAD_CHARS = 2200
_TITLE_ZONE_CHARS = 520
_CONFIDENCE_THRESHOLD = 0.55

_ZONE_FILENAME = "filename"
_ZONE_TITLE = "title"
_ZONE_BODY = "body"

_ZONE_MULTIPLIER = {
    _ZONE_FILENAME: 1.0,
    _ZONE_TITLE: 0.98,
    _ZONE_BODY: 0.92,
}

# A document titled «ДОГОВОР ...» stays a contract even when it mentions appendices,
# payments or disputes further down the page.
_MASTER_CONTRACT_TITLE_CUES = (
    "договор аренды",
    "договор поставки",
    "договор оказания",
    "договор подряда",
)


@dataclass(frozen=True)
class DdClassificationResult:
    doc_type: str
    confidence: float
    source: str
    rationale: str
    version: str = DD_CLASSIFIER_VERSION

    def to_json(self) -> dict:
        return {
            "doc_type": self.doc_type,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "rationale": self.rationale,
            "version": self.version,
        }


@dataclass(frozen=True)
class _Rule:
    doc_type: str
    filename_patterns: Tuple[str, ...]
    text_patterns: Tuple[str, ...]
    weight: float


_RULES: Tuple[_Rule, ...] = (
    _Rule(
        "payment_order",
        ("платеж", "платёж", "payment order", "pp_", "п/п"),
        ("платежное поручение", "0401060", "плательщик", "получатель"),
        0.92,
    ),
    _Rule(
        "bank_statement",
        ("выписк", "statement", "bank_"),
        ("выписка по счету", "остаток на начало", "банковская выписка", "движение средств"),
        0.9,
    ),
    _Rule(
        "addendum",
        ("дс ", "ds_", "дополн", "addendum"),
        ("дополнительное соглашение", "доп. соглашение", "дополнительное соглашение к договору"),
        0.88,
    ),
    _Rule(
        "appendix_spec",
        ("прилож", "spec", "специф"),
        ("приложение №", "спецификация", "перечень товаров", "перечень работ"),
        0.85,
    ),
    _Rule(
        "litigation",
        ("иск", "жалоб", "определен", "решение суда", "a40-", "а40-"),
        (
            "арбитражный суд",
            "исковое заявление",
            "встречный иск",
            "определение суда",
            "судебный акт",
        ),
        0.87,
    ),
    _Rule(
        "correspondence",
        ("письм", "претенз", "уведом", "notice"),
        (
            "претензия",
            "уважаемый",
            "уважаемая",
            "исх. №",
            "настоящим уведомляем",
            "просим",
            "направляем",
        ),
        0.88,
    ),
    _Rule(
        "lease_commercial",
        ("аренд", "lease", "arenda"),
        (
            "договор аренды",
            "арендная плата",
            "арендодатель",
            "арендатор",
            "имущество в аренду",
            "коммерческой аренды",
        ),
        0.86,
    ),
    _Rule(
        "supply",
        ("постав", "supply", "купл"),
        ("договор поставки", "поставщик", "покупатель", "товар в собственность"),
        0.86,
    ),
    _Rule(
        "services",
        ("услуг", "service", "it_", "saas"),
        ("договор оказания услуг", "исполнитель оказывает услуги", "заказчик услуг"),
        0.84,
    ),
    _Rule(
        "works",
        ("подряд", "works", "contractor"),
        ("договор подряда", "подрядчик", "результат работ", "выполнение работ"),
        0.84,
    ),
)

# Document *form* wins over contract *subject* (письмо об аренде → correspondence).
_FORM_TYPES = frozenset(
    {
        "payment_order",
        "bank_statement",
        "addendum",
        "appendix_spec",
        "litigation",
        "correspondence",
    }
)
_SUBJECT_TYPES = frozenset(
    {
        "lease_commercial",
        "supply",
        "services",
        "works",
    }
)


def _norm(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t.strip())


def _score_rule(rule: _Rule, *, name: str, hint: str, head: str) -> Tuple[float, str, List[str]]:
    score = 0.0
    zone = ""
    reasons: List[str] = []
    for pat in rule.filename_patterns:
        if pat in name or pat in hint:
            score = rule.weight * _ZONE_MULTIPLIER[_ZONE_FILENAME]
            zone = _ZONE_FILENAME
            reasons = [f"filename:{pat}"]
            break
    for pat in rule.text_patterns:
        # Zone is decided by where the match starts, so a cue straddling the title
        # boundary is still found.
        idx = head.find(pat)
        if idx < 0:
            continue
        pat_zone = _ZONE_TITLE if idx < _TITLE_ZONE_CHARS else _ZONE_BODY
        pat_score = rule.weight * _ZONE_MULTIPLIER[pat_zone]
        if pat_score > score:
            score = pat_score
            zone = pat_zone
            reasons = [f"{pat_zone}:{pat}"]
    return score, zone, reasons


def _best_among(
    rules: Tuple[_Rule, ...],
    allowed: frozenset,
    *,
    name: str,
    hint: str,
    head: str,
) -> Tuple[str, float, str, List[str]]:
    best_type = "unknown"
    best_score = 0.0
    best_zone = ""
    best_reasons: List[str] = []
    for rule in rules:
        if rule.doc_type not in allowed:
            continue
        score, zone, reasons = _score_rule(rule, name=name, hint=hint, head=head)
        if score > best_score:
            best_score = score
            best_type = rule.doc_type
            best_zone = zone
            best_reasons = reasons
    return best_type, best_score, best_zone, best_reasons


def classify_dd_document(
    *,
    text: str,
    filename: str = "",
    title_hint: Optional[str] = None,
    head_chars: int = _DEFAULT_HEAD_CHARS,
) -> DdClassificationResult:
    """Classify a document for DD tabular routing."""
    head = _norm((text or "")[:head_chars])
    name = _norm(filename)
    hint = _norm(title_hint or "")

    form_type, form_score, form_zone, form_reasons = _best_among(
        _RULES, _FORM_TYPES, name=name, hint=hint, head=head
    )
    subject_type, subject_score, subject_zone, subject_reasons = _best_among(
        _RULES, _SUBJECT_TYPES, name=name, hint=hint, head=head
    )

    # A master contract title beats form cues found mid-document; form cues in the
    # title zone win instead (a letter about a lease is correspondence).
    title = head[:_TITLE_ZONE_CHARS]
    if (
        subject_score >= _CONFIDENCE_THRESHOLD
        and subject_zone in (_ZONE_TITLE, _ZONE_FILENAME)
        and form_zone == _ZONE_BODY
        and any(cue in title for cue in _MASTER_CONTRACT_TITLE_CUES)
    ):
        return DdClassificationResult(
            doc_type=subject_type if subject_type in DD_DOC_TYPES else "other",
            confidence=subject_score,
            source="rules",
            rationale="; ".join(subject_reasons + ["title_master_contract"])
            or "subject_match",
        )

    if form_score >= _CONFIDENCE_THRESHOLD:
        return DdClassificationResult(
            doc_type=form_type if form_type in DD_DOC_TYPES else "other",
            confidence=form_score,
            source="rules",
            rationale="; ".join(form_reasons) or "form_match",
        )

    if subject_score >= _CONFIDENCE_THRESHOLD:
        return DdClassificationResult(
            doc_type=subject_type if subject_type in DD_DOC_TYPES else "other",
            confidence=subject_score,
            source="rules",
            rationale="; ".join(subject_reasons) or "subject_match",
        )

    return DdClassificationResult(
        doc_type="unknown",
        confidence=max(form_score, subject_score),
        source="rules",
        rationale="below_threshold",
    )


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
