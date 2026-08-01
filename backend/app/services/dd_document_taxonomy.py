"""
Due diligence document taxonomy v1 (RU commercial contracts).

Used for column templates, zone routing, and eval — not the full litigation taxonomy
in ``document_classifier_service``.
"""
from __future__ import annotations

from typing import Final, Tuple

# Stable ids — persist in processing_progress / API; do not rename without migration.
DD_DOC_TYPES: Final[Tuple[str, ...]] = (
    "lease_commercial",
    "supply",
    "services",
    "works",
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
    "addendum": "Дополнительное соглашение",
    "appendix_spec": "Приложение / спецификация",
    "payment_order": "Платёжное поручение",
    "bank_statement": "Банковская выписка / реестр операций",
    "litigation": "Судебный / процессуальный документ",
    "correspondence": "Письмо / претензия / уведомление",
    "other": "Прочее",
    "unknown": "Не определено",
}

DD_CLASSIFIER_VERSION: Final[str] = "dd_taxonomy_v1"
