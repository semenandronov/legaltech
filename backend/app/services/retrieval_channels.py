"""
Multi-channel retrieval plan and evidence pinning.

Contract (production):
  1. Rewrite a lawyer question into:
       - semantic_query  → dense / hybrid
       - lexical_terms   → independent keyword/literal channel
       - exact_query     → clause-boundary channel (optional)
       - exact_literals  → amounts / quoted / proper tokens (optional)
  2. Each channel recalls independently.
  3. Merge preserves strong literal hits — they cannot sink under semantic noise.
  4. Literal / clause pins bypass rerank and lead the model context.
  5. Prefer short clean fragments over huge headers when presenting evidence.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.clause_anchor import (
    clause_anchor_doc_identity,
    exclude_docs_by_identity,
    is_exact_channel_doc,
    merge_pinned_clause_anchors,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_LEXICAL_PINS = 3
_SHORT_EVIDENCE_MAX_CHARS = 1800

# Function words / question scaffolding that must not drive lexical recall alone.
_LEXICAL_STOP = frozenset(
    {
        "а",
        "и",
        "или",
        "в",
        "во",
        "на",
        "по",
        "из",
        "для",
        "о",
        "об",
        "про",
        "к",
        "ко",
        "с",
        "со",
        "у",
        "от",
        "до",
        "при",
        "без",
        "над",
        "под",
        "это",
        "как",
        "какой",
        "какая",
        "какие",
        "какую",
        "каким",
        "что",
        "чем",
        "ли",
        "есть",
        "был",
        "была",
        "было",
        "были",
        "будет",
        "быть",
        "можно",
        "нужно",
        "надо",
        "этот",
        "эта",
        "эти",
        "тот",
        "та",
        "те",
        "его",
        "ее",
        "её",
        "их",
        "мне",
        "нам",
        "вас",
        "вы",
        "он",
        "она",
        "они",
        "мы",
        "я",
        "документе",
        "документа",
        "документ",
        "договоре",
        "договора",
        "договор",
        "тексте",
        "текста",
        "пожалуйста",
        "полностью",
        "целиком",
        "дословно",
        "укажи",
        "укажите",
        "найди",
        "найдите",
        "пришли",
        "пришлите",
        "предусмотрена",
        "предусмотрен",
        "предусмотрено",
        "предусмотрены",
        "является",
        "являются",
        # English scaffolding (MAE / contract review)
        "the",
        "and",
        "or",
        "for",
        "with",
        "from",
        "that",
        "this",
        "shall",
        "mean",
        "means",
        "section",
        "article",
        "agreement",
        "company",
        "party",
        "parties",
        "whether",
        "any",
        "all",
        "such",
        "under",
        "upon",
        "into",
        "including",
        "except",
        "provided",
        "herein",
        "thereof",
        "pursuant",
        "you",
        "are",
        "public",
        "reviewing",
        "concise",
        "exact",
        "value",
        "used",
        "example",
        "yes",
        "annotations",
        "field",
        "type",
        "deal",
        "point",
        "question",
        "answer",
    }
)

_TOKEN_RE = re.compile(
    r"[a-zа-яё]+(?:-[a-zа-яё]+)?|\d+(?:[.,]\d+)+|\d[\d\s]{2,}\d",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[\s\u00a0]\d{3})+|\d+)(?:[.,]\d+)?(?!\d)",
)
_QUOTED_RE = re.compile(r"[«\"]([^»\"]{2,80})[»\"]")


@dataclass(frozen=True)
class RetrievalQueryPlan:
    """Normalized multi-channel retrieval inputs for one question."""

    semantic_query: str
    lexical_terms: Tuple[str, ...] = ()
    exact_query: Optional[str] = None
    exact_literals: Tuple[str, ...] = ()
    source_query: str = ""
    method: str = "passthrough"
    rationale: str = ""

    @property
    def search_query(self) -> str:
        return self.semantic_query

    def lexical_query_text(self) -> str:
        return " ".join(self.lexical_terms).strip()


def normalize_match_text(text: str) -> str:
    s = (text or "").lower().replace("ё", "е").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def term_stem(term: str) -> str:
    """Lightweight Russian flexion stem (prefix) for literal matching."""
    t = normalize_match_text(term)
    t = re.sub(r"[^a-zа-я0-9.]+", "", t)
    if not t:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)+", t):
        return t
    if len(t) <= 4:
        return t
    if len(t) <= 6:
        return t[:-1]
    return t[:-2]


def term_matches_text(term: str, text: str) -> bool:
    """True when term or its flexion stem appears in text."""
    body = normalize_match_text(text)
    if not body:
        return False
    raw = normalize_match_text(term)
    if not raw:
        return False
    compact_body = body.replace(" ", "")
    compact_raw = raw.replace(" ", "")
    if raw in body or compact_raw in compact_body:
        return True
    stem = term_stem(raw)
    if len(stem) >= 4 and stem in compact_body:
        return True
    return False


def extract_lexical_terms(*texts: str, limit: int = 12) -> Tuple[str, ...]:
    """Content terms for the independent lexical channel."""
    seen: set[str] = set()
    out: List[str] = []
    for text in texts:
        for raw in _TOKEN_RE.findall(normalize_match_text(text)):
            tok = raw.strip().lower().replace("ё", "е")
            if len(tok) < 3:
                continue
            if tok in _LEXICAL_STOP:
                continue
            if tok.isdigit() and len(tok) < 3:
                continue
            stem = term_stem(tok)
            key = stem or tok
            if key in seen:
                continue
            seen.add(key)
            out.append(tok)
            if len(out) >= limit:
                return tuple(out)
    return tuple(out)


def extract_exact_literals(text: str, *, limit: int = 6) -> Tuple[str, ...]:
    """Amounts / quoted phrases that deserve literal boost."""
    src = text or ""
    out: List[str] = []
    seen: set[str] = set()
    for m in _QUOTED_RE.finditer(src):
        val = normalize_match_text(m.group(1))
        if len(val) < 2 or val in seen:
            continue
        seen.add(val)
        out.append(val)
        if len(out) >= limit:
            return tuple(out)
    for m in _AMOUNT_RE.finditer(src):
        raw = re.sub(r"\s+", " ", m.group(0)).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 4:
            continue
        key = digits
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
        if len(out) >= limit:
            break
    return tuple(out)


def is_interrogative_query(text: str) -> bool:
    t = normalize_match_text(text)
    if not t:
        return False
    if "?" in (text or ""):
        return True
    return bool(
        re.search(
            r"(?:\bли\b|\bесть\b|\bпредусмотр|\bявляется\b|\bуказан|\bсодержит\b)",
            t,
        )
    )


def count_term_hits(terms: Sequence[str], text: str) -> Tuple[int, List[str]]:
    """Count distinct stem hits (flexions of the same lemma count once)."""
    hits: List[str] = []
    seen_stems: set[str] = set()
    for term in terms:
        if not term_matches_text(term, text):
            continue
        stem = term_stem(term) or normalize_match_text(term)
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        hits.append(term)
    return len(hits), hits


def dedupe_terms_by_stem(terms: Sequence[str], *, limit: int = 12) -> Tuple[str, ...]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in terms:
        term = str(raw or "").strip()
        if not term:
            continue
        stem = term_stem(term) or normalize_match_text(term)
        if not stem or stem in seen:
            continue
        seen.add(stem)
        out.append(term)
        if len(out) >= limit:
            break
    return tuple(out)


def _doc_text(doc: Document) -> str:
    return str(getattr(doc, "page_content", None) or "")


def _doc_meta(doc: Document) -> Dict[str, Any]:
    md = getattr(doc, "metadata", None)
    return dict(md) if isinstance(md, dict) else {}


def is_lexical_channel_doc(doc: Any) -> bool:
    md = _doc_meta(doc) if not isinstance(doc, dict) else dict(doc)
    if isinstance(doc, Document):
        md = _doc_meta(doc)
    return bool(md.get("lexical_match") or md.get("lexical_pinned") or md.get("literal_channel"))


def _chunk_level(doc: Document) -> str:
    return str(_doc_meta(doc).get("chunk_level") or "").strip().lower()


def _prefer_short_evidence(doc: Document) -> Tuple[int, int, int]:
    """Sort key: micro first, then shorter text, then higher lexical score."""
    level = _chunk_level(doc)
    level_rank = 0 if level in {"micro", "row", "docling"} else 1 if level else 2
    text_len = len(_doc_text(doc))
    score = 0.0
    raw = _doc_meta(doc).get("lexical_score")
    try:
        score = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    return (level_rank, -int(score * 1000), text_len)


def recall_lexical_term_docs(
    *,
    case_id: str,
    file_ids: Sequence[str],
    terms: Sequence[str],
    vector_store: Any,
    k: int = 8,
) -> List[Document]:
    """
    Independent lexical channel: scan scoped file chunks for term/stem hits.

    Does not depend on dense similarity. Tags survivors with ``lexical_match``.
    """
    clean_terms = list(
        dedupe_terms_by_stem(
            [str(t).strip() for t in terms if str(t).strip()],
            limit=16,
        )
    )
    fids = [str(x).strip() for x in file_ids if str(x).strip()]
    if not clean_terms or not fids or not case_id or vector_store is None:
        return []
    if not hasattr(vector_store, "list_chunks_by_file"):
        return []

    scored: List[Tuple[float, Document]] = []
    seen: set[str] = set()
    for fid in fids:
        try:
            chunks = vector_store.list_chunks_by_file(str(case_id), fid) or []
        except Exception as exc:
            logger.debug("lexical recall list_chunks failed file=%s: %s", fid, exc)
            continue
        for chunk in chunks:
            if chunk is None:
                continue
            text = _doc_text(chunk)
            if not text.strip():
                continue
            hit_n, hit_terms = count_term_hits(clean_terms, text)
            if hit_n <= 0:
                continue
            key = clause_anchor_doc_identity(chunk)
            if key in seen:
                continue
            seen.add(key)
            level = _chunk_level(chunk)
            # Prefer micro/clause evidence over giant headers.
            level_bonus = 1.35 if level in {"micro", "row", "docling"} else 1.0
            length_penalty = 1.0 if len(text) <= _SHORT_EVIDENCE_MAX_CHARS else 0.55
            score = (hit_n / max(1, len(clean_terms))) * 10.0 * level_bonus * length_penalty
            # Extra boost when multiple distinct terms co-occur.
            if hit_n >= 2:
                score += 2.0
            md = _doc_meta(chunk)
            md["lexical_match"] = True
            md["literal_channel"] = True
            md["lexical_score"] = float(score)
            md["lexical_term_hits"] = list(hit_terms)
            try:
                chunk.metadata = md
            except Exception:
                pass
            scored.append((score, chunk))

    scored.sort(key=lambda pair: (-pair[0], _prefer_short_evidence(pair[1])))
    return [doc for _sc, doc in scored[: max(1, int(k))]]


def select_pinned_lexical_docs(
    docs: Sequence[Document],
    *,
    terms: Sequence[str],
    max_pins: int = DEFAULT_MAX_LEXICAL_PINS,
) -> List[Document]:
    """Top verified lexical hits that bypass rerank (same contract as clause pins)."""
    clean_terms = list(
        dedupe_terms_by_stem(
            [str(t).strip() for t in terms if str(t).strip()],
            limit=16,
        )
    )
    if not docs or not clean_terms:
        return []
    limit = max(1, min(5, int(max_pins or DEFAULT_MAX_LEXICAL_PINS)))
    candidates: List[Document] = []
    for doc in docs:
        if doc is None:
            continue
        text = _doc_text(doc)
        if not text.strip():
            continue
        hit_n, hit_terms = count_term_hits(clean_terms, text)
        if hit_n <= 0:
            continue
        # Prefer channel-tagged docs, but recover unflagged copies that still match.
        md = _doc_meta(doc)
        if not md.get("lexical_match") and hit_n < 1:
            continue
        md = dict(md)
        md["lexical_match"] = True
        md["lexical_term_hits"] = list(hit_terms)
        if md.get("lexical_score") is None:
            md["lexical_score"] = float(hit_n)
        try:
            doc.metadata = md
        except Exception:
            pass
        candidates.append(doc)

    candidates.sort(
        key=lambda d: (
            0 if is_lexical_channel_doc(d) else 1,
            _prefer_short_evidence(d),
        )
    )
    out: List[Document] = []
    seen: set[str] = set()
    for doc in candidates:
        key = clause_anchor_doc_identity(doc)
        if key in seen:
            continue
        # Skip enormous non-micro dumps unless they are the only evidence.
        if (
            len(_doc_text(doc)) > _SHORT_EVIDENCE_MAX_CHARS
            and _chunk_level(doc) not in {"micro", "row", "docling"}
            and len(out) > 0
        ):
            continue
        seen.add(key)
        out.append(doc)
        if len(out) >= limit:
            break
    return out


def merge_retrieval_channels(
    *,
    exact_docs: Sequence[Document] = (),
    lexical_docs: Sequence[Document] = (),
    hybrid_docs: Sequence[Document] = (),
    limit: Optional[int] = None,
) -> List[Document]:
    """
    Exact → lexical → hybrid fill.

    Identity collisions keep the higher-priority channel copy (flags preserved).
    """
    merged: List[Document] = []
    seen: set[str] = set()

    def _add(seq: Sequence[Document]) -> None:
        for doc in seq:
            if doc is None:
                continue
            key = clause_anchor_doc_identity(doc)
            if key in seen:
                continue
            seen.add(key)
            merged.append(doc)

    _add(exact_docs)
    _add(lexical_docs)
    _add(hybrid_docs)
    if isinstance(limit, int) and limit > 0:
        return merged[:limit]
    return merged


def merge_evidence_pins(
    *,
    exact_pins: Sequence[Document],
    lexical_pins: Sequence[Document],
    ranked: Sequence[Document],
    final_k: int,
) -> List[Document]:
    """
    Pins always lead. Exact pins first, then lexical, then ranked fill.

    Additive: pins do not consume the ranked budget.
    """
    # Mark lexical pins for observability / assemble preference.
    marked_lexical: List[Document] = []
    for doc in lexical_pins:
        if doc is None:
            continue
        md = _doc_meta(doc)
        md["lexical_pinned"] = True
        md["literal_channel"] = True
        md["exact_channel"] = bool(md.get("exact_channel") or md.get("anchor_pinned"))
        try:
            doc.metadata = md
        except Exception:
            pass
        marked_lexical.append(doc)

    # Reuse clause merge for exact pins, then prepend lexical that are not already there.
    with_exact = merge_pinned_clause_anchors(
        exact_pins,
        list(ranked),
        final_k=final_k,
        additive_ranked=True,
    )
    # Insert lexical pins after exact pins, before ranked body.
    exact_n = 0
    for doc in with_exact:
        if is_exact_channel_doc(doc) or (_doc_meta(doc).get("anchor_pinned")):
            exact_n += 1
        else:
            break

    head = list(with_exact[:exact_n])
    tail = list(with_exact[exact_n:])
    return merge_retrieval_channels(
        exact_docs=head,
        lexical_docs=marked_lexical,
        hybrid_docs=tail,
    )


def prefer_short_docs_for_prompt(
    docs: Sequence[Document],
    *,
    max_lead_chars: int = _SHORT_EVIDENCE_MAX_CHARS,
) -> List[Document]:
    """
    Stable reorder for assemble: pinned/short evidence first, huge headers later.

    Does not drop docs — only reorders so the model sees clean proof first.
    """
    if not docs:
        return []
    lead: List[Document] = []
    rest: List[Document] = []
    for doc in docs:
        md = _doc_meta(doc)
        pinned = bool(
            md.get("anchor_pinned")
            or md.get("lexical_pinned")
            or md.get("exact_channel")
            or md.get("lexical_match")
        )
        short = len(_doc_text(doc)) <= max_lead_chars
        micro = _chunk_level(doc) in {"micro", "row", "docling"}
        if pinned or (short and micro):
            lead.append(doc)
        else:
            rest.append(doc)
    return lead + rest
