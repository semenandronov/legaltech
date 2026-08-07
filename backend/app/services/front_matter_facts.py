"""
Front-matter facts: structured identity / header evidence extracted at ingest.

Problem: dense/FTS retrieval buries preamble definitions (party roles, case
captions, contract numbers) under mid-document topical hits that reuse the
same words («Заказчик» in §4 obligations vs «именуемое Заказчик» in the header).

Solution (not a retrieval hack):
1. At ingest (or lazy backfill): LLM extracts labeled facts from the document
   front zone with verbatim quotes; we ground every quote to char spans.
2. At query: LLM classifies whether the question needs front-matter evidence;
   if yes, another LLM call selects matching facts by meaning (not keyword
   equality). Selected facts become primary RAG evidence with geometry spans.

Roles/labels are free-form — whatever the document uses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import config

logger = logging.getLogger(__name__)

FRONT_MATTER_VERSION = "fm-1"

FrontMatterKind = Literal[
    "party_role",
    "doc_number",
    "date",
    "case_id",
    "org",
    "person",
    "title",
    "other",
]

_HARD_SECTION_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"(?:\d{1,2}\.\s+[A-ZА-ЯЁ][A-ZА-ЯЁa-zа-яё \-]{2,80})|"
    r"(?:Статья\s+\d+)|"
    r"(?:РАЗДЕЛ\s+[IVXLCDM\d]+)|"
    r"(?:[IVXLCDM]{1,6}\.\s+[A-ZА-ЯЁ])|"
    r"(?:1\.\s*ПРЕДМЕТ)|"
    r"(?:ПРЕДМЕТ\s+ДОГОВОРА)"
    r")",
    re.IGNORECASE,
)

_WS_RE = re.compile(r"\s+")
_QUOTE_CHARS = "\"«»„“”'`"


def find_hard_body_section_start(text: str) -> Optional[int]:
    """
    Offset of the first hard body heading (e.g. «1. ПРЕДМЕТ…»), or None.

    Skips ultra-early letterhead false positives the same way as the front-matter zone cutter.
    """
    body = text or ""
    if not body.strip():
        return None
    search_from = min(120, max(0, len(body) // 20))
    match = _HARD_SECTION_RE.search(body, search_from)
    min_cut = min(80, max(40, search_from))
    if match and match.start() >= min_cut:
        return int(match.start())
    return None


def front_matter_facts_enabled() -> bool:
    return bool(getattr(config, "FRONT_MATTER_FACTS_ENABLED", True))


def front_matter_lazy_backfill_enabled() -> bool:
    return bool(getattr(config, "FRONT_MATTER_LAZY_BACKFILL", True))


def front_matter_extract_max_chars() -> int:
    return max(1500, int(getattr(config, "FRONT_MATTER_EXTRACT_MAX_CHARS", 5000) or 5000))


def front_matter_route_min_confidence() -> float:
    return float(getattr(config, "FRONT_MATTER_ROUTE_MIN_CONFIDENCE", 0.62) or 0.62)


def front_matter_match_min_confidence() -> float:
    return float(getattr(config, "FRONT_MATTER_MATCH_MIN_CONFIDENCE", 0.68) or 0.68)


def front_matter_model_name() -> str:
    return str(
        getattr(config, "FRONT_MATTER_FACTS_MODEL", None)
        or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", None)
        or "yandexgpt-lite/latest"
    )


class FrontMatterFact(BaseModel):
    """One grounded fact from the document header / preamble."""

    kind: FrontMatterKind = "other"
    label: str = Field(default="", description="Role or field name as in the document")
    value: str = Field(default="", description="Normalized answer value")
    quote: str = Field(default="", description="Verbatim substring from the source text")
    char_start: int = -1
    char_end: int = -1
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("label", "value", "quote", mode="before")
    @classmethod
    def _strip_text(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("kind", mode="before")
    @classmethod
    def _norm_kind(cls, v: Any) -> str:
        raw = str(v or "other").strip().lower()
        allowed = {
            "party_role",
            "doc_number",
            "date",
            "case_id",
            "org",
            "person",
            "title",
            "other",
        }
        return raw if raw in allowed else "other"


class FrontMatterPayload(BaseModel):
    version: str = FRONT_MATTER_VERSION
    content_hash: str = ""
    zone_end: int = 0
    extracted_at: str = ""
    facts: List[FrontMatterFact] = Field(default_factory=list)
    extractor: str = "llm"


class FrontMatterExtractLLMItem(BaseModel):
    kind: FrontMatterKind = "other"
    label: str = ""
    value: str = ""
    quote: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class FrontMatterExtractLLMOutput(BaseModel):
    facts: List[FrontMatterExtractLLMItem] = Field(default_factory=list)


class FrontMatterRouteLLMOutput(BaseModel):
    """LLM decision: does this question need front-matter / identity evidence?"""

    use_front_matter: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    information_need: str = Field(
        default="",
        description="Short Russian phrase: what identity/header fact is sought",
    )


class FrontMatterMatchLLMOutput(BaseModel):
    """LLM selects which stored facts answer the question."""

    fact_indices: List[int] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


@dataclass(frozen=True)
class FrontMatterEvidenceResult:
    used: bool
    context_text: str
    documents: List[Document]
    meta: Dict[str, Any]


def content_hash_for_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def select_front_matter_zone(text: str, *, max_chars: Optional[int] = None) -> Tuple[str, int]:
    """
    Take the document front zone: from start until the first hard section heading,
    capped by max_chars. Returns (zone_text, zone_end_offset).
    """
    body = text or ""
    if not body.strip():
        return "", 0
    cap = max_chars if max_chars is not None else front_matter_extract_max_chars()
    hard_at = find_hard_body_section_start(body)
    if hard_at is not None:
        # Stop at the hard section heading (keep preamble only).
        line_end = body.find("\n", hard_at)
        end = (line_end + 1) if line_end > hard_at else hard_at
    else:
        end = min(len(body), cap)
    end = min(end, cap, len(body))
    # Prefer ending on a paragraph boundary when truncating by cap.
    if end == cap and end < len(body):
        nl = body.rfind("\n\n", max(0, end - 400), end)
        if nl > end // 2:
            end = nl
    zone = body[:end]
    return zone, end


def _normalize_ws(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def locate_quote_span(full_text: str, quote: str) -> Optional[Tuple[int, int]]:
    """Ground a quote to char offsets; tolerant to whitespace / quote-mark drift."""
    q = (quote or "").strip()
    if not q or not full_text:
        return None
    idx = full_text.find(q)
    if idx >= 0:
        return idx, idx + len(q)

    soft = q.strip(_QUOTE_CHARS + " \t\n")
    if soft and soft != q:
        hit = locate_quote_span(full_text, soft)
        if hit is not None:
            return hit

    # Collapse whitespace in both strings; map match back to original offsets.
    norm_chars: List[str] = []
    norm_to_orig: List[int] = []
    i = 0
    n = len(full_text)
    while i < n:
        ch = full_text[i]
        if ch.isspace():
            while i < n and full_text[i].isspace():
                i += 1
            if norm_chars and norm_chars[-1] != " ":
                norm_chars.append(" ")
                norm_to_orig.append(i - 1)
            continue
        norm_chars.append(ch)
        norm_to_orig.append(i)
        i += 1
    joined = "".join(norm_chars)
    nq = _normalize_ws(q)
    if not nq:
        return None
    pos = joined.find(nq)
    if pos < 0:
        return None
    end_pos = pos + len(nq) - 1
    if pos >= len(norm_to_orig) or end_pos >= len(norm_to_orig):
        return None
    start = norm_to_orig[pos]
    end = norm_to_orig[end_pos] + 1
    if end <= start:
        return None
    return start, end


def ground_extracted_facts(
    full_text: str,
    raw_items: Sequence[FrontMatterExtractLLMItem],
) -> List[FrontMatterFact]:
    """Keep only facts whose quote grounds into full_text; set spans."""
    out: List[FrontMatterFact] = []
    seen: set[Tuple[str, str, int, int]] = set()
    for item in raw_items:
        quote = (item.quote or item.value or "").strip()
        if not quote or len(quote) < 3:
            continue
        span = locate_quote_span(full_text, quote)
        if span is None and item.value:
            # Try locating value alone inside a wider window
            span = locate_quote_span(full_text, item.value.strip())
            if span is not None:
                quote = full_text[span[0] : span[1]]
        if span is None:
            logger.debug(
                "Front-matter fact dropped (ungrounded): label=%r quote=%r",
                item.label,
                quote[:80],
            )
            continue
        cs, ce = span
        label = (item.label or item.kind or "fact").strip()
        value = (item.value or quote).strip()
        key = (label.lower(), value.lower(), cs, ce)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            FrontMatterFact(
                kind=item.kind,  # type: ignore[arg-type]
                label=label[:120],
                value=value[:500],
                quote=quote[:800],
                char_start=cs,
                char_end=ce,
                confidence=float(item.confidence or 0.7),
            )
        )
    return out


def payload_to_storage(payload: FrontMatterPayload) -> Dict[str, Any]:
    return payload.model_dump()


def payload_from_storage(raw: Any) -> Optional[FrontMatterPayload]:
    if not raw:
        return None
    try:
        if isinstance(raw, FrontMatterPayload):
            return raw
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            return None
        return FrontMatterPayload.model_validate(raw)
    except Exception:
        logger.debug("Invalid front_matter_facts payload", exc_info=True)
        return None


def _create_fm_llm(*, max_tokens: int = 1200) -> Any:
    from app.services.llm_factory import create_legal_llm

    return create_legal_llm(
        model=front_matter_model_name(),
        temperature=0.0,
        timeout=90.0,
        max_tokens=max_tokens,
    )


def _invoke_structured(llm: Any, schema: type[BaseModel], messages: list) -> Optional[BaseModel]:
    if hasattr(llm, "with_structured_output"):
        try:
            structured = llm.with_structured_output(schema)
            parsed = structured.invoke(messages)
            if isinstance(parsed, schema):
                return parsed
            if isinstance(parsed, dict):
                return schema.model_validate(parsed)
        except Exception:
            logger.debug("Front-matter structured LLM failed for %s", schema.__name__, exc_info=True)
    try:
        resp = llm.invoke(messages)
        text = resp.content if hasattr(resp, "content") else str(resp)
        match = re.search(r"\{[\s\S]*\}", text or "")
        if not match:
            return None
        return schema.model_validate_json(match.group())
    except Exception:
        logger.debug("Front-matter JSON parse failed for %s", schema.__name__, exc_info=True)
        return None


def extract_front_matter_facts(
    text: str,
    *,
    filename: str = "",
    allow_llm: bool = True,
) -> FrontMatterPayload:
    """
    LLM-extract grounded front-matter facts from document text.
    Empty payload on failure (never raises for caller convenience).
    """
    body = text or ""
    chash = content_hash_for_text(body)
    zone, zone_end = select_front_matter_zone(body)
    empty = FrontMatterPayload(
        version=FRONT_MATTER_VERSION,
        content_hash=chash,
        zone_end=zone_end,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        facts=[],
        extractor="none",
    )
    if not zone.strip() or not allow_llm or not front_matter_facts_enabled():
        return empty

    system = """Ты извлекаешь ФАКТЫ ИЗ ШАПКИ / ПРЕАМБУЛЫ юридического документа.
