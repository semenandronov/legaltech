from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class LegalInstrument:
    instrument_id: str  # slug, kebab-case
    short_name: str  # e.g. "127-ФЗ", "ГК РФ"
    title: str  # human label for UI
    aliases: Tuple[str, ...] = ()


# MVP registry (config_static): single source of truth for UI+router+ingestion.
# Keep ids stable: used in pgvector JSONB filters.
INSTRUMENTS: Dict[str, LegalInstrument] = {
    "fz-127": LegalInstrument(
        instrument_id="fz-127",
        short_name="127-ФЗ",
        title="127‑ФЗ «О несостоятельности (банкротстве)»",
        aliases=("127", "фз-127", "закон о банкротстве", "банкротство", "несостоятельность"),
    ),
    "gk-rf": LegalInstrument(
        instrument_id="gk-rf",
        short_name="ГК РФ",
        title="Гражданский кодекс РФ",
        aliases=("гк", "гк рф", "гражданский кодекс"),
    ),
    "apk-rf": LegalInstrument(
        instrument_id="apk-rf",
        short_name="АПК РФ",
        title="Арбитражный процессуальный кодекс РФ",
        aliases=("апк", "апк рф", "арбитражный процессуальный кодекс"),
    ),
    "gpk-rf": LegalInstrument(
        instrument_id="gpk-rf",
        short_name="ГПК РФ",
        title="Гражданский процессуальный кодекс РФ",
        aliases=("гпк", "гпк рф", "гражданский процессуальный кодекс"),
    ),
    "plenum-63": LegalInstrument(
        instrument_id="plenum-63",
        short_name="Пленум №63",
        title="ПП ВАС РФ №63 (оспаривание сделок в банкротстве)",
        aliases=("пленум 63", "пп вас 63", "постановление 63", "63", "пленум №63"),
    ),
    "other": LegalInstrument(
        instrument_id="other",
        short_name="Другое",
        title="Другое (не классифицировано)",
        aliases=(),
    ),
}


def list_instruments_for_api() -> List[dict]:
    out: List[dict] = []
    for iid, inst in INSTRUMENTS.items():
        out.append(
            {
                "instrument_id": iid,
                "short_name": inst.short_name,
                "title": inst.title,
                "aliases": list(inst.aliases or ()),
            }
        )
    # stable order for UI
    out.sort(key=lambda x: (x["instrument_id"] == "other", x["instrument_id"]))
    return out


def normalize_instrument_id(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    v = v.lower()
    # allow underscores as input; normalize to kebab
    v = v.replace("_", "-")
    return v


def resolve_instrument(value: Optional[str]) -> Optional[LegalInstrument]:
    iid = normalize_instrument_id(value)
    if not iid:
        return None
    if iid in INSTRUMENTS:
        return INSTRUMENTS[iid]
    # best-effort alias match
    for inst in INSTRUMENTS.values():
        if any(iid == a.lower().replace("_", "-") for a in (inst.aliases or ())):
            return inst
    return None


def instrument_short_name(instrument_id: Optional[str]) -> Optional[str]:
    inst = resolve_instrument(instrument_id)
    return inst.short_name if inst else None

