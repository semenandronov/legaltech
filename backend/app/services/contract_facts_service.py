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
from app.services.document_date_resolver import resolve_document_issuance_date
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
    r"(?is)(?:договор\w*|соглашени\w*|дс)\s*"
    r"(?:аренды|поставки|подряда|оказания\s+услуг)?"
    r".{0,90}?"
    r"(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
_DS_NUMBER_RE = re.compile(
    r"(?i)дополнительн\w*\s+соглашени\w*\s*(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
_BASE_CONTRACT_RE = re.compile(
    r"(?i)к\s+договору[^№\n]{0,80}(?:№|N[oо]?\.?)\s*([0-9A-Za-z][0-9A-Za-z/\-–—\._]*)"
)
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
# Role anchor; party name is resolved from a multi-line window BEFORE this mark
# (OCR often puts «ООО …» on earlier lines and «на основании устава, именуемое …» on the last).
_PARTY_ROLE_ANCHOR_RE = re.compile(
    r"(?is),\s*именуем\w+\s+в\s+дальнейшем\s+[«\"„]?(?P<role>Арендодатель|Арендатор|"
    r"Заказчик|Исполнитель|Подрядчик|Поставщик|Покупатель)\b"
)
_ORG_OR_IP_RE = re.compile(
    r"(?is)("
    r"(?:общество\s+с\s+ограниченной\s+ответственностью|ооо|акционерное\s+общество|"
    r"публичное\s+акционерное\s+общество|пао|ао|зао)\s*"
    r"[«\"„][^»\"\n]{1,120}[»\"“]?|"
    r"(?:общество\s+с\s+ограниченной\s+ответственностью|ооо)\s+[А-ЯЁA-Z][А-ЯЁA-Za-zа-яё0-9\-\s]{2,80}?|"
    r"индивидуальный\s+предприниматель\s+[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}|"
    r"ип\s+[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r")"
)
_PARTY_GARBAGE_RE = re.compile(
    r"(?i)^(?:"
    r"основани[еюя]|устава|доверенност\w*|огрн(?:ип)?|инн|кпп|"
    r"действующ\w*|в\s+лице|с\s+одной\s+стороны|с\s+другой\s+стороны"
    r")\b"
)
_ID_ONLY_RE = re.compile(r"(?i)^(?:огрн(?:ип)?|инн|кпп)?\s*\d{10,15}\s*$")
_GENERIC_LEASE_OBJECT_RE = re.compile(
    r"(?i)^(?:движимого|недвижимого)\s+имущества\s*$"
)
_LEASED_OBJECT_GARBAGE_RE = re.compile(
    r"(?i)^[)\]»,.\s]+|за\s+плату,\s+а\s+арендатор|принимает\s+объект\s+аренды"
)
_RENT_CLAUSE_RE = re.compile(
    r"(?is)(?:размер\s+)?арендн\w+\s+плат\w*.{0,80}?"
    r"(?:составляет|в\s+размере|равна|равняется)?[^\d]{0,40}"
    r"(\d[\d\s\u00a0\u202f]{0,}(?:[.,]\d{1,2})?)\s*(?:руб|₽|RUB)?"
)
# Schema must not lock in pocket-change OCR noise when a real rent figure exists.
_MIN_SCHEMA_RENT_RUB = 100.0


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


