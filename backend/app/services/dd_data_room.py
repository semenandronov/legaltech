"""
DD data-room folder model (lawyer-facing).

Document *types* stay fine-grained (lease / addendum / payment_order / …).
Auto-catalog *folders* are coarser workstreams so related deal papers stay together
(e.g. lease + its addendum + appendix → «Аренда»).
"""
from __future__ import annotations

import re
from typing import Final, Optional, Tuple

from app.services.dd_document_taxonomy import DD_CLASSIFIER_HEAD_CHARS

# Stable bucket ids — persisted in Folder.description as dd_room:<id>
DD_DATA_ROOM_BUCKETS: Final[Tuple[str, ...]] = (
    "lease",
    "supply",
    "services_works",
    "contracts_other",
    "finance",
    "disputes",
    "inbox",
)

DD_DATA_ROOM_LABELS_RU: Final[dict[str, str]] = {
    "lease": "Аренда",
    "supply": "Поставка",
    "services_works": "Услуги и подряд",
    "contracts_other": "Другие договоры",
    "finance": "Финансы",
    "disputes": "Споры и переписка",
    "inbox": "Разобрать",
}

DD_DATA_ROOM_ORDER: Final[Tuple[str, ...]] = DD_DATA_ROOM_BUCKETS

DD_ROOM_MARKER_PREFIX: Final[str] = "dd_room:"
# Legacy auto folders (one folder per doc type) — still treated as system-owned.
DD_LEGACY_TYPE_MARKER_PREFIX: Final[str] = "dd_auto:"

_SUBJECT_HINTS: Final[Tuple[Tuple[str, Tuple[str, ...]], ...]] = (
    ("lease", ("аренд", "lease", "arenda")),
    ("supply", ("постав", "supply", "купл")),
    (
        "services_works",
        ("услуг", "подряд", "строитель", "выполнен", "service", "works", "contractor"),
    ),
)


def _norm(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t.strip())


def dd_room_folder_marker(bucket_id: str) -> str:
    return f"{DD_ROOM_MARKER_PREFIX}{bucket_id}"


def parse_dd_room_folder_marker(description: str | None) -> Optional[str]:
    raw = str(description or "").strip()
    if raw.startswith(DD_ROOM_MARKER_PREFIX):
        bucket = raw[len(DD_ROOM_MARKER_PREFIX) :].strip()
        return bucket if bucket in DD_DATA_ROOM_BUCKETS else None
    return None


def is_dd_system_folder_description(description: str | None) -> bool:
    """True for current data-room folders and legacy per-type auto folders."""
    raw = str(description or "").strip()
    if parse_dd_room_folder_marker(raw):
        return True
    return raw.startswith(DD_LEGACY_TYPE_MARKER_PREFIX)


def resolve_subject_bucket_from_text(*, filename: str = "", text: str = "") -> Optional[str]:
    """Infer thematic bucket from filename + header (for addenda / appendices)."""
    head = _norm((text or "")[:DD_CLASSIFIER_HEAD_CHARS])
    name = _norm(filename)
    blob = f"{name} {head}".strip()
    for bucket_id, cues in _SUBJECT_HINTS:
        if any(cue in blob for cue in cues):
            return bucket_id
    return None


def resolve_data_room_bucket(
    doc_type: str,
    *,
    filename: str = "",
    text: str = "",
) -> str:
    """
    Map fine-grained DD doc type → lawyer data-room folder.

    Addenda / appendices follow subject hints when present; otherwise
    «Другие договоры» (not a separate «ДС» / «Приложение» folder).
    """
    t = str(doc_type or "unknown").strip().lower() or "unknown"

    if t == "lease_commercial":
        return "lease"
    if t == "supply":
        return "supply"
    if t in {"services", "works"}:
        return "services_works"
    if t in {"payment_order", "bank_statement"}:
        return "finance"
    if t in {"litigation", "correspondence"}:
        return "disputes"
    if t == "contract_other":
        # Still try subject cues (e.g. filename says arenda but type stayed other).
        hinted = resolve_subject_bucket_from_text(filename=filename, text=text)
        return hinted or "contracts_other"
    if t in {"addendum", "appendix_spec"}:
        hinted = resolve_subject_bucket_from_text(filename=filename, text=text)
        return hinted or "contracts_other"
    if t in {"other", "unknown"}:
        return "inbox"
    return "inbox"


def data_room_bucket_label(bucket_id: str) -> str:
    return DD_DATA_ROOM_LABELS_RU.get(bucket_id, DD_DATA_ROOM_LABELS_RU["inbox"])


def serialize_dd_data_room() -> dict:
    return {
        "marker_prefix": DD_ROOM_MARKER_PREFIX,
        "folders": [
            {"id": bucket_id, "label": DD_DATA_ROOM_LABELS_RU[bucket_id]}
            for bucket_id in DD_DATA_ROOM_ORDER
        ],
    }
