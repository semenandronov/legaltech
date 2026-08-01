"""
Contract facts layer: one structured extract per file → tabular cells by field_id.

Rules-first (always). Optional single LLM pass when enabled (phase 3.2–3.3).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.contract_extraction_schemas import (
    CONTRACT_FACTS_SCHEMA_VERSION,
    extraction_model_to_fields,
    schema_for_dd_doc_type,
)
from app.services.contract_field_catalog import (
    field_applies_to_dd_doc_type,
    field_id_from_column_config,
    normalize_field_id,
)
from app.services.dd_document_classifier import get_file_dd_doc_type
from app.services.ru_contract_value_normalize import (
    normalize_ru_contract_number,
    normalize_ru_money_amount,
)
from app.services.tabular_extraction_schemas import typed_extraction_to_cell_model
from app.services.tabular_review_models import TabularCellExtractionModel

logger = logging.getLogger(__name__)

_CONTRACT_LIKE = frozenset(
    {
        "lease_commercial",
        "supply",
        "services",
        "works",
        "addendum",
        "appendix_spec",
    }
)

_DOC_NUMBER_RE = re.compile(
    r"(?i)(?:договор\w*|соглашени\w*|дс)\s*"
    r"(?:аренды|поставки|подряда|оказания\s+услуг)?\s*"
    r"(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
_DS_NUMBER_RE = re.compile(
    r"(?i)дополнительн\w+\s+соглашени\w*\s*(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
_BASE_CONTRACT_RE = re.compile(
    r"(?i)к\s+договору[^№\n]{0,80}(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
_DATE_RE = re.compile(
    r"(?i)(?:от\s+)?[«\"]?(\d{1,2})[»\"]?\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s+(\d{4})\s*г?\.?"
)
_DATE_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DATE_DOT_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\s*г?\.?\b")
_RENT_AMOUNT_RE = re.compile(
    r"(?i)(?:размер\s+)?арендн\w+\s+плат\w+[^\d]{0,40}"
    r"(\d[\d\s\u00a0\u202f]{2,}(?:[.,]\d{1,2})?)\s*(?:руб|₽|RUB)?"
)
_PRICE_TOTAL_RE = re.compile(
    r"(?i)(?:общая\s+стоимость|стоимость\s+товара|цена\s+услуг|"
    r"цена\s+договора|стоимость\s+услуг)[^\d]{0,40}"
    r"(\d[\d\s\u00a0\u202f]{2,}(?:[.,]\d{1,2})?)\s*(?:руб|₽|RUB)?"
)
_BUYOUT_YES_RE = re.compile(r"(?i)с\s+правом\s+выкупа|право\s+выкупа|выкупн\w+\s+стоимост")
_BUYOUT_NO_RE = re.compile(r"(?i)без\s+права\s+выкупа|право\s+выкупа\s+не\s+предусмотр")
_PENALTY_RE = re.compile(
    r"(?i)(?:неустойк\w*|пен\w*)[^\n%]{0,80}(\d+[.,]?\d*\s*%)"
)
_LEASED_OBJECT_FROM_TITLE_RE = re.compile(
    r"(?i)договор\w*\s+аренды\s+(.+?)(?=\s+с\s+правом|\s*№|\s*N[oо]?\.?|\s+от\s|\n)"
)
_LEASED_OBJECT_EXPLICIT_RE = re.compile(
    r"(?i)(?:объект\s+аренды|предмет\s+договора(?:\s+аренды)?|в\s+аренду\s+переда[её]т?ся)\s*[:\-]?\s*"
    r"([^\n.]{5,180})"
)
_LANDLORD_RE = re.compile(
    r"(?is)([^\n]{8,220}?)\s*,\s*именуем\w+\s+в\s+дальнейшем\s+[«\"„]?Арендодатель"
)
_TENANT_RE = re.compile(
    r"(?is)([^\n]{8,220}?)\s*,\s*именуем\w+\s+в\s+дальнейшем\s+[«\"„]?Арендатор"
)
_MONTHS = {
    "января": "01",
    "февраля": "02",
    "марта": "03",
    "апреля": "04",
    "мая": "05",
    "июня": "06",
    "июля": "07",
    "августа": "08",
    "сентября": "09",
    "октября": "10",
    "ноября": "11",
    "декабря": "12",
}


def contract_facts_enabled() -> bool:
    return bool(getattr(config, "CONTRACT_FACTS_ENABLED", True))


def contract_facts_llm_enabled() -> bool:
    return bool(getattr(config, "CONTRACT_FACTS_LLM_ENABLED", False))


def contract_facts_extract_max_chars() -> int:
    return max(3000, int(getattr(config, "CONTRACT_FACTS_EXTRACT_MAX_CHARS", 12000) or 12000))


def _pack_field(
    value: str,
    *,
    verbatim: str,
    confidence: float,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "value": value.strip(),
        "verbatim": (verbatim or value).strip()[:500],
        "confidence": float(confidence),
    }
    if char_start is not None:
        row["char_start"] = int(char_start)
    if char_end is not None:
        row["char_end"] = int(char_end)
    return row


def _merge_fields(
    base: Dict[str, Dict[str, Any]],
    extra: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    out = dict(base)
    for key, val in extra.items():
        if not isinstance(val, dict) or not str(val.get("value") or "").strip():
            continue
        prev = out.get(key)
        if prev is None or float(val.get("confidence") or 0) >= float(prev.get("confidence") or 0):
            out[key] = val
    return out


def extract_contract_facts_rules(
    text: str,
    *,
    filename: str = "",
    dd_doc_type: str = "unknown",
) -> Dict[str, Dict[str, Any]]:
    """Deterministic extractors for high-signal RU contract fields."""
    head = (text or "")[: contract_facts_extract_max_chars()]
    fields: Dict[str, Dict[str, Any]] = {}

    def _put_number(raw: str, *, verbatim: str, confidence: float, start: int, end: int) -> None:
        number = normalize_ru_contract_number(raw)
        if not number:
            return
        fields["doc_number"] = _pack_field(
            number,
            verbatim=verbatim[:200],
            confidence=confidence,
            char_start=start,
            char_end=end,
        )

    m = _DS_NUMBER_RE.search(head) or _DOC_NUMBER_RE.search(head)
    if m:
        _put_number(
            m.group(1),
            verbatim=m.group(0),
            confidence=0.88,
            start=m.start(),
            end=m.end(),
        )
    base = _BASE_CONTRACT_RE.search(head)
    if base and "doc_number" not in fields:
        _put_number(
            base.group(1),
            verbatim=base.group(0),
            confidence=0.82,
            start=base.start(),
            end=base.end(),
        )
    elif base and dd_doc_type == "addendum":
        # Prefer base contract number for DD columns about the master agreement.
        _put_number(
            base.group(1),
            verbatim=base.group(0),
            confidence=0.9,
            start=base.start(),
            end=base.end(),
        )

    # Prefer Russian month dates in the header (doc signing date) over
    # dotted dates that often appear in contract-number references.
    dm = _DATE_RE.search(head[:2500])
    if dm:
        day, month_ru, year = dm.group(1), dm.group(2).lower(), dm.group(3)
        month = _MONTHS.get(month_ru)
        if month:
            iso = f"{year}-{month}-{int(day):02d}"
            fields["doc_date"] = _pack_field(
                iso,
                verbatim=dm.group(0),
                confidence=0.86,
                char_start=dm.start(),
                char_end=dm.end(),
            )
    if "doc_date" not in fields:
        for pattern, parser in (
            (_DATE_ISO_RE, lambda g: f"{g.group(1)}-{g.group(2)}-{g.group(3)}"),
            (
                _DATE_DOT_RE,
                lambda g: f"{g.group(3)}-{int(g.group(2)):02d}-{int(g.group(1)):02d}",
            ),
        ):
            dm = pattern.search(head[:2500])
            if dm:
                try:
                    iso = parser(dm)
                    fields["doc_date"] = _pack_field(
                        iso,
                        verbatim=dm.group(0),
                        confidence=0.85,
                        char_start=dm.start(),
                        char_end=dm.end(),
                    )
                    break
                except Exception:
                    pass

    rm = _RENT_AMOUNT_RE.search(head)
    if rm:
        amount = normalize_ru_money_amount(rm.group(1))
        if amount:
            fields["rent_amount"] = _pack_field(
                amount,
                verbatim=rm.group(0)[:240],
                confidence=0.84,
                char_start=rm.start(),
                char_end=rm.end(),
            )
            fields["price_total"] = dict(fields["rent_amount"])

    if "price_total" not in fields:
        pm_price = _PRICE_TOTAL_RE.search(head)
        if pm_price:
            amount = normalize_ru_money_amount(pm_price.group(1))
            if amount:
                fields["price_total"] = _pack_field(
                    amount,
                    verbatim=pm_price.group(0)[:240],
                    confidence=0.84,
                    char_start=pm_price.start(),
                    char_end=pm_price.end(),
                )

    if _BUYOUT_NO_RE.search(head):
        m = _BUYOUT_NO_RE.search(head)
        fields["buyout_right"] = _pack_field(
            "Нет",
            verbatim=m.group(0) if m else "без права выкупа",
            confidence=0.9,
        )
    elif _BUYOUT_YES_RE.search(head):
        m = _BUYOUT_YES_RE.search(head)
        fields["buyout_right"] = _pack_field(
            "Да",
            verbatim=m.group(0) if m else "с правом выкупа",
            confidence=0.88,
        )

    pm = _PENALTY_RE.search(head)
    if pm:
        fields["penalty"] = _pack_field(
            pm.group(1).replace(",", "."),
            verbatim=pm.group(0)[:240],
            confidence=0.8,
            char_start=pm.start(),
            char_end=pm.end(),
        )

    obj_m = _LEASED_OBJECT_EXPLICIT_RE.search(head) or _LEASED_OBJECT_FROM_TITLE_RE.search(head)
    if obj_m:
        obj = re.sub(r"\s+", " ", obj_m.group(1)).strip(" .,;:«»\"'")
        if len(obj) >= 5:
            fields["leased_object"] = _pack_field(
                obj,
                verbatim=obj_m.group(0)[:240],
                confidence=0.8,
                char_start=obj_m.start(),
                char_end=obj_m.end(),
            )
            fields.setdefault(
                "subject",
                _pack_field(
                    f"Аренда: {obj}",
                    verbatim=obj_m.group(0)[:240],
                    confidence=0.72,
                    char_start=obj_m.start(),
                    char_end=obj_m.end(),
                ),
            )

    landlord_m = _LANDLORD_RE.search(head[:4000])
    if landlord_m:
        party = re.sub(r"\s+", " ", landlord_m.group(1)).strip(" .,;:")
        if len(party) >= 8:
            fields["landlord"] = _pack_field(
                party,
                verbatim=landlord_m.group(0)[:240],
                confidence=0.86,
                char_start=landlord_m.start(),
                char_end=landlord_m.end(),
            )
            fields.setdefault("party_a", dict(fields["landlord"]))

    tenant_m = _TENANT_RE.search(head[:4000])
    if tenant_m:
        party = re.sub(r"\s+", " ", tenant_m.group(1)).strip(" .,;:")
        if len(party) >= 8:
            fields["tenant"] = _pack_field(
                party,
                verbatim=tenant_m.group(0)[:240],
                confidence=0.86,
                char_start=tenant_m.start(),
                char_end=tenant_m.end(),
            )
            fields.setdefault("party_b", dict(fields["tenant"]))

    return fields


def _llm_extract_fields(
    text: str,
    *,
    dd_doc_type: str,
    filename: str = "",
) -> Dict[str, Dict[str, Any]]:
    schema_cls = schema_for_dd_doc_type(dd_doc_type)
    head = (text or "")[: contract_facts_extract_max_chars()]
    if not head.strip():
        return {}
    try:
        from app.services.llm_factory import create_llm

        llm = create_llm(temperature=0.0, max_tokens=1800)
        structured = llm.with_structured_output(schema_cls)
        system = (
            "Ты юрист due diligence. Извлеки факты из фрагмента российского договора. "
            "Для каждого поля: value + verbatim_quote из текста. "
            "Если поля нет — value=null. Не выдумывай."
        )
        human = (
            f"Тип документа (hint): {dd_doc_type}\n"
            f"Файл: {filename}\n\n"
            f"Текст:\n{head}"
        )
        result = structured.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        if isinstance(result, dict):
            result = schema_cls.model_validate(result)
        return extraction_model_to_fields(result)
    except Exception as exc:
        logger.warning("Contract facts LLM extract failed: %s", exc, exc_info=True)
        return {}


def build_contract_facts_payload(
    *,
    text: str,
    filename: str = "",
    dd_doc_type: str = "unknown",
    allow_llm: bool = True,
) -> Dict[str, Any]:
    rules = extract_contract_facts_rules(
        text, filename=filename, dd_doc_type=dd_doc_type
    )
    source = "rules"
    fields = dict(rules)
    if (
        allow_llm
        and contract_facts_llm_enabled()
        and dd_doc_type in _CONTRACT_LIKE
    ):
        llm_fields = _llm_extract_fields(
            text, dd_doc_type=dd_doc_type, filename=filename
        )
        if llm_fields:
            fields = _merge_fields(fields, llm_fields)
            source = "hybrid" if rules else "llm"

    return {
        "schema_version": CONTRACT_FACTS_SCHEMA_VERSION,
        "doc_type": dd_doc_type or "unknown",
        "source": source,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "filename": filename or "",
        "fields": fields,
        "field_count": len(fields),
    }


def save_contract_facts_on_file(file_model, payload: Dict[str, Any]) -> None:
    file_model.contract_facts = payload


def get_contract_facts_payload(file_model) -> Optional[Dict[str, Any]]:
    raw = getattr(file_model, "contract_facts", None)
    if isinstance(raw, dict) and isinstance(raw.get("fields"), dict):
        return raw
    return None


def ensure_contract_facts_on_file(
    file_model,
    *,
    allow_llm: bool = False,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Lazy/backfill extract; does not commit the session."""
    if not contract_facts_enabled():
        return get_contract_facts_payload(file_model)
    existing = get_contract_facts_payload(file_model)
    if existing and not force:
        return existing
    text = str(getattr(file_model, "original_text", None) or "")
    if not text.strip():
        return existing
    dd_type = get_file_dd_doc_type(file_model) or "unknown"
    payload = build_contract_facts_payload(
        text=text,
        filename=str(getattr(file_model, "filename", "") or ""),
        dd_doc_type=dd_type,
        allow_llm=allow_llm,
    )
    save_contract_facts_on_file(file_model, payload)
    return payload