Верни только JSON: {"facts":[...]} .

Каждый факт:
- kind: party_role | doc_number | date | case_id | org | person | title | other
- label: как в документе (Заказчик, Подрядчик, Истец, Арендодатель, № договора, Дата…) — БЕЗ фиксированного списка ролей
- value: краткий ответ (наименование / номер / дата)
- quote: ДОСЛОВНАЯ цитата из переданного фрагмента (обязательно substring исходного текста)
- confidence: 0..1

Правила:
- Бери только факты из начала документа (стороны, роли «именуемое…», реквизиты, номер дела, дата, город, название).
- Для формулы «именуемое/именуемый в дальнейшем «Роль»» kind=party_role, label=Роль, value=наименование стороны,
  quote — фрагмент с наименованием И ролью (если помещается).
- НЕ извлекай обязанности из середины договора, пункты 1.1+, условия оплаты.
- Если ролей несколько — отдельный факт на каждую.
- quote обязан быть точной цитатой; без цитаты факт не включай.
- Не выдумывай. Если шапка пустая — {"facts":[]}."""

    human = (
        f"Имя файла: {filename or '—'}\n"
        f"Фрагмент начала документа (символы 0..{zone_end}):\n"
        f"---\n{zone}\n---"
    )
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    try:
        llm = _create_fm_llm(max_tokens=1400)
        parsed = _invoke_structured(llm, FrontMatterExtractLLMOutput, messages)
    except Exception:
        logger.warning("Front-matter extract LLM invoke failed", exc_info=True)
        return empty

    items: List[FrontMatterExtractLLMItem] = []
    if isinstance(parsed, FrontMatterExtractLLMOutput):
        items = list(parsed.facts or [])
    grounded = ground_extracted_facts(body, items)
    return FrontMatterPayload(
        version=FRONT_MATTER_VERSION,
        content_hash=chash,
        zone_end=zone_end,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        facts=grounded,
        extractor="llm",
    )


def save_front_matter_on_file(file_model: Any, payload: FrontMatterPayload) -> None:
    """Persist payload onto a File ORM instance (caller commits)."""
    if file_model is None:
        return
    file_model.front_matter_facts = payload_to_storage(payload)


def load_front_matter_from_file(file_model: Any) -> Optional[FrontMatterPayload]:
    if file_model is None:
        return None
    return payload_from_storage(getattr(file_model, "front_matter_facts", None))


def ensure_front_matter_payload(
    db: Session,
    *,
    file_id: str,
    text: str,
    filename: str = "",
    allow_llm: bool = True,
) -> Optional[FrontMatterPayload]:
    """
    Return stored facts if present and hash-compatible; otherwise extract and save.
    """
    if not front_matter_facts_enabled():
        return None
    from app.models.case import File as FileModel

    row = db.query(FileModel).filter(FileModel.id == str(file_id)).first()
    if row is None:
        return None
    existing = load_front_matter_from_file(row)
    chash = content_hash_for_text(text or getattr(row, "original_text", "") or "")
    if (
        existing
        and existing.facts
        and (not existing.content_hash or existing.content_hash == chash)
    ):
        return existing
    if not allow_llm:
        return existing
    if existing and not front_matter_lazy_backfill_enabled() and existing.facts:
        return existing
    # Fresh extract (ingest or lazy backfill)
    source = text or str(getattr(row, "original_text", "") or "")
    if not source.strip():
        return existing
    payload = extract_front_matter_facts(
        source,
        filename=filename or str(getattr(row, "filename", "") or ""),
        allow_llm=True,
    )
    save_front_matter_on_file(row, payload)
    try:
        db.commit()
    except Exception:
        logger.warning("Could not persist front_matter_facts for %s", file_id, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
    return payload


def route_front_matter_question(
    question: str,
    *,
    column_label: str = "",
    allow_llm: bool = True,
) -> FrontMatterRouteLLMOutput:
    """LLM: is this an identity / header-requisites question?"""
    q = (question or "").strip()
    if not q or not allow_llm or not front_matter_facts_enabled():
        return FrontMatterRouteLLMOutput(use_front_matter=False, confidence=0.0, reason="disabled")

    # Hard negative: numbered clause lookup is never front-matter.
    if re.search(r"(?i)\b(?:п(?:ункт)?\.?\s*)\d+(?:\.\d+)+\b", q) or re.search(
        r"(?i)\bстатья\s+\d+", q
    ):
        return FrontMatterRouteLLMOutput(
            use_front_matter=False,
            confidence=0.95,
            reason="clause_anchor_question",
            information_need="",
        )

    system = """Ты классификатор для юридической RAG-системы.
