"""
Within-file lexical retrieval for narrowly scoped case questions.

When the router already bound the question to specific file_ids, hybrid top-k
often surfaces titles/headers while missing the in-file fact clause (amount,
party signature, model code, term). For those scopes we load the indexed chunk
inventory of each scoped file and rank with BM25-lite (IDF over that file).

Production contract:
  hybrid recall (scoped) → within-file BM25 channel → assemble/rerank

No document-specific rules: same scoring for every case/file.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chat.document_ref_scope import extract_document_refs, normalize_doc_ref
from app.services.chat.retrieval_escalation import extract_question_anchors

logger = logging.getLogger(__name__)

# Words + product codes (МК088) + numbers (incl. №51, 98/2024) + long digit runs.
_TOKEN_RE = re.compile(
    r"[a-zа-яё]+(?:\d+[a-zа-яё]*)?|\d+[a-zа-яё]+|№?\d+(?:/\d+)?|[\d][\d\s]{4,}[\d]",
    re.IGNORECASE,
)

_QUESTION_STOP = frozenset(
    {
        "как",
        "какой",
        "какая",
        "какие",
        "какую",
        "каким",
        "какими",
        "что",
        "для",
        "или",
        "при",
        "это",
        "после",
        "указан",
        "указана",
        "указано",
        "указаны",
        "является",
        "сколько",
        "кто",
        "где",
        "когда",
        "почему",
        "какойто",
        "всего",
        "также",
        "между",
        "через",
        "который",
        "которая",
        "которые",
        "было",
        "были",
        "есть",
        "быть",
        "может",
        "нужно",
        "надо",
        "пожалуйста",
        "ответ",
        "вопрос",
        "по",
        "от",
        "до",
        "на",
        "из",
        "за",
        "об",
        "со",
        "года",
        "году",
        "годом",
        "г",
    }
)

# Inside an already-scoped file these only inflate title/header chunks.
_IN_FILE_DOC_NOISE = frozenset(
    {
        "договор",
        "договора",
        "договору",
        "договоре",
        "договором",
        "контракт",
        "контракта",
        "контракту",
        "претензия",
        "претензии",
        "претензию",
        "претензией",
        "иск",
        "иска",
        "иску",
        "иском",
        "возражение",
        "возражения",
        "позиция",
        "позиции",
        "документ",
        "документа",
        "документе",
        "файл",
        "файла",
        "сторона",
        "стороны",
        "сторон",
        "общество",
        "общества",
        "ооо",
        "ип",
    }
)

_BM25_K1 = 1.2
_BM25_B = 0.75


def scoped_file_expand_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_SCOPED_FILE_EXPAND_ENABLED", True))


def scoped_file_expand_max_chunks() -> int:
    return max(
        8,
        int(getattr(config, "CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_CHUNKS", 48) or 48),
    )


def scoped_file_expand_pool_limit() -> int:
    return max(
        8,
        int(getattr(config, "CASE_ASSISTANT_SCOPED_FILE_EXPAND_POOL", 32) or 32),
    )


def scoped_file_expand_max_files() -> int:
    return max(1, int(getattr(config, "CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_FILES", 3) or 3))


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _normalize_token(raw: str) -> str:
    t = raw.lower().lstrip("№").replace(" ", "")
    return t


def _tokenize_text(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in _TOKEN_RE.findall(_norm(text)):
        t = _normalize_token(raw)
        if len(t) < 2 or t in seen:
            continue
        if t.isdigit() and len(t) < 3:
            continue
        seen.add(t)
        out.append(t)
    return out


def _question_tokens(question: str, *, in_file: bool = False) -> List[str]:
    stop = set(_QUESTION_STOP)
    if in_file:
        stop |= _IN_FILE_DOC_NOISE
    tokens: List[str] = []
    seen = set()
    for t in _tokenize_text(question):
        if t in seen or t in stop:
            continue
        # Calendar years only identify the document once the file is bound.
        if in_file and re.fullmatch(r"(?:19|20)\d{2}", t):
            continue
        seen.add(t)
        tokens.append(t)
    return tokens


def _stem6(tok: str) -> str:
    return tok[:6] if len(tok) >= 6 else tok


def _token_in_bag(tok: str, bag: set[str], compact: str) -> bool:
    if tok in bag or tok in compact:
        return True
    if len(tok) >= 6:
        stem = _stem6(tok)
        if stem in compact:
            return True
        for b in bag:
            if len(b) >= 6 and _stem6(b) == stem:
                return True
    return False


def _bm25_idf(n_docs: int, df: int) -> float:
    # Robertson–Walker IDF used by Okapi BM25.
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def score_chunk_for_question(
    question: str,
    page_content: str,
    *,
    suppress_doc_refs: Optional[Sequence[str]] = None,
    idf: Optional[Dict[str, float]] = None,
    avgdl: float = 0.0,
) -> float:
    """
    Lexical relevance of a chunk to the question.

    When ``idf`` is provided (file-level DF), uses BM25-lite. Otherwise falls
    back to additive token hits (unit tests / single-chunk probes).

    ``suppress_doc_refs``: document numbers already used to bind the file —
    matching them again only inflates headers.
    """
    content = _norm(page_content)
    if not content:
        return 0.0
    compact = content.replace(" ", "")
    suppressed = {normalize_doc_ref(x) for x in (suppress_doc_refs or []) if x}

    content_tokens = _tokenize_text(content)
    bag = set(content_tokens)
    tf = Counter(content_tokens)
    dl = max(1, len(content_tokens))

    score = 0.0
    # Identity boosts (№ / dates) only when the file is not already bound —
    # inside a scoped file they inflate titles over fact clauses.
    apply_identity_boost = not suppressed and idf is None

    if apply_identity_boost:
        for ref in extract_document_refs(question):
            needle = normalize_doc_ref(ref)
            if not needle:
                continue
            if needle in compact or f"№{needle}" in compact or f"№{needle}" in content:
                score += 2.5

        for anchor in extract_question_anchors(question):
            if anchor and (anchor in compact or anchor in content):
                score += 2.0

    tokens = _question_tokens(question, in_file=True)
    if suppressed:
        tokens = [t for t in tokens if normalize_doc_ref(t) not in suppressed]
    if not tokens:
        return score

    if idf is not None and avgdl > 0:
        k1 = _BM25_K1
        b = _BM25_B
        for tok in tokens:
            matched_keys = [tok] if tok in tf else []
            if not matched_keys and len(tok) >= 6:
                stem = _stem6(tok)
                matched_keys = [w for w in tf if len(w) >= 6 and _stem6(w) == stem]
            if not matched_keys and tok in compact:
                # Compact digit/code hit without whitespace tokenization.
                matched_keys = [tok]
                tf[tok] = max(tf.get(tok, 0), 1)
            if not matched_keys:
                continue
            term_tf = sum(tf[k] for k in matched_keys)
            term_idf = 0.0
            for k in matched_keys:
                term_idf = max(term_idf, float(idf.get(k, idf.get(_stem6(k), 0.0))))
            if term_idf <= 0:
                # Rare / unseen in DF map: still reward exact question term.
                term_idf = _bm25_idf(max(2, len(idf) or 2), 1)
            denom = term_tf + k1 * (1.0 - b + b * (dl / avgdl))
            score += term_idf * (term_tf * (k1 + 1.0)) / max(denom, 1e-9)
            if any(ch.isdigit() for ch in tok):
                score += 0.35
        return score

    # Additive fallback (no file inventory).
    hits = 0
    for tok in tokens:
        if _token_in_bag(tok, bag, compact):
            hits += 1
            score += 1.25 if any(ch.isdigit() for ch in tok) else 0.85
    if hits:
        score += min(2.5, hits * 0.2)
    return score


def is_compact_chunk_inventory(chunk_count: int) -> bool:
    return 0 < chunk_count <= scoped_file_expand_max_chunks()


def _doc_identity(doc: Document) -> str:
    md = doc.metadata or {}
    for key in ("chunk_id", "id", "vector_id"):
        value = md.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{value}"
    fid = str(md.get("file_id") or "")
    return f"{fid}:{hash((doc.page_content or '')[:240])}"


def _build_file_idf(chunks: Sequence[Document]) -> Tuple[Dict[str, float], float]:
    n = len(chunks)
    df: Counter[str] = Counter()
    stem_df: Counter[str] = Counter()
    lengths: List[int] = []
    for doc in chunks:
        toks = _tokenize_text(doc.page_content or "")
        lengths.append(max(1, len(toks)))
        uniq = set(toks)
        for t in uniq:
            df[t] += 1
        stems = {_stem6(t) for t in uniq if len(t) >= 6}
        for s in stems:
            stem_df[s] += 1
    idf = {t: _bm25_idf(n, int(c)) for t, c in df.items() if c > 0}
    for stem, c in stem_df.items():
        idf.setdefault(stem, _bm25_idf(n, max(1, int(c))))
    avgdl = (sum(lengths) / len(lengths)) if lengths else 1.0
    return idf, float(avgdl)


def _windows_from_text(
    text: str,
    *,
    window: int = 900,
    stride: int = 450,
) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= window:
        return [t]
    out: List[str] = []
    i = 0
    while i < len(t):
        out.append(t[i : i + window])
        if i + window >= len(t):
            break
        i += stride
    tail = t[-window:]
    if out[-1] != tail:
        out.append(tail)
    return out


def _content_fingerprint(text: str) -> str:
    return _norm(text)[:180]


def _inventory_from_chunks_and_text(
    *,
    chunks: Sequence[Document],
    file_id: str,
    original_text: str = "",
) -> Tuple[List[Document], List[Document]]:
    """
    Build BM25 inventory: indexed chunks + original_text windows.

    Returns (inventory, edge_docs) where edge_docs are head/tail windows used as
    structural priors (parties / sign-off blocks in legal PDFs).
    """
    inventory: List[Document] = []
    seen_fp: set[str] = set()

    def _add(content: str, *, source: str, extra: Optional[Dict[str, Any]] = None) -> Optional[Document]:
        body = (content or "").strip()
        if len(body) < 40:
            return None
        fp = _content_fingerprint(body)
        if fp in seen_fp:
            return None
        seen_fp.add(fp)
        md: Dict[str, Any] = {"file_id": file_id, "within_file_source": source}
        if extra:
            md.update(extra)
        doc = Document(page_content=body, metadata=md)
        inventory.append(doc)
        return doc

    for doc in chunks:
        if not isinstance(doc, Document):
            continue
        md = dict(doc.metadata or {})
        md.setdefault("file_id", file_id)
        md.setdefault("within_file_source", "vector")
        body = doc.page_content or ""
        fp = _content_fingerprint(body)
        if fp in seen_fp or len(body.strip()) < 20:
            continue
        seen_fp.add(fp)
        inventory.append(Document(page_content=body, metadata=md))

    edge_docs: List[Document] = []
    text = (original_text or "").strip()
    if text:
        windows = _windows_from_text(text)
        for i, w in enumerate(windows):
            added = _add(w, source="original_window", extra={"window_index": i})
            if added is None:
                continue
        # Structural priors: opening (parties) and closing (signature / apps).
        head = text[:1000]
        tail = text[-1000:] if len(text) > 1000 else text
        for label, block in (("head", head), ("tail", tail)):
            doc = _add(block, source=f"original_{label}", extra={"edge": label})
            if doc is not None:
                edge_docs.append(doc)
            else:
                # Already in inventory via window — recover reference.
                fp = _content_fingerprint(block)
                for inv in inventory:
                    if _content_fingerprint(inv.page_content or "") == fp:
                        edge_docs.append(inv)
                        break

    return inventory, edge_docs


def _rank_chunks_in_file(
    *,
    question: str,
    chunks: Sequence[Document],
    file_id: str,
    suppress_doc_refs: Sequence[str],
    per_file_cap: int,
    original_text: str = "",
) -> List[Tuple[float, Document]]:
    inventory, edge_docs = _inventory_from_chunks_and_text(
        chunks=chunks,
        file_id=file_id,
        original_text=original_text,
    )
    if not inventory:
        return []

    idf, avgdl = _build_file_idf(inventory)
    scored: List[Tuple[float, Document]] = []
    for doc in inventory:
        sc = score_chunk_for_question(
            question,
            doc.page_content or "",
            suppress_doc_refs=suppress_doc_refs,
            idf=idf,
            avgdl=avgdl,
        )
        if sc <= 0:
            continue
        md = dict(doc.metadata or {})
        md["within_file_lexical_score"] = float(sc)
        md["combined_score"] = float(sc)
        md.setdefault("file_id", file_id)
        scored.append((sc, Document(page_content=doc.page_content, metadata=md)))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Always keep file edges under compact scope (sign-off / parties often
    # missing from shattered micro-chunks).
    if edge_docs:
        scored_by_id = {_doc_identity(d): (sc, d) for sc, d in scored}
        # Survive FAST final_k≈6: edge score ≥ 5th-best BM25 hit.
        anchor_ix = min(4, max(0, len(scored) - 1))
        floor = max(0.05, scored[anchor_ix][0] if scored else 0.05)
        edge_keys = {_doc_identity(e) for e in edge_docs}

        for edge in edge_docs:
            key = _doc_identity(edge)
            if key in scored_by_id:
                sc, existing = scored_by_id[key]
                md = dict(existing.metadata or {})
                md["within_file_edge_prior"] = True
                # Lift to at least the FAST-survival floor.
                sc = max(float(sc), floor)
                md["within_file_lexical_score"] = sc
                md["combined_score"] = sc
                scored_by_id[key] = (
                    sc,
                    Document(page_content=existing.page_content, metadata=md),
                )
                continue
            edge_sc = score_chunk_for_question(
                question,
                edge.page_content or "",
                suppress_doc_refs=suppress_doc_refs,
                idf=idf,
                avgdl=avgdl,
            )
            sc = max(float(edge_sc), floor) if edge_sc > 0 else floor
            md = dict(edge.metadata or {})
            md["within_file_lexical_score"] = sc
            md["combined_score"] = sc
            md["within_file_edge_prior"] = True
            md.setdefault("file_id", file_id)
            scored_by_id[key] = (
                sc,
                Document(page_content=edge.page_content, metadata=md),
            )

        scored = sorted(scored_by_id.values(), key=lambda x: x[0], reverse=True)

        # Hard-reserve edge slots inside the per-file cap.
        reserved = [pair for pair in scored if _doc_identity(pair[1]) in edge_keys]
        rest = [pair for pair in scored if _doc_identity(pair[1]) not in edge_keys]
        reserve_n = min(len(reserved), max(1, min(2, per_file_cap // 3)))
        # Keep 1–2 strongest BM25 hits first, then edges, then the rest —
        # so edges land inside FAST final_k without starving fact clauses.
        lead_n = min(2, max(0, per_file_cap - reserve_n))
        core_n = max(0, per_file_cap - lead_n - reserve_n)
        merged_scored = rest[:lead_n] + reserved[:reserve_n] + rest[lead_n : lead_n + core_n]
        return merged_scored[:per_file_cap]

    return scored[:per_file_cap]


def expand_docs_within_scoped_files(
    *,
    case_id: str,
    file_ids: Sequence[str],
    question: str,
    hybrid_docs: Sequence[Document],
    vector_store: Any,
    force: bool = False,
    file_texts: Optional[Dict[str, str]] = None,
) -> Tuple[List[Document], Dict[str, Any]]:
    """
    Merge hybrid hits with BM25-ranked in-file passages for compact scopes.

    Inventory = vector chunks ∪ original_text windows (when provided). Lexical
    channel is primary under narrow scope; hybrid fills gaps.
    """
    meta: Dict[str, Any] = {"within_file_expand": False}
    if not force and not scoped_file_expand_enabled():
        meta["skipped"] = "disabled"
        return list(hybrid_docs), meta

    fids = [str(x).strip() for x in file_ids if str(x).strip()]
    if not fids or not case_id or vector_store is None:
        meta["skipped"] = "no_scope_or_store"
        return list(hybrid_docs), meta

    if not hasattr(vector_store, "list_chunks_by_file"):
        meta["skipped"] = "store_unsupported"
        return list(hybrid_docs), meta

    texts = {str(k): (v or "") for k, v in (file_texts or {}).items() if str(k).strip()}
    pool_limit = scoped_file_expand_pool_limit()
    max_chunks = scoped_file_expand_max_chunks()
    max_files = scoped_file_expand_max_files()
    hard_ceiling = max(max_chunks * 8, 400)
    lexical_hits: List[List[Tuple[float, Document]]] = []
    files_expanded = 0
    files_skipped_large = 0
    files_with_original = 0
    suppressed_refs = extract_document_refs(question)
    per_file_cap = max(6, pool_limit // max(1, min(max_files, len(fids))))

    for fid in fids[:max_files]:
        try:
            chunks = vector_store.list_chunks_by_file(str(case_id), fid) or []
        except Exception as exc:
            logger.debug("within_file_expand list_chunks failed file=%s: %s", fid, exc)
            continue
        original = texts.get(fid, "")
        # Allow expand from original_text alone when vector inventory is empty.
        if not chunks and not original:
            continue
        inventory_size = len(chunks) + (len(_windows_from_text(original)) if original else 0)
        if not force and inventory_size > scoped_file_expand_max_chunks() * 3:
            # Very large files: still allow pure chunk path if compact chunks.
            if not is_compact_chunk_inventory(len(chunks)):
                files_skipped_large += 1
                continue
            original = ""
        if len(chunks) > hard_ceiling and not original:
            files_skipped_large += 1
            continue
        files_expanded += 1
        if original:
            files_with_original += 1
        lexical_hits.append(
            _rank_chunks_in_file(
                question=question,
                chunks=chunks,
                file_id=fid,
                suppress_doc_refs=suppressed_refs,
                per_file_cap=per_file_cap,
                original_text=original,
            )
        )

    if not lexical_hits:
        meta.update(
            {
                "within_file_expand": False,
                "files_expanded": files_expanded,
                "files_skipped_large": files_skipped_large,
                "lexical_hits": 0,
            }
        )
        return list(hybrid_docs), meta

    # Preserve per-file order (BM25 lead + edge priors). Multi-file: round-robin.
    ordered: List[Tuple[float, Document]] = []
    if len(lexical_hits) == 1:
        ordered = list(lexical_hits[0])
    else:
        cursors = [0] * len(lexical_hits)
        while len(ordered) < pool_limit and any(
            cursors[i] < len(lexical_hits[i]) for i in range(len(lexical_hits))
        ):
            for i, hits in enumerate(lexical_hits):
                if cursors[i] < len(hits):
                    ordered.append(hits[cursors[i]])
                    cursors[i] += 1
                if len(ordered) >= pool_limit:
                    break

    picked: List[Document] = []
    seen = set()
    for sc, doc in ordered:
        key = _doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        picked.append(doc)
        if len(picked) >= pool_limit:
            break

    # Lexical is primary under narrow scope; hybrid only fills missing chunks.
    # Avoid mixing incomparable hybrid similarity with BM25 scores.
    hybrid_fill = [d for d in hybrid_docs if _doc_identity(d) not in seen]
    for d in hybrid_fill:
        seen.add(_doc_identity(d))
    merged = list(picked) + hybrid_fill
    if len(fids) > 1:
        # Fairness across multi-file scopes (e.g. contract + pleading).
        merged = _round_robin_by_file(merged, limit=max(pool_limit, len(picked)))
    else:
        merged = merged[: max(pool_limit, len(hybrid_docs) + 8)]

    meta.update(
        {
            "within_file_expand": True,
            "files_expanded": files_expanded,
            "files_skipped_large": files_skipped_large,
            "lexical_hits": len(picked),
            "merged_docs": len(merged),
            "suppressed_doc_refs": list(suppressed_refs),
            "channel": "bm25_in_file",
            "files_with_original": files_with_original,
        }
    )
    logger.info(
        "[WithinFileExpand] case=%s files=%s expanded=%s lexical=%s merged=%s original=%s channel=bm25",
        case_id,
        len(fids),
        files_expanded,
        len(picked),
        len(merged),
        files_with_original,
    )
    return merged, meta


def _round_robin_by_file(docs: Sequence[Document], *, limit: int) -> List[Document]:
    buckets: Dict[str, List[Document]] = {}
    order: List[str] = []
    for doc in docs:
        md = doc.metadata or {}
        fid = str(md.get("file_id") or md.get("doc_id") or "").strip() or "_unknown"
        if fid not in buckets:
            buckets[fid] = []
            order.append(fid)
        buckets[fid].append(doc)
    out: List[Document] = []
    while len(out) < limit and any(buckets[f] for f in order):
        for fid in order:
            if buckets[fid]:
                out.append(buckets[fid].pop(0))
            if len(out) >= limit:
                break
    return out
