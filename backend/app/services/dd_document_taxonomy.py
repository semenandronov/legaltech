"""
Due diligence document taxonomy v1 (RU commercial contracts).

Used for column templates, zone routing, case file library UI (type badges/filters),
and eval — not the full litigation taxonomy in ``document_classifier_service``.

Lawyer-facing *folders* live in ``dd_data_room`` (thematic data-room buckets),
not 1:1 with these fine-grained types.
"""
from __future__ import annotations

from typing import Any, Dict, Final, List, Tuple

# Stable ids — persist in processing_progress / API; do not rename without migration.
DD_DOC_TYPES: Final[Tuple[str, ...]] = (
    "lease_commercial",
    "supply",
    "services",
    "works",
    "contract_other",
    "addendum",
    "appendix_spec",
    "payment_order",
    "bank_statement",
    "litigation",
    "correspondence",
    "other",
    "unknown",
)

DD_DOC_TYPE_LABELS_RU: Final[dict[str, str]] = {
    "lease_commercial": "Договор / документ по коммерческой аренде",
    "supply": "Договор поставки / документ по поставке",
    "services": "Договор оказания услуг",
    "works": "Договор подряда / выполнения работ",
    "contract_other": "Договор (прочее / тема не уточнена)",
    "addendum": "Дополнительное соглашение",
    "appendix_spec": "Приложение / спецификация",
    "payment_order": "Платёжное поручение",
    "bank_statement": "Банковская выписка / реестр операций",
    "litigation": "Судебный / процессуальный документ",
    "correspondence": "Письмо / претензия / уведомление",
    "other": "Прочее",
    "unknown": "Не определено",
}

# Short labels for table badges / filter chips / virtual folders.
DD_DOC_TYPE_SHORT_LABELS_RU: Final[dict[str, str]] = {
    "lease_commercial": "Аренда",
    "supply": "Поставка",
    "services": "Услуги",
    "works": "Подряд",
    "contract_other": "Договор",
    "addendum": "ДС",
    "appendix_spec": "Приложение",
    "payment_order": "Платёжка",
    "bank_statement": "Выписка",
    "litigation": "Суд",
    "correspondence": "Переписка",
    "other": "Прочее",
    "unknown": "Не определено",
}

# Preferred filter / folder order in the case library UI.
DD_DOC_TYPE_FILTER_ORDER: Final[Tuple[str, ...]] = (
    "lease_commercial",
    "supply",
    "services",
    "works",
    "contract_other",
    "addendum",
    "appendix_spec",
    "payment_order",
    "bank_statement",
    "litigation",
    "correspondence",
    "other",
    "unknown",
)

DD_CLASSIFIER_VERSION: Final[str] = "dd_taxonomy_v1_1"
DD_NEEDS_REVIEW_CONFIDENCE: Final[float] = 0.55
# Classification evidence: filename + first N chars of OCR text (not mid-document).
DD_CLASSIFIER_HEAD_CHARS: Final[int] = 150

# Legacy per-type auto folders (superseded by dd_room:* data-room buckets).
DD_AUTO_FOLDER_MARKER_PREFIX: Final[str] = "dd_auto:"


def is_valid_dd_doc_type(doc_type: str | None) -> bool:
    return bool(doc_type) and str(doc_type).strip() in DD_DOC_TYPES


def dd_doc_type_label(doc_type: str | None, *, short: bool = False) -> str:
    key = str(doc_type or "unknown").strip() or "unknown"
    catalog = DD_DOC_TYPE_SHORT_LABELS_RU if short else DD_DOC_TYPE_LABELS_RU
    return catalog.get(key, catalog["unknown"])


def dd_auto_folder_marker(doc_type: str) -> str:
    """Legacy marker — prefer ``dd_data_room.dd_room_folder_marker`` for new folders."""
    return f"{DD_AUTO_FOLDER_MARKER_PREFIX}{doc_type}"


def parse_dd_auto_folder_marker(description: str | None) -> str | None:
    raw = str(description or "").strip()
    if not raw.startswith(DD_AUTO_FOLDER_MARKER_PREFIX):
        return None
    doc_type = raw[len(DD_AUTO_FOLDER_MARKER_PREFIX) :].strip()
    return doc_type if is_valid_dd_doc_type(doc_type) else None


def serialize_dd_taxonomy() -> Dict[str, Any]:
    """Payload for GET taxonomy — types + lawyer data-room folder model."""
    from app.services.dd_data_room import serialize_dd_data_room

    types: List[Dict[str, str]] = []
    for doc_type in DD_DOC_TYPE_FILTER_ORDER:
        types.append(
            {
                "id": doc_type,
                "label": DD_DOC_TYPE_LABELS_RU[doc_type],
                "short_label": DD_DOC_TYPE_SHORT_LABELS_RU[doc_type],
            }
        )
    return {
        "version": DD_CLASSIFIER_VERSION,
        "needs_review_confidence": DD_NEEDS_REVIEW_CONFIDENCE,
        "classifier_head_chars": DD_CLASSIFIER_HEAD_CHARS,
        "types": types,
        "data_room": serialize_dd_data_room(),
    }