Вопрос касается ФАКТОВ ШАПКИ / ПРЕАМБУЛЫ документа?
(кто сторона и под какой ролью; наименование стороны; истец/ответчик; номер договора/дела из шапки; дата заключения в шапке; город подписания)

НЕ шапка (use_front_matter=false):
- содержание пунктов, обязанности, сроки исполнения, цена, ответственность, предмет работ по смыслу раздела
- вопросы «о чём пункт / что сказано в разделе»

Верни JSON:
{"use_front_matter": true|false, "confidence": 0..1, "reason": "...", "information_need": "кратко что ищем"}

Решай по СМЫСЛУ вопроса, не по одному совпавшему слову."""

    human = (
        f"Название колонки (если есть): {column_label or '—'}\n"
        f"Вопрос:\n{q}"
    )
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    try:
        llm = _create_fm_llm(max_tokens=200)
        parsed = _invoke_structured(llm, FrontMatterRouteLLMOutput, messages)
        if isinstance(parsed, FrontMatterRouteLLMOutput):
            return parsed
    except Exception:
        logger.debug("Front-matter route failed", exc_info=True)
    return FrontMatterRouteLLMOutput(use_front_matter=False, confidence=0.0, reason="route_failed")


def match_front_matter_facts(
    question: str,
    facts: Sequence[FrontMatterFact],
    *,
    information_need: str = "",
    allow_llm: bool = True,
) -> FrontMatterMatchLLMOutput:
    """LLM: which stored facts answer the question (by meaning, any labels)."""
    if not facts or not allow_llm:
        return FrontMatterMatchLLMOutput(fact_indices=[], confidence=0.0, reason="no_facts")

    catalog_lines = []
    for i, f in enumerate(facts):
        catalog_lines.append(
            f"[{i}] kind={f.kind} label={f.label!r} value={f.value!r} quote={f.quote[:180]!r}"
        )
    catalog = "\n".join(catalog_lines)

    system = """Выбери факты шапки, которые отвечают на вопрос юриста.