def lookup_contract_fact(
    payload: Optional[Dict[str, Any]],
    field_id: str,
) -> Optional[Dict[str, Any]]:
    fid = normalize_field_id(field_id)
    if not fid or not isinstance(payload, dict):
        return None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None
    row = fields.get(fid)
    if not isinstance(row, dict):
        return None
    if not str(row.get("value") or "").strip():
        return None
    return row


def contract_fact_to_extraction_dict(
    fact: Dict[str, Any],
    *,
    field_id: str,
) -> Dict[str, Any]:
    value = str(fact.get("value") or "").strip()
    verbatim = str(fact.get("verbatim") or value).strip()
    conf = float(fact.get("confidence") or 0.85)
    refs: List[Dict[str, Any]] = []
    if verbatim:
        ref: Dict[str, Any] = {"text": verbatim[:500]}
        if fact.get("char_start") is not None:
            ref["char_start"] = fact.get("char_start")
        if fact.get("char_end") is not None:
            ref["char_end"] = fact.get("char_end")
        refs.append(ref)
    return {
        "cell_value": value,
        "normalized_value": value,
        "verbatim_extract": verbatim[:500] if verbatim else None,
        "source_references": refs,
        "confidence": conf,
        "reasoning": f"Из contract_facts (field_id={field_id}).",
        "extraction_method": "contract_facts",
        "source_page": fact.get("source_page"),
        "source_section": fact.get("source_section"),
    }


