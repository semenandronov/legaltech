"""File passport lines for RAG chunk prompts (document identity next to excerpt)."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from langchain_core.documents import Document

from app.services.chat.document_ref_scope import CONTRACT_NO_RE as _CONTRACT_NO_RE
_DATE_RE = re.compile(
    r"(?i)(?:от\s+)?(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[«\"]?[а-яё]+[»\"]?\s+\d{4})"
)
_DOC_KIND_RE = re.compile(
    r"(?i)\b(договор\s+поставки|договор\s+подряда|договор\s+купли[-\s]?продажи|"
    r"возражен\w*|ходатайств\w*)\b"
)


def _file_key(metadata: Mapping[str, Any]) -> str:
    fid = str(metadata.get("file_id") or metadata.get("doc_id") or "").strip()
    if fid:
        return f"id:{fid}"
    src = str(metadata.get("source_file") or metadata.get("filename") or "").strip()
    return f"file:{src or 'unknown'}"


def _scan_text_for_identity(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not text:
        return out
    m = _CONTRACT_NO_RE.search(text)
    if m:
        out["doc_no"] = m.group(1).strip()
    kind = _DOC_KIND_RE.search(text)
    if kind:
        out["kind"] = re.sub(r"\s+", " ", kind.group(1).strip().lower())
    # Prefer "от DD.MM.YYYY" near contract wording
    dm = re.search(
        r"(?i)(?:договор\w*.{0,40})?от\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        text,
    )
    if dm:
        out["date"] = dm.group(1).replace("/", ".")
    else:
        dm2 = _DATE_RE.search(text)
        if dm2 and "от" in text[max(0, dm2.start() - 8) : dm2.start() + 1].lower():
            out["date"] = dm2.group(1)
    return out


def _identity_from_filename(filename: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    name = filename or ""
    kind = _DOC_KIND_RE.search(name)
    if kind:
        out["kind"] = re.sub(r"\s+", " ", kind.group(1).strip().lower())
    m = _CONTRACT_NO_RE.search(name)
    if m:
        out["doc_no"] = m.group(1).strip()
    dm = re.search(r"(?i)от\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", name)
    if dm:
        out["date"] = dm.group(1).replace("/", ".")
    # "на 5л" / "на 14л" — полезно отличать twin PDF с одной датой
    pages = re.search(r"(?i)на\s+(\d+)\s*л", name)
    if pages:
        out["pages_hint"] = pages.group(1)
    return out


def infer_file_identity_bundle(
    documents: Iterable[Document],
) -> Dict[str, Dict[str, str]]:
    """
    Infer shared identity per file from all retrieved chunks of that file.

    A narrow clause chunk (only «90 дней») often lacks «№54»; a sibling chunk
    from the same file usually has the contract header — merge them.
    """
    buckets: Dict[str, Dict[str, str]] = {}
    texts: Dict[str, List[str]] = {}
    filenames: Dict[str, str] = {}

    for doc in documents:
        md = doc.metadata or {}
        key = _file_key(md)
        src = str(md.get("source_file") or md.get("filename") or "").strip()
        if src:
            filenames[key] = src
        parts = [
            src,
            str(md.get("section_title") or ""),
            " > ".join(str(p) for p in (md.get("parent_path") or []) if p),
            str(md.get("doc_summary_short") or md.get("file_summary") or "")[:400],
            (doc.page_content or "")[:800],
        ]
        texts.setdefault(key, []).append("\n".join(p for p in parts if p))

    for key, blobs in texts.items():
        merged: Dict[str, str] = {}
        fn = filenames.get(key, "")
        for piece in (_identity_from_filename(fn),):
            merged.update({k: v for k, v in piece.items() if v})
        for blob in blobs:
            found = _scan_text_for_identity(blob)
            for k, v in found.items():
                if v and k not in merged:
                    merged[k] = v
        if fn:
            merged["filename"] = fn
        # human title
        kind = merged.get("kind") or ""
        doc_no = merged.get("doc_no") or ""
        date = merged.get("date") or ""
        title_bits = []
        if kind:
            title_bits.append(kind)
        if doc_no:
            title_bits.append(f"№{doc_no}")
        if date:
            title_bits.append(f"от {date}")
        if title_bits:
            merged["title"] = " ".join(title_bits)
        buckets[key] = merged
    return buckets


def format_file_passport_line(
    metadata: Mapping[str, Any],
    *,
    identity: Optional[Mapping[str, str]] = None,
) -> str:
    """Single compact passport line for a chunk header."""
    md = metadata or {}
    ident = dict(identity or {})
    filename = str(
        ident.get("filename")
        or md.get("source_file")
        or md.get("filename")
        or "документ"
    ).strip()
    title = str(ident.get("title") or "").strip()
    kind = str(ident.get("kind") or md.get("doc_type_label") or md.get("doc_type") or "").strip()
    doc_no = str(ident.get("doc_no") or "").strip()
    date = str(ident.get("date") or "").strip()
    pages_hint = str(ident.get("pages_hint") or "").strip()

    bits: List[str] = [f"файл: {filename}"]
    if title:
        bits.append(f"документ: {title}")
    else:
        if kind:
            bits.append(f"тип: {kind}")
        if doc_no:
            bits.append(f"номер: №{doc_no}")
        if date:
            bits.append(f"дата: {date}")
    if pages_hint and f"{pages_hint}л" not in filename:
        bits.append(f"объём: {pages_hint}л")
    return "Паспорт: " + "; ".join(bits)


def passport_for_document(
    doc: Document,
    *,
    identities: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> str:
    md = doc.metadata or {}
    key = _file_key(md)
    ident = (identities or {}).get(key)
    return format_file_passport_line(md, identity=ident)


def stamp_file_summaries_on_documents(
    documents: List[Document],
    *,
    summaries_by_file_id: Mapping[str, str],
) -> None:
    """Copy file-level summary into chunk metadata for passport inference."""
    if not documents or not summaries_by_file_id:
        return
    for doc in documents:
        md = dict(doc.metadata or {})
        fid = str(md.get("file_id") or md.get("doc_id") or "").strip()
        summary = str(summaries_by_file_id.get(fid) or "").strip()
        if not summary:
            continue
        if not str(md.get("doc_summary_short") or "").strip():
            md["doc_summary_short"] = summary[:500]
            doc.metadata = md


def load_case_file_summary_map(db: Any, case_id: str) -> Dict[str, str]:
    """file_id -> doc_summary_short for a case (empty on failure)."""
    out: Dict[str, str] = {}
    if db is None or not case_id:
        return out
    try:
        from app.models.case import File

        rows = (
            db.query(File.id, File.doc_summary_short)
            .filter(File.case_id == str(case_id))
            .all()
        )
        for rid, summary in rows:
            text = str(summary or "").strip()
            if text:
                out[str(rid)] = text
        return out
    except Exception:
        try:
            from sqlalchemy import text as sql_text

            rows = db.execute(
                sql_text(
                    """
                    SELECT id::text, COALESCE(doc_summary_short, '')
                    FROM files WHERE case_id = :c
                    """
                ),
                {"c": str(case_id)},
            ).fetchall()
            for rid, summary in rows:
                text = str(summary or "").strip()
                if text:
                    out[str(rid)] = text
        except Exception:
            return {}
    return out


def attach_passports_to_source_headers(
    documents: List[Document],
) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """Return (identities, passport_line_per_doc_index)."""
    identities = infer_file_identity_bundle(documents)
    lines = [passport_for_document(d, identities=identities) for d in documents]
    return identities, lines
