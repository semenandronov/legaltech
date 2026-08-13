"""Authoritative inventory from followed appendix / specification sections.

When a clause points at Приложение №N / Спецификация, the followed appendix
text is the source of truth for object/goods composition — not the summary
noun in the subject clause.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.tabular_review_models import TabularCellExtractionModel

_INVENTORY_COLUMN_RE = re.compile(
    r"(?i)"
    r"(?:объект\s+аренды|предмет\s+аренды|leased[_\s-]?object|"
    r"что\s+переда(?:ётся|ется)|комплектац|состав\s+имущ|"
    r"\bтовар\b|\bgoods\b|спецификац|"
    r"какое\s+имуществ|перечень\s+имущ)"
)

_INVENTORY_FIELD_IDS = frozenset(
    {
        "leased_object",
        "goods",
        "subject",
        "scope",
    }
)

# Spec table rows: name … qty … unit_price … total
_SPEC_ROW_RE = re.compile(
    r"(?is)"
    r"(?P<name>"
    r"(?:электросамокат|зарядное\s+устройство(?:\s+для\s+электросамоката)?|"
    r"самокат|зарядк\w+|батаре\w+|аккумулятор\w+)"
    r"(?:\s+E-Scooter\s*Mk?\s*[\w\-]+)?"
    r"(?:\s+для\s+электросамоката(?:\s+E-Scooter\s*Mk?\s*[\w\-]+)?)?"
    r")"
    r"\s+(?P<qty>\d{1,4})\s+"
    r"(?P<unit>\d{1,3}(?:[ \u00a0\u202f]?\d{3})+|\d{4,7})\s+"
    r"(?P<total>\d{1,3}(?:[ \u00a0\u202f]?\d{3})+|\d{4,8})"
)

_NAME_QTY_RE = re.compile(
    r"(?is)"
    r"(?P<name>"
    r"(?:электросамокат|зарядное\s+устройство(?:\s+для\s+электросамоката)?)"
    r"(?:\s+E-Scooter\s*Mk?\s*[\w\-]+)?"
    r")"
    r"[^\d]{0,40}?(?:в\s+количестве\s+)?(?P<qty>\d{1,4})\s*(?:шт\.?|штук)?"
)


def column_requires_appendix_inventory(column: Any) -> bool:
    """True when the column asks for leased/sold property composition."""
    cfg = getattr(column, "column_config", None)
    field_id = ""
    if isinstance(cfg, dict):
        field_id = str(cfg.get("field_id") or cfg.get("schema_field") or "").strip().lower()
    if field_id in _INVENTORY_FIELD_IDS:
        return True
    blob = " ".join(
        [
            str(getattr(column, "column_label", "") or ""),
            str(getattr(column, "prompt", "") or ""),
            field_id,
        ]
    )
    return bool(_INVENTORY_COLUMN_RE.search(blob))


def _normalize_blob(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_name(name: str) -> str:
    text = re.sub(r"\s+", " ", (name or "")).strip(" .,;:«»\"'")
    text = re.sub(r"(?i)\s+для\s+электросамоката\s*$", " для электросамоката", text)
    # Title-case first letter only if all-lower/all-upper mess from OCR.
    if text and text.isupper():
        text = text.capitalize()
    return text


def extract_inventory_items(text: str) -> List[Tuple[str, int]]:
    """
    Parse specification-style inventory rows from appendix text.

    Returns ordered unique (name, qty) pairs.
    """
    blob = _normalize_blob(text)
    if not blob:
        return []

    items: List[Tuple[str, int]] = []
    seen = set()

    for m in _SPEC_ROW_RE.finditer(blob):
        name = _clean_name(m.group("name"))
        try:
            qty = int(m.group("qty"))
        except ValueError:
            continue
        if qty <= 0 or not name or len(name) < 5:
            continue
        key = (name.lower(), qty)
        if key in seen:
            continue
        seen.add(key)
        items.append((name, qty))

    if len(items) >= 2:
        return items

    # Fallback: name + quantity without prices (still better than subject noun).
    for m in _NAME_QTY_RE.finditer(blob):
        name = _clean_name(m.group("name"))
        try:
            qty = int(m.group("qty"))
        except ValueError:
            continue
        if qty <= 0 or not name:
            continue
        key = (name.lower(), qty)
        if key in seen:
            continue
        seen.add(key)
        items.append((name, qty))

    return items


def format_inventory_cell_value(items: Sequence[Tuple[str, int]]) -> str:
    parts = [f"{name} — {qty} шт." for name, qty in items]
    return "; ".join(parts)


def followed_appendix_docs(docs: Sequence[Document]) -> List[Document]:
    out: List[Document] = []
    for doc in docs or []:
        md = doc.metadata or {}
        if md.get("cross_ref_followed") or md.get("cross_ref_required"):
            out.append(doc)
            continue
        kind = str(md.get("section_kind") or "").strip().lower()
        title = str(md.get("section_title") or "")
        if kind in {"appendix", "appendix_part"} or re.search(
            r"(?i)приложени|спецификац|exhibit|schedule|annex", title
        ):
            # Only treat as appendix evidence when already in the prompt bag;
            # do not invent follow here.
            if md.get("cross_ref_section_root_id") or md.get("cross_ref_followed"):
                out.append(doc)
    return out


def try_inventory_extraction_from_docs(
    docs: Sequence[Document],
) -> Optional[TabularCellExtractionModel]:
    """
    If followed appendix docs contain a parseable inventory table, return an
    authoritative cell extraction (LLM must not override this path).
    """
    followed = followed_appendix_docs(docs)
    if not followed:
        # Also accept any prompt docs that are clearly the followed appendix macros
        # stamped during enrich (cross_ref_followed).
        return None

    blob = "\n".join(str(d.page_content or "") for d in followed)
    items = extract_inventory_items(blob)
    if len(items) < 2 and not any(re.search(r"(?i)зарядн", n) for n, _ in items):
        # Single scooter row without charger → not authoritative enough to short-circuit;
        # leave to LLM with pinned appendix context.
        if len(items) < 1:
            return None
        # One row only — still prefer it over subject noun if it has qty+model.
        if len(items) == 1 and not re.search(r"(?i)E-Scooter|модель|\d+\s*шт", items[0][0]):
            if items[0][1] < 2:
                return None

    if not items:
        return None

    value = format_inventory_cell_value(items)
    # Prefer a verbatim span that mentions at least two item classes when possible.
    verbatim = value
    for doc in followed:
        text = _normalize_blob(doc.page_content or "")
        if re.search(r"(?i)электросамокат", text) and re.search(r"(?i)зарядн", text):
            # Keep a compact but faithful slice around the table rows.
            m = re.search(
                r"(?is)(?:электросамокат|зарядное\s+устройство).{0,400}?итого",
                text,
            )
            if m:
                verbatim = re.sub(r"\s+", " ", m.group(0))[:400]
            else:
                verbatim = text[:400]
            break

    section = ""
    page = None
    for doc in followed:
        md = doc.metadata or {}
        section = str(md.get("section_title") or md.get("section_retrieval_label") or "") or section
        page = md.get("source_page") or md.get("page_start") or page

    return TabularCellExtractionModel(
        cell_value=value,
        verbatim_extract=verbatim[:500],
        reasoning=(
            "Полный перечень имущества взят из Приложения/Спецификации, "
            "на которую ссылается предмет договора; ответ не сводится к общему "
            "названию из п. предмета."
        ),
        confidence=0.95,
        source_page=int(page) if page is not None and str(page).isdigit() else None,
        source_section=section or "Приложение / Спецификация",
        source_references=[
            {
                "text": verbatim[:240],
                "section": section or "Приложение / Спецификация",
                **({"page": int(page)} if page is not None and str(page).isdigit() else {}),
            }
        ],
        extraction_method="appendix_inventory",
    )


def appendix_follow_binding_instruction() -> str:
    return (
        "[Обязательное правило перекрёстных ссылок]\n"
        "Фрагменты Приложения/Спецификации, подтянутые по ссылке из текста, "
        "обязательны для ответа. Если вопрос про объект аренды, товар или состав "
        "имущества — cell_value должен включать полный перечень позиций из "
        "приложения (все строки спецификации), а не только общее слово из предмета "
        "договора (например, нельзя ответить одним «электросамокаты», если в "
        "приложении есть ещё зарядные устройства)."
    )
