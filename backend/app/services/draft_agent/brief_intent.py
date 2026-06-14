"""Parse lawyer brief and choose draft execution strategy."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Literal

DraftTemplateMode = Literal["catalog_fill", "template_guide", "scratch"]


def _normalize_party_name(raw: str) -> str:
    name = (raw or "").strip().strip("«»\"' ")
    if not name:
        return ""
    if "ооо" not in name.lower() and len(name) > 2:
        if re.match(r"^[А-ЯA-Z]", name):
            return f"ООО «{name}»"
    if "«" not in name and "ооо" in name.lower():
        m = re.search(r"ооо\s+(.+)", name, re.I)
        if m:
            inner = m.group(1).strip().strip("«»")
            return f"ООО «{inner}»"
    return name[:200]


@dataclass(frozen=True)
class DraftBriefIntent:
    """Structured understanding of the lawyer request before RAG/template routing."""

    document_type_hint: str = ""
    requires_financial_calc: bool = False
    requires_materials_pipeline: bool = False
    parties_from_brief: Dict[str, str] = field(default_factory=dict)
    routing_reason: str = ""

    def effective_template_mode(self, resolved_mode: DraftTemplateMode) -> DraftTemplateMode:
        """Шаблон с плейсхолдерами всегда заполняется через catalog_fill."""
        return resolved_mode

    def to_state_dict(self) -> Dict[str, object]:
        return {
            "document_type_hint": self.document_type_hint,
            "requires_financial_calc": self.requires_financial_calc,
            "requires_materials_pipeline": self.requires_materials_pipeline,
            "parties_from_brief": dict(self.parties_from_brief),
            "routing_reason": self.routing_reason,
        }

    @classmethod
    def from_state_dict(cls, raw: Dict[str, object]) -> "DraftBriefIntent":
        if not isinstance(raw, dict):
            return cls()
        parties_raw = raw.get("parties_from_brief") or {}
        parties = (
            {str(k): str(v) for k, v in parties_raw.items() if str(v).strip()}
            if isinstance(parties_raw, dict)
            else {}
        )
        return cls(
            document_type_hint=str(raw.get("document_type_hint") or ""),
            requires_financial_calc=bool(raw.get("requires_financial_calc")),
            requires_materials_pipeline=bool(raw.get("requires_materials_pipeline")),
            parties_from_brief=parties,
            routing_reason=str(raw.get("routing_reason") or ""),
        )


def parse_draft_brief(user_prompt: str) -> DraftBriefIntent:
    """Heuristic planner: infer document type, parties, and pipeline needs from brief."""
    text = (user_prompt or "").strip()
    low = text.lower()

    is_claim = any(token in low for token in ("исков", "иск о", "иск в", " подать иск"))
    is_pretension = "претенз" in low

    requires_financial = any(
        token in low
        for token in (
            "неусто",
            "задолжен",
            "долг",
            "взыск",
            "пени",
            "процент",
            "сумм",
            "руб",
            "оплат",
        )
    )

    doc_type = ""
    if is_claim:
        doc_type = "исковое заявление"
    elif is_pretension:
        doc_type = "претензия"

    parties: Dict[str, str] = {}

    patterns = [
        (r"истец\s*[—\-:,]\s*([^.\n;]+)", "истец"),
        (r"ответчик\s*[—\-:,]\s*([^.\n;]+)", "ответчик"),
        (r"в пользу\s+([^.\n;]+?)(?:\s+к\s+|\s+против\s+|$)", "истец"),
        (r"против\s+([^.\n;]+)", "ответчик"),
    ]
    for pattern, role in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and role not in parties:
            normalized = _normalize_party_name(m.group(1))
            if normalized:
                parties[role] = normalized

    # «Истец — Вектор-М, ответчик — ТехноСфера» on one line
    if "истец" in low and "ответчик" in low:
        pair = re.search(
            r"истец\s*[—\-:,]\s*([^,;]+?)\s*[,;]?\s*ответчик\s*[—\-:,]\s*([^.\n;]+)",
            text,
            re.IGNORECASE,
        )
        if pair:
            if "истец" not in parties:
                parties["истец"] = _normalize_party_name(pair.group(1))
            if "ответчик" not in parties:
                parties["ответчик"] = _normalize_party_name(pair.group(2))

    requires_pipeline = bool(is_claim and requires_financial)
    reason = ""
    if requires_pipeline:
        reason = "financial_statement_of_claim"

    return DraftBriefIntent(
        document_type_hint=doc_type,
        requires_financial_calc=requires_financial and (is_claim or is_pretension or requires_financial),
        requires_materials_pipeline=requires_pipeline,
        parties_from_brief=parties,
        routing_reason=reason,
    )
