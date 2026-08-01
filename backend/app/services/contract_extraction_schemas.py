"""
Pydantic schemas for RU commercial contract fact extraction (phase 3).

One LLM pass fills a typed schema; tabular cells read fields by ``field_id``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

CONTRACT_FACTS_SCHEMA_VERSION = "contract_facts_v1"


class GroundedField(BaseModel):
    """Single grounded fact — value must be supported by verbatim_quote when present."""

    value: Optional[str] = Field(
        None,
        description="Нормализованное значение поля или null если в тексте нет",
    )
    verbatim_quote: Optional[str] = Field(
        None,
        description="Дословная цитата из документа (обязательна при value != null)",
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Уверенность 0..1",
    )

    class Config:
        extra = "ignore"


class _ContractExtractionBase(BaseModel):
    doc_number: Optional[GroundedField] = Field(None, description="Номер договора / ДС")
    doc_date: Optional[GroundedField] = Field(
        None, description="Дата документа YYYY-MM-DD"
    )
    party_a: Optional[GroundedField] = Field(
        None, description="Первая сторона (как в шапке)"
    )
    party_b: Optional[GroundedField] = Field(
        None, description="Вторая сторона (как в шапке)"
    )
    subject: Optional[GroundedField] = Field(None, description="Предмет договора")
    price_total: Optional[GroundedField] = Field(
        None, description="Ключевая сумма / цена / арендная плата"
    )
    contract_term: Optional[GroundedField] = Field(
        None, description="Срок действия договора"
    )
    penalty: Optional[GroundedField] = Field(
        None, description="Неустойка / пеня (ставка или описание)"
    )
    governing_law: Optional[GroundedField] = Field(
        None, description="Применимое право / подсудность"
    )

    class Config:
        extra = "ignore"


class LeaseExtraction(_ContractExtractionBase):
    """Коммерческая аренда / ДС к аренде."""

    landlord: Optional[GroundedField] = Field(None, description="Арендодатель")
    tenant: Optional[GroundedField] = Field(None, description="Арендатор")
    rent_amount: Optional[GroundedField] = Field(
        None, description="Арендная плата (ключевая сумма)"
    )
    buyout_right: Optional[GroundedField] = Field(
        None, description="Право выкупа: Да / Нет / null"
    )
    leased_object: Optional[GroundedField] = Field(
        None, description="Объект аренды"
    )


class SupplyExtraction(_ContractExtractionBase):
    """Поставка / купля-продажа товара."""

    supplier: Optional[GroundedField] = Field(None, description="Поставщик")
    buyer: Optional[GroundedField] = Field(None, description="Покупатель")
    goods: Optional[GroundedField] = Field(None, description="Товар / номенклатура")
    delivery_term: Optional[GroundedField] = Field(
        None, description="Срок / условия поставки"
    )


class ServicesWorksExtraction(_ContractExtractionBase):
    """Услуги или подряд."""

    customer: Optional[GroundedField] = Field(None, description="Заказчик")
    contractor: Optional[GroundedField] = Field(
        None, description="Исполнитель / подрядчик"
    )
    scope: Optional[GroundedField] = Field(
        None, description="Объём услуг / работ"
    )
    sla_or_deadline: Optional[GroundedField] = Field(
        None, description="Срок выполнения / SLA"
    )


_SCHEMA_BY_DOC_TYPE: Dict[str, Type[BaseModel]] = {
    "lease_commercial": LeaseExtraction,
    "addendum": LeaseExtraction,  # often lease addendum; LLM still fills shared fields
    "supply": SupplyExtraction,
    "services": ServicesWorksExtraction,
    "works": ServicesWorksExtraction,
}


def schema_for_dd_doc_type(doc_type: str) -> Type[BaseModel]:
    return _SCHEMA_BY_DOC_TYPE.get(
        (doc_type or "").strip().lower(),
        _ContractExtractionBase,
    )


def grounded_field_to_dict(field: Optional[GroundedField]) -> Optional[Dict[str, Any]]:
    if field is None:
        return None
    value = (field.value or "").strip() if field.value is not None else ""
    if not value or value.upper() in {"N/A", "NA", "NULL", "NONE"}:
        return None
    quote = (field.verbatim_quote or "").strip() or None
    return {
        "value": value,
        "verbatim": quote,
        "confidence": float(field.confidence or 0.0),
    }


def extraction_model_to_fields(model: BaseModel) -> Dict[str, Dict[str, Any]]:
    """Flatten schema instance → field_id → {value, verbatim, confidence}."""
    raw = model.model_dump() if hasattr(model, "model_dump") else dict(model)
    out: Dict[str, Dict[str, Any]] = {}
    for key, val in raw.items():
        if val is None:
            continue
        if isinstance(val, dict):
            gf = GroundedField.model_validate(val)
        elif isinstance(val, GroundedField):
            gf = val
        else:
            continue
        packed = grounded_field_to_dict(gf)
        if packed:
            out[key] = packed
    # Aliases: rent_amount also fills price_total when missing
    if "rent_amount" in out and "price_total" not in out:
        out["price_total"] = dict(out["rent_amount"])
    if "landlord" in out and "party_a" not in out:
        out["party_a"] = dict(out["landlord"])
    if "tenant" in out and "party_b" not in out:
        out["party_b"] = dict(out["tenant"])
    if "supplier" in out and "party_a" not in out:
        out["party_a"] = dict(out["supplier"])
    if "buyer" in out and "party_b" not in out:
        out["party_b"] = dict(out["buyer"])
    if "customer" in out and "party_a" not in out:
        out["party_a"] = dict(out["customer"])
    if "contractor" in out and "party_b" not in out:
        out["party_b"] = dict(out["contractor"])
    if "scope" in out and "subject" not in out:
        out["subject"] = dict(out["scope"])
    if "goods" in out and "subject" not in out:
        out["subject"] = dict(out["goods"])
    if "leased_object" in out and "subject" not in out:
        out["subject"] = dict(out["leased_object"])
    return out