def try_extraction_from_contract_facts(
    file_model,
    column,
    *,
    allow_lazy: bool = True,
) -> Optional[Tuple[TabularCellExtractionModel, List[Document], Dict[str, Any]]]:
    """
    Schema-first cell fill. Returns (extraction, evidence_docs, meta) or None.
    """
    if not contract_facts_enabled():
        return None
    cfg = getattr(column, "column_config", None)
    field_id = field_id_from_column_config(cfg if isinstance(cfg, dict) else None)
    if not field_id:
        return None

    dd_type = get_file_dd_doc_type(file_model) or "unknown"
    if not field_applies_to_dd_doc_type(field_id, dd_type):
        raw = {
            "cell_value": "N/A",
            "normalized_value": "N/A",
            "reasoning": (
                f"Поле «{field_id}» не применимо к типу документа «{dd_type}»."
            ),
            "extraction_method": "contract_facts",
            "confidence": 1.0,
            "source_references": [],
        }
        extraction = typed_extraction_to_cell_model(raw, column=column)
        extraction.extraction_method = "contract_facts"
        meta = {
            "status": "field_not_applicable",
            "field_id": field_id,
            "dd_doc_type": dd_type,
            "extraction_method": "contract_facts",
        }
        return extraction, [], meta

    payload = get_contract_facts_payload(file_model)
    if payload is None and allow_lazy:
        payload = ensure_contract_facts_on_file(file_model, allow_llm=False, force=False)

    fact = lookup_contract_fact(payload, field_id)
    if not fact:
        return None

    raw = contract_fact_to_extraction_dict(fact, field_id=field_id)
    try:
        extraction = typed_extraction_to_cell_model(raw, column=column)
    except Exception:
        logger.warning(
            "contract_facts typed convert failed field_id=%s",
            field_id,
            exc_info=True,
        )
        return None
    extraction.extraction_method = "contract_facts"

    verbatim = str(fact.get("verbatim") or fact.get("value") or "")
    doc = Document(
        page_content=verbatim or str(fact.get("value") or ""),
        metadata={
            "file_id": str(getattr(file_model, "id", "") or ""),
            "source_file": str(getattr(file_model, "filename", "") or ""),
            "zone": "schema",
            "retrieval_channel": "contract_facts",
            "field_id": field_id,
            "char_start": fact.get("char_start"),
            "char_end": fact.get("char_end"),
        },
    )
    meta = {
        "status": "contract_facts_hit",
        "field_id": field_id,
        "schema_version": (payload or {}).get("schema_version"),
        "source": (payload or {}).get("source"),
    }
    return extraction, [doc], meta