def _money_to_float(display: str) -> Optional[float]:
    plain = normalize_ru_money_amount(display, with_rub_suffix=False)
    if not plain:
        return None
    try:
        return float(plain.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def is_plausible_party_name(value: str) -> bool:
    """Reject OCR tail fragments that must never short-circuit tabular cells."""
    text = re.sub(r"\s+", " ", (value or "")).strip(" .,;:«»\"'")
    if len(text) < 8:
        return False
    if _PARTY_GARBAGE_RE.search(text):
        return False
    if _ID_ONLY_RE.match(text):
        return False
    # Must look like an org/IP/person name, not a legal-boilerplate clause.
    if not _ORG_OR_IP_RE.search(text) and not re.search(
        r"(?i)\b(?:ооо|ип|ао|пао|зао|общество|предприниматель)\b", text
    ):
        # Allow bare FIO-like strings (3 capitalized tokens) for individuals.
        fio = re.match(
            r"^[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}$",
            text,
        )
        if not fio:
            return False
    return True


def is_plausible_leased_object(value: str) -> bool:
    text = re.sub(r"\s+", " ", (value or "")).strip(" .,;:«»\"'")
    if len(text) < 5:
        return False
    if _LEASED_OBJECT_GARBAGE_RE.search(text):
        return False
    return True


def is_acceptable_contract_fact(field_id: str, value: str) -> bool:
    """Quality gate before schema short-circuit — bad facts fall through to RAG/LLM."""
    fid = normalize_field_id(field_id) or str(field_id or "")
    text = str(value or "").strip()
    if not text or text in {"—", "N/A", "n/a", "NA"}:
        return False
    if fid in {"landlord", "tenant", "party_a", "party_b", "supplier", "buyer", "customer", "contractor"}:
        return is_plausible_party_name(text)
    if fid == "leased_object":
        return is_plausible_leased_object(text)
    if fid in {"rent_amount", "price_total"}:
        amount = _money_to_float(text)
        if amount is None:
            return False
        # Pocket-change hits are almost always OCR/deposit noise for commercial DD.
        if amount < _MIN_SCHEMA_RENT_RUB:
            return False
        return True
    return True


def _extract_party_for_role(
    head: str, role: str
) -> Optional[Tuple[str, int, int, str]]:
    """
    Resolve party name for a preamble role.

    Looks at a multi-line window before «именуемое в дальнейшем «Роль»» and picks
    the nearest ООО/ИП/АО span — not the last clause fragment on the same line.
    """
    role_l = role.lower()
    best: Optional[Tuple[str, int, int, str]] = None
    for m in _PARTY_ROLE_ANCHOR_RE.finditer(head):
        if (m.group("role") or "").lower() != role_l:
            continue
        window_start = max(0, m.start() - 700)
        window = head[window_start : m.start()]
        orgs = list(_ORG_OR_IP_RE.finditer(window))
        if not orgs:
            continue
        org = orgs[-1]
        party = re.sub(r"\s+", " ", org.group(1)).strip()
        party = party.strip(" .,;:")
        # Keep guillemets / quotes that belong to the legal name.
        if not is_plausible_party_name(party):
            continue
        abs_start = window_start + org.start(1)
        abs_end = window_start + org.end(1)
        verbatim = head[abs_start : m.end()][:240]
        cand = (party, abs_start, abs_end, verbatim)
        # Prefer the first role occurrence in the preamble (true header).
        if best is None or abs_start < best[1]:
            best = cand
    return best


def _extract_rent_amount(
    head: str,
) -> Optional[Tuple[str, int, int, str]]:
    """Pick the strongest rent figure; ignore tiny OCR noise when larger figures exist."""
    candidates: List[Tuple[float, str, int, int, str]] = []
    for m in _RENT_CLAUSE_RE.finditer(head):
        amount = normalize_ru_money_amount(m.group(1))
        if not amount:
            continue
        val = _money_to_float(amount)
        if val is None:
            continue
        candidates.append((val, amount, m.start(), m.end(), m.group(0)[:240]))
    if not candidates:
        # Fallback to legacy pattern for older fixtures.
        rm = _RENT_AMOUNT_RE.search(head)
        if not rm:
            return None
        amount = normalize_ru_money_amount(rm.group(1))
        if not amount:
            return None
        val = _money_to_float(amount)
        if val is None or val < _MIN_SCHEMA_RENT_RUB:
            return None
        return amount, rm.start(), rm.end(), rm.group(0)[:240]

    # Prefer amounts that look like commercial rent; among those, largest near clause.
    strong = [c for c in candidates if c[0] >= _MIN_SCHEMA_RENT_RUB]
    pool = strong or candidates
    # Largest wins among plausible (buyout/total rent usually the headline figure).
    best = max(pool, key=lambda c: c[0])
    if best[0] < _MIN_SCHEMA_RENT_RUB:
        return None
    return best[1], best[2], best[3], best[4]


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

    # Issuance/signing date of THIS document (narrow zone + candidate scoring).
    date_hit = resolve_document_issuance_date(head, filename=filename or "")
    if date_hit is not None:
        fields["doc_date"] = _pack_field(
            date_hit.iso_date,
            verbatim=date_hit.verbatim,
            confidence=date_hit.confidence,
            char_start=date_hit.char_start,
            char_end=date_hit.char_end,
        )

    rent_hit = _extract_rent_amount(head)
    if rent_hit:
        amount, r_start, r_end, r_verb = rent_hit
        if is_acceptable_contract_fact("rent_amount", amount):
            fields["rent_amount"] = _pack_field(
                amount,
                verbatim=r_verb,
                confidence=0.84,
                char_start=r_start,
                char_end=r_end,
            )
            fields["price_total"] = dict(fields["rent_amount"])

    if "price_total" not in fields:
        pm_price = _PRICE_TOTAL_RE.search(head)
        if pm_price:
            amount = normalize_ru_money_amount(pm_price.group(1))
            if amount and is_acceptable_contract_fact("price_total", amount):
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
        if is_plausible_leased_object(obj) and not _GENERIC_LEASE_OBJECT_RE.match(obj):
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

    landlord = _extract_party_for_role(head[:6000], "Арендодатель")
    if landlord:
        party, p_start, p_end, p_verb = landlord
        fields["landlord"] = _pack_field(
            party,
            verbatim=p_verb,
            confidence=0.9,
            char_start=p_start,
            char_end=p_end,
        )
        fields.setdefault("party_a", dict(fields["landlord"]))

    tenant = _extract_party_for_role(head[:6000], "Арендатор")
    if tenant:
        party, p_start, p_end, p_verb = tenant
        fields["tenant"] = _pack_field(
            party,
            verbatim=p_verb,
            confidence=0.9,
            char_start=p_start,
            char_end=p_end,
        )
        fields.setdefault("party_b", dict(fields["tenant"]))

    # Never persist garbage that would short-circuit tabular cells.
    fields = {
        fid: row
        for fid, row in fields.items()
        if isinstance(row, dict)
        and is_acceptable_contract_fact(fid, str(row.get("value") or ""))
    }
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
    if not is_acceptable_contract_fact(field_id, str(fact.get("value") or "")):
        logger.info(
            "contract_facts skip short-circuit field_id=%s value=%r (failed quality gate)",
            field_id,
            str(fact.get("value") or "")[:80],
        )
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
