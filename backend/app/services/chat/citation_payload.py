"""
Единый builder payload цитат для SSE / LangGraph state.

Инварианты см. backend/docs/CITATION_CONTRACT_V1.md
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Iterable

from langchain_core.documents import Document
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services.chat.citation_file_identity import (
    CaseCitationFileIndex,
    is_synthetic_doc_label,
    parse_passport_filename,
    resolve_citation_file_identity,
)
from app.services.chat.retrieval_dc_labels import compute_retrieval_dc_labels
from app.services.prov_span_utils import narrow_char_span_to_quote
from app.services.rag_service import RAGService
from app.services.transaction_source import highlight_targets_from_row_metadata

logger = logging.getLogger(__name__)

# Zero-width pair + маркеры — см. frontend MessageContent.tsx (injectCitations).
_CITE_ZW = "\u200b\u200b"
_DC_BRACKET_RE = re.compile(r"\[\s*D(\d+)\s*:\s*C(\d+)\s*\]", re.IGNORECASE)

_BRACKET_NUM_RE = re.compile(r"\[(\d+)\]")
_SOURCE_STYLE_RE = re.compile(r"\[Источник\s+(\d+)(?:[^\]]*)\]", flags=re.IGNORECASE)

def _make_citation_id(
    *,
    source_id: str,
    chunk_id: Optional[str],
    char_start: Optional[int],
    char_end: Optional[int],
    page: Optional[int],
) -> str:
    """
    Стабильный идентификатор цитаты для UI.

    Идея: UI должен ссылаться на citation_id, а не на позицию в citations[].
    """
    if chunk_id:
        digest = hashlib.sha1(f"{source_id}|chunk|{chunk_id}".encode("utf-8")).hexdigest()[:12]
        return f"cit_{digest}"
    digest = hashlib.sha1(f"{source_id}|{page}|{char_start}|{char_end}".encode("utf-8")).hexdigest()[:12]
    return f"cit_{digest}"


def fetch_original_text_map_for_case(
    db: Session,
    case_id: str,
    *,
    file_ids: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """file_id -> original_text (как в БД после ingestion joiner \\n\\n).

    IMPORTANT: When `file_ids` is provided, only those files are fetched.
    This avoids loading large `original_text` blobs for the entire case and reduces
    the chance of remote Postgres closing the connection on big responses.
    """
    from app.models.case import File

    if not db or not case_id:
        return {}

    wanted_ids = [str(x) for x in (file_ids or []) if x]

    def _query(session: Session):
        q = session.query(File.id, File.original_text).filter(File.case_id == case_id)
        if wanted_ids:
            q = q.filter(File.id.in_(wanted_ids))
        return q.all()

    try:
        rows = _query(db)
        return {str(rid): (txt or "") for rid, txt in rows}
    except OperationalError as e:
        # Remote Postgres (Neon/serverless) can drop connections mid-request.
        # Retrying with a fresh session is cheap and avoids failing the whole retrieval.
        logger.warning("[citations] original_text query OperationalError, retrying once: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            from app.utils.database import SessionLocal

            fresh = SessionLocal()
            try:
                rows = _query(fresh)
                return {str(rid): (txt or "") for rid, txt in rows}
            finally:
                fresh.close()
        except Exception:
            logger.error("[citations] original_text retry failed", exc_info=True)
            return {}


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_page(meta: Dict[str, Any]) -> Optional[int]:
    """
    STRICT: return 1-based page number ONLY from Docling provenance (dl_meta).

    Used as the first-tier source in resolve_citation_page_from_metadata().
    """

    # Docling LangChain: dl_meta.doc_items[].prov[].page_no is the ONLY reliable page.
    # Important: docling chunks != pages, so NEVER derive "page" from chunk index.
    dl_meta = meta.get("dl_meta")
    if isinstance(dl_meta, dict):
        doc_items = dl_meta.get("doc_items")
        if isinstance(doc_items, list) and doc_items:
            # Heuristic:
            # - pick the minimum page_no across ALL provenance entries (doc_items may represent
            #   multiple fragments; relying on doc_items[0] can yield invalid/late page numbers);
            # - if any page_no==0 appears, treat as 0-based and +1.
            min_pno: Optional[int] = None
            for doc_item in doc_items:
                if not isinstance(doc_item, dict):
                    continue
                prov_list = doc_item.get("prov")
                if not isinstance(prov_list, list) or not prov_list:
                    continue
                for prov in prov_list:
                    if not isinstance(prov, dict):
                        continue
                    pno_i = _as_int(prov.get("page_no"))
                    if pno_i is None:
                        continue
                    if min_pno is None or pno_i < min_pno:
                        min_pno = pno_i

            if min_pno is None:
                return None
            if min_pno == 0:
                return 1
            if min_pno >= 1:
                return min_pno

    return None


def resolve_citation_page_from_metadata(meta: Optional[Dict[str, Any]]) -> Optional[int]:
    """
    Unified 1-based page for citations / PDF navigation.

    1. Docling dl_meta provenance (_as_page) — highest fidelity.
    2. LegalChunkerV2: page_start / page_end (from Docling segment prov when present).
       These are deliberately NOT chunk indices (see _as_page docstring history).
    3. Legacy source_page / loader hints (often 1-based for PDF pages).
    """
    if not isinstance(meta, dict):
        return None
    p_dl = _as_page(meta)
    if p_dl is not None:
        return p_dl

    for key in ("page_start", "page_end"):
        v = _as_int(meta.get(key))
        if v is None:
            continue
        if v == 0:
            return 1
        if v >= 1:
            return v
        return v + 1

    src = _as_int(meta.get("source_page"))
    if src is not None:
        if src == 0:
            return 1
        if src >= 1:
            return src
        return src + 1

    return None


def _citation_bbox_char_span(
    *,
    original: Optional[str],
    char_start: Optional[int],
    char_end: Optional[int],
    quote_anchor: Optional[str],
    quote: Optional[str],
) -> Tuple[Optional[int], Optional[int]]:
    """Document char span used to filter prov/bbox for a single citation highlight."""
    if char_start is None or char_end is None or char_end <= char_start:
        return None, None
    hs, he = int(char_start), int(char_end)
    if original:
        anchor = (quote_anchor or quote or "").strip()
        if anchor:
            hs, he = narrow_char_span_to_quote(
                original=original,
                span_start=hs,
                span_end=he,
                quote_anchor=anchor,
            )
    return hs, he


def _is_dev_env() -> bool:
    """
    Best-effort "dev mode" detection for adding debug-only fields to SSE.
    We avoid relying on app config imports here to keep this module lightweight.
    """
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    if env == "production":
        return False
    # Heuristic used elsewhere: PORT is typically set in deployed environments.
    if os.getenv("PORT"):
        return False
    return True


def _docling_prov_page_nos(meta: Dict[str, Any]) -> List[int]:
    """Collect all integer Docling prov.page_no values (raw, as-is)."""
    out: List[int] = []
    dl_meta = meta.get("dl_meta")
    if not isinstance(dl_meta, dict):
        return out
    doc_items = dl_meta.get("doc_items")
    if not isinstance(doc_items, list) or not doc_items:
        return out
    for doc_item in doc_items:
        if not isinstance(doc_item, dict):
            continue
        prov_list = doc_item.get("prov")
        if not isinstance(prov_list, list) or not prov_list:
            continue
        for prov in prov_list:
            if not isinstance(prov, dict):
                continue
            pno_i = _as_int(prov.get("page_no"))
            if pno_i is None:
                continue
            out.append(pno_i)
    return out


def _align_offsets_to_original(
    *,
    original: str,
    chunk_text: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Tuple[Optional[int], Optional[int], Optional[str], Dict[str, Any]]:
    """
    Best-effort alignment for cases where stored `original_text` and indexing offsets diverged.

    Root cause seen in legacy ingestion: offsets computed on `chunk_text.strip()` while DB
    stored join of raw loader chunks without strip. This helper attempts to relocate the chunk
    within `original` near the expected start coordinate and returns corrected offsets.
    """
    meta: Dict[str, Any] = {"aligned": False, "method": None}
    if not original:
        return char_start, char_end, None, meta

    needle = (chunk_text or "").strip()
    # Allow short anchors too; UI falls back to coords if quote is too short anyway,
    # but alignment helps keep offsets correct.
    if len(needle) < 4:
        return char_start, char_end, None, meta

    olen = len(original)

    # If current slice already looks consistent, keep.
    if (
        char_start is not None
        and char_end is not None
        and 0 <= char_start <= char_end <= olen
        and needle[: min(len(needle), 40)].lower()
        in original[char_start:char_end].lower()
    ):
        return char_start, char_end, original[char_start:char_end], meta

    # Strategy 1: local window around expected start.
    if char_start is not None and 0 <= char_start <= olen:
        radius = 8000
        local_start = max(0, char_start - radius)
        local_end = min(olen, char_start + radius)
        local = original[local_start:local_end]
        idx = local.find(needle)
        if idx != -1:
            s = local_start + idx
            e = s + len(needle)
            meta.update({"aligned": True, "method": "local_find"})
            return s, e, original[s:e], meta

    # Strategy 2: global find (first occurrence).
    idx2 = original.find(needle)
    if idx2 != -1:
        s = idx2
        e = s + len(needle)
        meta.update({"aligned": True, "method": "global_find"})
        return s, e, original[s:e], meta

    return char_start, char_end, None, meta


def fetch_originals_for_citation_docs(
    db: Session,
    case_id: str,
    docs: List[Document],
) -> Dict[str, str]:
    """Load original_text only for files resolved from retrieval docs (not doc_N placeholders)."""
    from app.services.chat.citation_file_identity import (
        CaseCitationFileIndex,
        collect_resolved_file_ids_for_originals,
    )
    from app.services.chat.retrieval_dc_labels import compute_retrieval_dc_labels

    if not db or not case_id or not docs:
        return {}
    try:
        index = CaseCitationFileIndex.from_db(db, str(case_id))
    except Exception as exc:
        logger.warning("[citations] originals index failed case=%s: %s", case_id, exc)
        return fetch_original_text_map_for_case(db, case_id)
    dc = compute_retrieval_dc_labels(docs)
    file_ids = collect_resolved_file_ids_for_originals(docs, dc, index=index)
    if file_ids:
        return fetch_original_text_map_for_case(db, case_id, file_ids=file_ids)
    return fetch_original_text_map_for_case(db, case_id)


def build_retrieval_citations(
    docs: List[Document],
    *,
    original_text_by_file_id: Optional[Dict[str, str]] = None,
    quote_max_len: int = 260,
    anchor_max_len: int = 800,
    source_type: str = "document",
    case_id: Optional[str] = None,
    db: Optional[Session] = None,
    case_file_index: Optional[CaseCitationFileIndex] = None,
) -> List[Dict[str, Any]]:
    """
    Строит список dict, совместимых с Citation (events.py) и SSESerializer.

    quote_anchor: подстрока для DOM-поиска; при наличии original_text и валидных
    char_start/char_end — срез из original_text, иначе из page_content.

    source_id всегда стремится быть File.id дела (UUID), никогда doc_1 / D-метки.
    """
    out: List[Dict[str, Any]] = []
    originals = dict(original_text_by_file_id or {})
    dc_labels = compute_retrieval_dc_labels(docs)

    index: Optional[CaseCitationFileIndex] = case_file_index
    if index is None and source_type == "document" and db and case_id:
        try:
            index = CaseCitationFileIndex.from_db(db, str(case_id))
        except Exception as exc:
            logger.warning(
                "[citations] case file index load failed case=%s: %s",
                case_id,
                exc,
            )
            index = None

    d_to_file_id: Dict[int, str] = {}
    if index and source_type == "document":
        for doc, (retrieval_d, _retrieval_c) in zip(docs, dc_labels):
            meta = dict(doc.metadata or {})
            pc = str(doc.page_content or "")
            fid, _ = resolve_citation_file_identity(
                meta,
                pc,
                retrieval_d=retrieval_d,
                index=index,
                d_to_file_id=d_to_file_id,
            )
            if fid and retrieval_d not in d_to_file_id:
                d_to_file_id[retrieval_d] = fid

    for doc, (retrieval_d, retrieval_c) in zip(docs, dc_labels):
        meta = dict(doc.metadata or {})
        pc = str(doc.page_content or "")

        if source_type == "document" and index is not None:
            source_id, file_name = resolve_citation_file_identity(
                meta,
                pc,
                retrieval_d=retrieval_d,
                index=index,
                d_to_file_id=d_to_file_id,
            )
            if not source_id:
                logger.warning(
                    "[citations] unresolved file identity d=%s meta_keys=%s has_passport_line=%s",
                    retrieval_d,
                    list(meta.keys())[:8],
                    bool(parse_passport_filename(pc)),
                )
                source_id_str = ""
            else:
                source_id_str = source_id
        elif source_type == "document":
            raw = str(meta.get("file_id") or meta.get("doc_id") or "").strip()
            source_id_str = "" if is_synthetic_doc_label(raw) else (raw or "")
            file_name = str(meta.get("source_file") or meta.get("filename") or "Документ")
            if is_synthetic_doc_label(file_name):
                file_name = parse_passport_filename(pc) or "Документ"
        else:
            source_id_str = str(
                meta.get("file_id") or meta.get("doc_id") or meta.get("source_id") or ""
            )
            file_name = str(meta.get("source_file") or meta.get("filename") or "Документ")

        page = resolve_citation_page_from_metadata(meta)

        char_start = _as_int(meta.get("char_start"))
        if char_start is None:
            char_start = _as_int(meta.get("chunk_start_char"))
        char_end = _as_int(meta.get("char_end"))
        if char_end is None:
            char_end = _as_int(meta.get("chunk_end_char"))

        chunk_id = meta.get("chunk_id")
        if chunk_id is not None:
            chunk_id = str(chunk_id)

        quote = (pc[:quote_max_len] + ("..." if len(pc) > quote_max_len else "")) if pc else ""

        # Structured table / Excel rows: DOM search must use bare cell values, not "Col: value".
        highlight_targets = highlight_targets_from_row_metadata(meta, page_content=pc)

        original = originals.get(source_id_str) if (originals and source_id_str) else None
        if original is not None:
            char_start, char_end, aligned_anchor, align_meta = _align_offsets_to_original(
                original=original,
                chunk_text=pc,
                char_start=char_start,
                char_end=char_end,
            )
            if align_meta.get("aligned"):
                logger.debug(
                    "[citations] aligned offsets file=%s chunk=%s method=%s",
                    source_id_str,
                    chunk_id or "-",
                    align_meta.get("method"),
                )
            if highlight_targets:
                quote_anchor = highlight_targets[0][:anchor_max_len]
            elif aligned_anchor:
                quote_anchor = aligned_anchor[:anchor_max_len]
            elif (
                char_start is not None
                and char_end is not None
                and 0 <= char_start <= char_end <= len(original)
            ):
                quote_anchor = original[char_start:char_end][:anchor_max_len]
            else:
                quote_anchor = pc[:anchor_max_len]
        else:
            if highlight_targets:
                quote_anchor = highlight_targets[0][:anchor_max_len]
            else:
                quote_anchor = pc[:anchor_max_len]
            if char_start is not None and char_end is not None and original is not None:
                if not (0 <= char_start <= char_end <= len(original)):
                    logger.debug(
                        "[citations] invalid offsets file=%s start=%s end=%s olen=%s",
                        source_id_str,
                        char_start,
                        char_end,
                        len(original),
                    )

        bbox_hs, bbox_he = _citation_bbox_char_span(
            original=original,
            char_start=char_start,
            char_end=char_end,
            quote_anchor=quote_anchor,
            quote=quote,
        )
        bbox_regions, page_bbox = RAGService._extract_bbox_regions(
            meta,
            char_start=bbox_hs,
            char_end=bbox_he,
        )
        bbox = bbox_regions[0] if bbox_regions else None

        # Полный текст чанка для UI (поиск в PDF как на /chunk-lab); лимит на размер SSE.
        text_preview_full = (pc[:20000] + ("…" if len(pc) > 20000 else "")) if pc else None

        payload: Dict[str, Any] = {
            "citation_id": _make_citation_id(
                source_id=source_id_str or file_name,
                chunk_id=chunk_id,
                char_start=char_start,
                char_end=char_end,
                page=page,
            ),
            "source_id": source_id_str,
            "file_name": file_name,
            "page": page,
            "quote": quote if quote else None,
            "quote_anchor": quote_anchor if quote_anchor else None,
            "text_preview": text_preview_full,
            "char_start": char_start,
            "char_end": char_end,
            "source_type": source_type,
            "bbox": bbox,
            "page_bbox": page_bbox,
        }
        if highlight_targets:
            payload["highlight_targets"] = highlight_targets
        if _is_dev_env():
            # Debug-only: show exactly what Docling provenance reported for this chunk.
            payload["debug_docling_prov_page_nos"] = _docling_prov_page_nos(meta)
        if bbox_regions:
            payload["bbox_regions"] = bbox_regions
        if chunk_id:
            payload["chunk_id"] = chunk_id
        payload["retrieval_d"] = int(retrieval_d)
        payload["retrieval_c"] = int(retrieval_c)
        out.append(payload)
    return out


def expand_dc_markers_to_cite_zw(
    text: str,
    citations: List[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """
    Заменяет [D{d}:C{c}] (регистронезависимо) на ZW+CITE_{citation_id}_{n}_ENDCITE+ZW.

    d/c должны совпадать с полями retrieval_d / retrieval_c в citations[] (тот же порядок, что в промпте).
    Неизвестные пары удаляются (пустая строка).
    """
    if not text or not citations:
        return text or "", {"expanded": 0, "removed_invalid_dc": 0}

    dc_to_indices: Dict[Tuple[int, int], List[int]] = {}
    for idx, c in enumerate(citations):
        d_raw = c.get("retrieval_d")
        r_raw = c.get("retrieval_c")
        if d_raw is None or r_raw is None:
            continue
        try:
            key = (int(d_raw), int(r_raw))
        except (TypeError, ValueError):
            continue
        dc_to_indices.setdefault(key, []).append(idx)

    expanded = 0
    removed_invalid_dc = 0

    def _repl(m: re.Match) -> str:
        nonlocal expanded, removed_invalid_dc
        try:
            d, c = int(m.group(1)), int(m.group(2))
        except ValueError:
            removed_invalid_dc += 1
            return ""
        positions = dc_to_indices.get((d, c))
        if not positions:
            removed_invalid_dc += 1
            return ""
        expanded += 1
        pos = positions[0]
        cit = citations[pos]
        cid = cit.get("citation_id")
        if not cid:
            removed_invalid_dc += 1
            expanded -= 1
            return ""
        display_n = pos + 1
        return f"{_CITE_ZW}CITE_{cid}_{display_n}_ENDCITE{_CITE_ZW}"

    new_text = _DC_BRACKET_RE.sub(_repl, text)
    meta = {"expanded": expanded, "removed_invalid_dc": removed_invalid_dc}
    if removed_invalid_dc:
        logger.warning("[citations] expand_dc_markers %s", meta)
    return new_text, meta


def enrich_structured_citations(
    citation_dicts: List[Dict[str, Any]],
    docs: List[Document],
    originals: Dict[str, str],
    *,
    anchor_max_len: int = 800,
    case_id: Optional[str] = None,
    db: Optional[Session] = None,
    case_file_index: Optional[CaseCitationFileIndex] = None,
) -> List[Dict[str, Any]]:
    """
    Приводит citations из generate_with_structured_citations к SSE-полям:
    source_id = file_id из чанка, quote_anchor из original_text по offsets.
    """
    chunk_to_doc: Dict[str, Document] = {}
    for d in docs:
        cid = (d.metadata or {}).get("chunk_id")
        if cid is not None:
            chunk_to_doc[str(cid)] = d

    index: Optional[CaseCitationFileIndex] = case_file_index
    if index is None and db and case_id:
        try:
            index = CaseCitationFileIndex.from_db(db, str(case_id))
        except Exception as exc:
            logger.warning("[citations] enrich index load failed case=%s: %s", case_id, exc)

    out: List[Dict[str, Any]] = []
    for raw in citation_dicts:
        ec = dict(raw)
        chunk_id = ec.get("chunk_id")
        doc = chunk_to_doc.get(str(chunk_id)) if chunk_id is not None else None
        meta = dict(doc.metadata or {}) if doc else {}
        pc = str(getattr(doc, "page_content", "") or "") if doc else ""
        if index is not None:
            source_id, file_name = resolve_citation_file_identity(meta, pc, index=index)
            source_id = source_id or ""
        else:
            raw_sid = str(meta.get("file_id") or ec.get("source_id") or "").strip()
            source_id = "" if is_synthetic_doc_label(raw_sid) else raw_sid
            file_name = str(
                ec.get("file_name") or meta.get("source_file") or meta.get("source_filename") or "Документ"
            )
            if is_synthetic_doc_label(file_name):
                file_name = parse_passport_filename(pc) or "Документ"
        # Page from metadata only (dl_meta, LegalChunker page_*, loader source_page — not model guesses).
        page = resolve_citation_page_from_metadata(meta)

        char_start = _as_int(ec.get("char_start"))
        char_end = _as_int(ec.get("char_end"))
        original = originals.get(source_id) if (originals and source_id) else None
        quote_anchor: Optional[str] = None
        highlight_targets = highlight_targets_from_row_metadata(meta, page_content=pc)
        if original is not None:
            char_start, char_end, aligned_anchor, _ = _align_offsets_to_original(
                original=original,
                chunk_text=str(getattr(doc, "page_content", "") or ""),
                char_start=char_start,
                char_end=char_end,
            )
            if highlight_targets:
                quote_anchor = highlight_targets[0][:anchor_max_len]
            elif aligned_anchor:
                quote_anchor = aligned_anchor[:anchor_max_len]
            elif (
                char_start is not None
                and char_end is not None
                and 0 <= char_start <= char_end <= len(original)
            ):
                quote_anchor = original[char_start:char_end][:anchor_max_len]
            else:
                quote_anchor = (ec.get("quote") or "")[:anchor_max_len] or None
        else:
            if highlight_targets:
                quote_anchor = highlight_targets[0][:anchor_max_len]
            else:
                quote_anchor = (ec.get("quote") or "")[:anchor_max_len] or None

        bbox_hs, bbox_he = _citation_bbox_char_span(
            original=original,
            char_start=char_start,
            char_end=char_end,
            quote_anchor=quote_anchor,
            quote=str(ec.get("quote") or "") or None,
        )
        bbox_regions, page_bbox = RAGService._extract_bbox_regions(
            meta,
            char_start=bbox_hs,
            char_end=bbox_he,
        )
        bbox = bbox_regions[0] if bbox_regions else None

        pc_struct = str(getattr(doc, "page_content", "") or "") if doc else ""
        text_preview_struct = (
            (pc_struct[:20000] + ("…" if len(pc_struct) > 20000 else "")) if pc_struct else None
        )

        row: Dict[str, Any] = {
            "citation_id": _make_citation_id(
                source_id=source_id,
                chunk_id=str(chunk_id) if chunk_id else None,
                char_start=char_start,
                char_end=char_end,
                page=page,
            ),
            "source_id": source_id,
            "file_name": file_name,
            "page": page,
            "quote": ec.get("quote"),
            "quote_anchor": quote_anchor,
            "text_preview": text_preview_struct,
            "char_start": char_start,
            "char_end": char_end,
            "context_before": ec.get("context_before"),
            "context_after": ec.get("context_after"),
            "source_type": meta.get("source_type", "document"),
            "bbox": bbox,
            "page_bbox": page_bbox,
        }
        if highlight_targets:
            row["highlight_targets"] = highlight_targets
        if _is_dev_env():
            # Debug-only: show exactly what Docling provenance reported for this chunk.
            row["debug_docling_prov_page_nos"] = _docling_prov_page_nos(meta)
        if bbox_regions:
            row["bbox_regions"] = bbox_regions
        if chunk_id:
            row["chunk_id"] = str(chunk_id)
        out.append(row)
    return out


def repair_citation_brackets(
    text: str,
    n_citations: int,
) -> Tuple[str, Dict[str, Any]]:
    """
    Нормализует и чинит ссылочные маркеры.

    1) Приводит модельный формат вида "[Источник N, ...]" к кликабельному "[N]".
    Удаляет маркеры [N], где N вне 1..n_citations (или при n_citations==0 — все [N]).
    Возвращает (исправленный_текст, метаданные для логов/observability).
    """
    if text is None:
        return "", {"removed_invalid": 0, "removed_all_due_to_zero": 0}

    normalized_source_style = 0

    def _src_repl(m: re.Match) -> str:
        nonlocal normalized_source_style
        normalized_source_style += 1
        return f"[{m.group(1)}]"

    text = _SOURCE_STYLE_RE.sub(_src_repl, text)

    removed_invalid = 0
    removed_zero = 0

    def _repl(m: re.Match) -> str:
        nonlocal removed_invalid, removed_zero
        n = int(m.group(1))
        if n_citations <= 0:
            removed_zero += 1
            return ""
        if 1 <= n <= n_citations:
            return m.group(0)
        removed_invalid += 1
        return ""

    new_text = _BRACKET_NUM_RE.sub(_repl, text)
    meta = {
        "normalized_source_style": normalized_source_style,
        "removed_invalid": removed_invalid,
        "removed_all_due_to_zero": removed_zero,
        "n_citations": n_citations,
    }
    if removed_invalid or removed_zero:
        logger.warning("[citations] bracket_repair %s", meta)
    return new_text, meta