Сравнивай по СМЫСЛУ (заказчик ≈ сторона с label Заказчик; истец ≈ Истец и т.д.).
Роли в документах разные — не требуй точного совпадения строки вопроса и label.
Если ни один факт не отвечает — fact_indices=[] и низкая confidence.
Верни JSON: {"fact_indices":[0,1], "confidence":0..1, "reason":"..."}
Индексы только из каталога. Не выдумывай факты."""

    human = (
        f"Вопрос: {question}\n"
        f"Потребность (если есть): {information_need or '—'}\n"
        f"Каталог фактов:\n{catalog}"
    )
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    try:
        llm = _create_fm_llm(max_tokens=250)
        parsed = _invoke_structured(llm, FrontMatterMatchLLMOutput, messages)
        if isinstance(parsed, FrontMatterMatchLLMOutput):
            valid = [i for i in parsed.fact_indices if isinstance(i, int) and 0 <= i < len(facts)]
            # dedupe preserve order
            seen: set[int] = set()
            uniq: List[int] = []
            for i in valid:
                if i not in seen:
                    seen.add(i)
                    uniq.append(i)
            return FrontMatterMatchLLMOutput(
                fact_indices=uniq,
                confidence=float(parsed.confidence or 0.0),
                reason=parsed.reason or "",
            )
    except Exception:
        logger.debug("Front-matter match failed", exc_info=True)
    return FrontMatterMatchLLMOutput(fact_indices=[], confidence=0.0, reason="match_failed")


def facts_to_documents(
    facts: Sequence[FrontMatterFact],
    *,
    file_id: str,
    filename: str = "",
    indices: Optional[Sequence[int]] = None,
) -> List[Document]:
    """Build leaf-like Documents with char spans for LLM context + PDF geometry."""
    docs: List[Document] = []
    chosen = list(indices) if indices is not None else list(range(len(facts)))
    for i in chosen:
        if i < 0 or i >= len(facts):
            continue
        f = facts[i]
        body = (
            f"[Факт шапки документа]\n"
            f"Вид: {f.kind}\n"
            f"Метка: {f.label}\n"
            f"Значение: {f.value}\n"
            f"Цитата: {f.quote}"
        )
        docs.append(
            Document(
                page_content=body,
                metadata={
                    "chunk_id": f"front_matter:{file_id}:{i}",
                    "chunk_level": "micro",
                    "char_start": int(f.char_start),
                    "char_end": int(f.char_end),
                    "file_id": str(file_id),
                    "source_file": filename or "",
                    "filename": filename or "",
                    "retrieval_channel": "front_matter",
                    "front_matter_kind": f.kind,
                    "front_matter_label": f.label,
                    "front_matter_value": f.value,
                    "front_matter_quote": f.quote,
                    "front_matter_confidence": f.confidence,
                },
            )
        )
    return docs


def documents_are_front_matter(docs: Optional[Sequence[Document]]) -> bool:
    """True when retrieval evidence is exclusively from the front-matter channel."""
    if not docs:
        return False
    channels = {
        str((d.metadata or {}).get("retrieval_channel") or "").strip()
        for d in docs
        if d is not None
    }
    return bool(channels) and channels == {"front_matter"}


def extraction_dict_from_front_matter_docs(
    docs: Sequence[Document],
) -> Optional[Dict[str, Any]]:
    """
    Build a cell extraction payload from already-matched front-matter docs.

    Uses only the first matched fact's ``value`` (specific answer), not the whole card.
    Returns None if docs are not front-matter evidence.
    """
    if not documents_are_front_matter(docs):
        return None
    primary = next((d for d in docs if d is not None), None)
    if primary is None:
        return None
    md = primary.metadata or {}
    value = str(md.get("front_matter_value") or "").strip()
    quote = str(md.get("front_matter_quote") or "").strip()
    label = str(md.get("front_matter_label") or "").strip()
    kind = str(md.get("front_matter_kind") or "").strip()
    conf = md.get("front_matter_confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.92
    except (TypeError, ValueError):
        conf_f = 0.92
    conf_f = max(0.0, min(1.0, conf_f))

    if not value:
        # Recover from page_content "Значение: …" line if metadata missing (legacy).
        text = primary.page_content or ""
        for line in text.splitlines():
            if line.startswith("Значение:"):
                value = line.split(":", 1)[-1].strip()
                break
    if not value:
        return None
    if not quote:
        quote = value

    cs = md.get("char_start")
    ce = md.get("char_end")
    try:
        cs_i = int(cs) if cs is not None else None
        ce_i = int(ce) if ce is not None else None
    except (TypeError, ValueError):
        cs_i = ce_i = None

    reason_bits = ["Извлечено из фактов шапки документа без повторного LLM-extract"]
    if label:
        reason_bits.append(f"метка «{label}»")
    if kind:
        reason_bits.append(f"вид={kind}")

    return {
        "cell_value": value,
        "normalized_value": value,
        "verbatim_extract": quote[:500],
        "confidence": conf_f,
        "reasoning": "; ".join(reason_bits) + ".",
        "extraction_method": "front_matter",
        "source_references": [
            {
                "text": quote[:500],
                "page": md.get("source_page"),
                "section": label or "шапка",
                "char_start": cs_i,
                "char_end": ce_i,
            }
        ],
        "source_section": label or "шапка документа",
    }


def format_front_matter_context(docs: Sequence[Document]) -> str:
    if not docs:
        return ""
    parts = [
        "[Факты из шапки / преамбулы документа — приоритетный источник для этого вопроса]"
    ]
    for d in docs:
        parts.append((d.page_content or "").strip())
    return "\n\n".join(p for p in parts if p)


def resolve_front_matter_evidence(
    db: Session,
    *,
    file_id: str,
    question: str,
    column_label: str = "",
    filename: str = "",
    original_text: str = "",
    allow_llm: bool = True,
) -> FrontMatterEvidenceResult:
    """
    Full path: ensure facts → route → match → documents.
    ``used=False`` means caller should fall back to hybrid RAG.
    """
    meta: Dict[str, Any] = {"front_matter": True}
    if not front_matter_facts_enabled() or not (question or "").strip():
        return FrontMatterEvidenceResult(False, "", [], {**meta, "skipped": "disabled_or_empty"})

    text = original_text
    if not text:
        from app.models.case import File as FileModel

        row = db.query(FileModel).filter(FileModel.id == str(file_id)).first()
        text = str(getattr(row, "original_text", "") or "") if row else ""
        if not filename and row is not None:
            filename = str(getattr(row, "filename", "") or "")

    payload = ensure_front_matter_payload(
        db,
        file_id=str(file_id),
        text=text,
        filename=filename,
        allow_llm=allow_llm and front_matter_lazy_backfill_enabled(),
    )
    facts = list(payload.facts) if payload else []
    meta["facts_available"] = len(facts)
    if not facts:
        return FrontMatterEvidenceResult(False, "", [], {**meta, "skipped": "no_facts"})

    # Re-ground quotes against current text (handles whitespace / re-ingest drift)
    regrounded: List[FrontMatterFact] = []
    for f in facts:
        span = locate_quote_span(text, f.quote) if text else None
        if span is None and f.value:
            span = locate_quote_span(text, f.value)
        if span is None and f.char_start >= 0 and f.char_end > f.char_start and text:
            # Keep stored span if still plausible
            if f.char_end <= len(text):
                regrounded.append(f)
            continue
        if span is None:
            continue
        regrounded.append(
            f.model_copy(update={"char_start": span[0], "char_end": span[1]})
        )
    facts = regrounded or facts
    meta["facts_grounded"] = len(facts)

    route = route_front_matter_question(
        question,
        column_label=column_label,
        allow_llm=allow_llm,
    )
    meta["route"] = route.model_dump()
    if not route.use_front_matter or float(route.confidence) < front_matter_route_min_confidence():
        return FrontMatterEvidenceResult(
            False, "", [], {**meta, "skipped": "not_front_matter_intent"}
        )

    match = match_front_matter_facts(
        question,
        facts,
        information_need=route.information_need,
        allow_llm=allow_llm,
    )
    meta["match"] = match.model_dump()
    if (
        not match.fact_indices
        or float(match.confidence) < front_matter_match_min_confidence()
    ):
        return FrontMatterEvidenceResult(
            False, "", [], {**meta, "skipped": "no_confident_match"}
        )

    docs = facts_to_documents(
        facts,
        file_id=str(file_id),
        filename=filename,
        indices=match.fact_indices,
    )
    ctx = format_front_matter_context(docs)
    if not ctx.strip() or not docs:
        return FrontMatterEvidenceResult(False, "", [], {**meta, "skipped": "empty_docs"})

    meta["status"] = "front_matter_hit"
    meta["selected"] = len(docs)
    return FrontMatterEvidenceResult(True, ctx, docs, meta)
