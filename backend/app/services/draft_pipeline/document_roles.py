"""Mapping between draft task roles and case file doc_type codes."""
from __future__ import annotations

from typing import Dict, List, Set

# Roles produced by TaskDecomposer (stable API for triage + extraction).
CORE_DATA_ROLES = frozenset(
    {
        "contract",
        "primary_execution_act",
        "payment_order",
        "pretension",
        "invoice",
        "delivery_note",
    }
)

SIDEBAR_ROLES = frozenset(
    {
        "egrul_extract",
        "charter",
        "power_of_attorney",
        "requisites",
    }
)

ROLE_TO_DOC_TYPES: Dict[str, List[str]] = {
    "contract": ["contract", "agreement"],
    "primary_execution_act": ["act", "acceptance_certificate", "upd"],
    "payment_order": ["payment_order", "bank_statement", "payment"],
    "pretension": ["claim", "pretension", "demand_letter"],
    "invoice": ["invoice", "bill"],
    "delivery_note": ["delivery_note", "waybill", "ttn"],
    "egrul_extract": ["egrul_extract", "egrip_extract"],
    "charter": ["charter", "articles_of_association"],
    "power_of_attorney": ["power_of_attorney"],
    "requisites": ["egrul_extract", "charter", "other"],
}

DOC_TYPE_ALIASES: Dict[str, str] = {
    "agreement": "contract",
    "договор": "contract",
    "контракт": "contract",
    "acceptance_certificate": "act",
    "акт": "act",
    "claim": "pretension",
    "претензия": "pretension",
    "demand_letter": "pretension",
    "payment": "payment_order",
    "bank_statement": "payment_order",
    "платежное поручение": "payment_order",
    "платежка": "payment_order",
}


def normalize_doc_type(doc_type: str) -> str:
    key = (doc_type or "other").strip().lower()
    return DOC_TYPE_ALIASES.get(key, key)


def doc_types_for_role(role: str) -> List[str]:
    return list(ROLE_TO_DOC_TYPES.get(role, ["other"]))


def role_for_doc_type(doc_type: str) -> str:
    norm = normalize_doc_type(doc_type)
    for role, types in ROLE_TO_DOC_TYPES.items():
        if norm in types:
            return role
    if norm in {"egrul_extract", "charter", "power_of_attorney"}:
        return "requisites"
    return "other"
