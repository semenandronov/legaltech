"""
Stable field_id catalog + RU DD column templates (phase 3.4).

``column_config.field_id`` maps a tabular column onto ``File.contract_facts.fields``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# field_id → (default column_type, RU label, extraction prompt)
CONTRACT_FIELD_CATALOG: Dict[str, Dict[str, str]] = {
    "doc_number": {
        "column_type": "text",
        "label": "Номер договора",
        "prompt": "Укажи номер этого договора / дополнительного соглашения.",
    },
    "doc_date": {
        "column_type": "date",
        "label": "Дата документа",
        "prompt": "Дата подписания или составления этого документа (YYYY-MM-DD).",
    },
    "party_a": {
        "column_type": "text",
        "label": "Сторона A",
        "prompt": "Первая сторона договора (как указана в шапке).",
    },
    "party_b": {
        "column_type": "text",
        "label": "Сторона B",
        "prompt": "Вторая сторона договора (как указана в шапке).",
    },
    "landlord": {
        "column_type": "text",
        "label": "Арендодатель",
        "prompt": "Кто арендодатель?",
    },
    "tenant": {
        "column_type": "text",
        "label": "Арендатор",
        "prompt": "Кто арендатор?",
    },
    "supplier": {
        "column_type": "text",
        "label": "Поставщик",
        "prompt": "Кто поставщик?",
    },
    "buyer": {
        "column_type": "text",
        "label": "Покупатель",
        "prompt": "Кто покупатель?",
    },
    "customer": {
        "column_type": "text",
        "label": "Заказчик",
        "prompt": "Кто заказчик?",
    },
    "contractor": {
        "column_type": "text",
        "label": "Исполнитель / подрядчик",
        "prompt": "Кто исполнитель или подрядчик?",
    },
    "subject": {
        "column_type": "text",
        "label": "Предмет",
        "prompt": "Кратко: предмет договора.",
    },
    "leased_object": {
        "column_type": "text",
        "label": "Объект аренды",
        "prompt": "Что передаётся в аренду?",
    },
    "goods": {
        "column_type": "text",
        "label": "Товар",
        "prompt": "Какой товар поставляется?",
    },
    "scope": {
        "column_type": "text",
        "label": "Объём услуг/работ",
        "prompt": "Какой объём услуг или работ?",
    },
    "rent_amount": {
        "column_type": "currency",
        "label": "Арендная плата",
        "prompt": "Ключевая сумма арендной платы.",
    },
    "price_total": {
        "column_type": "currency",
        "label": "Сумма / цена",
        "prompt": "Ключевая цена или общая сумма по договору.",
    },
    "contract_term": {
        "column_type": "text",
        "label": "Срок договора",
        "prompt": "Срок действия договора.",
    },
    "delivery_term": {
        "column_type": "text",
        "label": "Срок поставки",
        "prompt": "Срок или условия поставки.",
    },
    "sla_or_deadline": {
        "column_type": "text",
        "label": "Срок выполнения / SLA",
        "prompt": "Срок выполнения работ/услуг или SLA.",
    },
    "buyout_right": {
        "column_type": "yes_no",
        "label": "Право выкупа",
        "prompt": "Предусмотрено ли право выкупа? Да / Нет.",
    },
    "penalty": {
        "column_type": "text",
        "label": "Неустойка",
        "prompt": "Условия неустойки / пени.",
    },
    "governing_law": {
        "column_type": "text",
        "label": "Применимое право",
        "prompt": "Применимое право и/или подсудность.",
    },
}


def known_field_ids() -> Tuple[str, ...]:
    return tuple(sorted(CONTRACT_FIELD_CATALOG.keys()))


def normalize_field_id(raw: Any) -> Optional[str]:
    fid = str(raw or "").strip().lower().replace(" ", "_")
    if not fid:
        return None
    # Allow namespaced ids: lease.rent_amount → rent_amount
    if "." in fid:
        fid = fid.split(".")[-1]
    if fid in CONTRACT_FIELD_CATALOG:
        return fid
    return None


def field_id_from_column_config(column_config: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(column_config, dict):
        return None
    return normalize_field_id(column_config.get("field_id"))


# Subject-specific fields must not be hallucinated from litigation / payments / letters.
_CONTRACT_SUBJECT_FIELD_IDS = frozenset(
    {
        "landlord",
        "tenant",
        "leased_object",
        "rent_amount",
        "buyout_right",
        "contract_term",
        "supplier",
        "buyer",
        "goods",
        "delivery_term",
        "customer",
        "contractor",
        "scope",
        "sla_or_deadline",
        "price_total",
        "penalty",
        "governing_law",
        "party_a",
        "party_b",
        "subject",
    }
)

_NON_CONTRACT_DD_DOC_TYPES = frozenset(
    {
        "litigation",
        "payment_order",
        "bank_statement",
        "correspondence",
    }
)


def field_applies_to_dd_doc_type(field_id: str, dd_doc_type: str) -> bool:
    """Whether a catalog field is meaningful for this DD document type."""
    fid = normalize_field_id(field_id) or str(field_id or "").strip().lower()
    doc_type = str(dd_doc_type or "unknown").strip().lower()
    if not fid:
        return True
    if fid in _CONTRACT_SUBJECT_FIELD_IDS and doc_type in _NON_CONTRACT_DD_DOC_TYPES:
        return False
    return True


def column_def_for_field(field_id: str) -> Dict[str, Any]:
    meta = CONTRACT_FIELD_CATALOG[field_id]
    return {
        "column_label": meta["label"],
        "column_type": meta["column_type"],
        "prompt": meta["prompt"],
        "column_config": {"field_id": field_id, "column_kind": "fact"},
    }


def build_template_columns(field_ids: List[str]) -> List[Dict[str, Any]]:
    cols: List[Dict[str, Any]] = []
    for fid in field_ids:
        if fid not in CONTRACT_FIELD_CATALOG:
            continue
        cols.append(column_def_for_field(fid))
    return cols


# Seed templates for add_tabular_templates / product catalog.
# Fact/precise columns only — vague "key risks" columns are not part of DD packs.
RU_DD_LEASE_TEMPLATE: Dict[str, Any] = {
    "name": "DD: коммерческая аренда",
    "description": (
        "Карточка договора аренды для due diligence: стороны, объект, плата, "
        "срок, выкуп, неустойка и расторжение."
    ),
    "category": "due_diligence",
    "tags": ["DD", "аренда", "lease", "RU"],
    "is_system": True,
    "is_public": True,
    "is_featured": True,
    "columns": build_template_columns(
        [
            "doc_number",
            "doc_date",
            "landlord",
            "tenant",
            "leased_object",
            "rent_amount",
            "contract_term",
            "buyout_right",
            "penalty",
        ]
    )
    + [
        {
            "column_label": "Расторжение / отказ",
            "column_type": "text",
            "prompt": (
                "Как можно расторгнуть договор или отказаться от исполнения? "
                "Укажи основания, сроки уведомления и последствия. Если не указано — «не указано»."
            ),
        },
        {
            "column_label": "Ответственность",
            "column_type": "text",
            "prompt": (
                "Какова ответственность сторон: неустойка, ограничение убытков, "
                "исключение упущенной выгоды? Кратко по пунктам. Если не указано — «не указано»."
            ),
        },
        *build_template_columns(["governing_law"]),
    ],
}

RU_DD_SUPPLY_TEMPLATE: Dict[str, Any] = {
    "name": "DD: поставка",
    "description": (
        "Карточка договора поставки: стороны, товар, цена, сроки поставки, "
        "неустойка и расторжение."
    ),
    "category": "due_diligence",
    "tags": ["DD", "поставка", "supply", "RU"],
    "is_system": True,
    "is_public": True,
    "is_featured": True,
    "columns": build_template_columns(
        [
            "doc_number",
            "doc_date",
            "supplier",
            "buyer",
            "goods",
            "price_total",
            "delivery_term",
            "penalty",
        ]
    )
    + [
        {
            "column_label": "Расторжение / отказ",
            "column_type": "text",
            "prompt": (
                "Как можно расторгнуть договор или отказаться от исполнения? "
                "Укажи основания, сроки уведомления и последствия. Если не указано — «не указано»."
            ),
        },
        {
            "column_label": "Ответственность",
            "column_type": "text",
            "prompt": (
                "Какова ответственность сторон: неустойка, ограничение убытков, "
                "исключение упущенной выгоды? Кратко по пунктам. Если не указано — «не указано»."
            ),
        },
        *build_template_columns(["governing_law"]),
    ],
}

RU_DD_SERVICES_WORKS_TEMPLATE: Dict[str, Any] = {
    "name": "DD: услуги и подряд",
    "description": (
        "Карточка договора услуг или подряда: стороны, объём, цена, сроки/SLA, "
        "неустойка и расторжение."
    ),
    "category": "due_diligence",
    "tags": ["DD", "услуги", "подряд", "services", "RU"],
    "is_system": True,
    "is_public": True,
    "is_featured": True,
    "columns": build_template_columns(
        [
            "doc_number",
            "doc_date",
            "customer",
            "contractor",
            "scope",
            "price_total",
            "sla_or_deadline",
            "penalty",
        ]
    )
    + [
        {
            "column_label": "Расторжение / отказ",
            "column_type": "text",
            "prompt": (
                "Как можно расторгнуть договор или отказаться от исполнения? "
                "Укажи основания, сроки уведомления и последствия. Если не указано — «не указано»."
            ),
        },
        {
            "column_label": "Ответственность",
            "column_type": "text",
            "prompt": (
                "Какова ответственность сторон: неустойка, ограничение убытков, "
                "исключение упущенной выгоды? Кратко по пунктам. Если не указано — «не указано»."
            ),
        },
        *build_template_columns(["governing_law"]),
    ],
}

RU_DD_SCHEMA_TEMPLATES: Tuple[Dict[str, Any], ...] = (
    RU_DD_LEASE_TEMPLATE,
    RU_DD_SUPPLY_TEMPLATE,
    RU_DD_SERVICES_WORKS_TEMPLATE,
)
