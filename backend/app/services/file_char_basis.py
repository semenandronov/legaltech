"""Canonical citation text = the string that char_start/char_end index into.

CITATION_CONTRACT: for narrative/PDF/OCR chunks,
``File.original_text[char_start:char_end]`` must match the coordinate space used
at indexing. Structured rows use ``structured_row_stream`` (see
``structured_file_text``); everything else uses the LegalChunker / docling-direct
full text attached here as an ingest-only carrier document.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from langchain_core.documents import Document

# Ingest-only sentinel — never stored in PGVector.
CHAR_BASIS_CHUNK_LEVEL = "__char_basis__"

CHAR_BASIS_LEGAL_CHUNKER = "legal_chunker_full_text"
CHAR_BASIS_DOCLING_DIRECT = "docling_direct_nn_join"
CHAR_BASIS_STRUCTURED_ROW = "structured_row_stream"
CHAR_BASIS_LOADER_JOIN = "loader_join"


def is_char_basis_carrier(doc: Document) -> bool:
    md = doc.metadata or {}
    return str(md.get("chunk_level") or "").strip() == CHAR_BASIS_CHUNK_LEVEL


def attach_char_basis(
    documents: Sequence[Document],
    text: str,
    basis: str,
) -> List[Document]:
    """
    Stamp ``char_basis`` on real chunks and prepend an ingest-only carrier
    holding the canonical full text (not embedded / not stored).
    """
    basis_name = (basis or "").strip() or CHAR_BASIS_LEGAL_CHUNKER
    body = text if isinstance(text, str) else ""
    stamped: List[Document] = []
    for doc in documents or []:
        if is_char_basis_carrier(doc):
            continue
        md = dict(doc.metadata or {})
        md["char_basis"] = basis_name
        stamped.append(Document(page_content=doc.page_content, metadata=md))
    if not body:
        return stamped
    carrier = Document(
        page_content=body,
        metadata={
            "chunk_level": CHAR_BASIS_CHUNK_LEVEL,
            "char_basis": basis_name,
        },
    )
    return [carrier, *stamped]


def peel_char_basis(
    documents: Sequence[Document],
) -> Tuple[List[Document], Optional[str], Optional[str]]:
    """
    Remove carrier docs. Returns (real_docs, basis_text, basis_name).

    If several carriers exist, the first non-empty text wins.
    """
    out: List[Document] = []
    basis_text: Optional[str] = None
    basis_name: Optional[str] = None
    for doc in documents or []:
        if is_char_basis_carrier(doc):
            if basis_text is None:
                raw = doc.page_content if isinstance(doc.page_content, str) else ""
                if raw:
                    basis_text = raw
                    basis_name = str((doc.metadata or {}).get("char_basis") or "").strip() or None
            continue
        out.append(doc)
    return out, basis_text, basis_name


def docling_direct_char_basis(langchain_docs: Sequence[Document]) -> str:
    """Same join contract as ``DocumentProcessor`` docling-direct-v1 offsets."""
    parts: List[str] = []
    for src in langchain_docs or []:
        chunk_text = str((src.page_content or "")).strip()
        if chunk_text:
            parts.append(chunk_text)
    return "\n\n".join(parts)


def resolve_ingest_original_text(
    documents: Sequence[Document],
    *,
    loader_text: str,
) -> Tuple[List[Document], str, str]:
    """
    Align indexed docs + choose ``File.original_text`` for citation offsets.

    Priority:
    1. structured_row_stream (rewrites row offsets to match joined bodies)
    2. peeled LegalChunker / docling-direct carrier
    3. loader join (last resort; may diverge from offsets)
    """
    from app.services.structured_file_text import align_structured_table_row_stream

    # Drop any carrier before structured align (carrier is not a row).
    real_docs, carrier_text, carrier_basis = peel_char_basis(documents)
    aligned, structured_joined = align_structured_table_row_stream(real_docs)

    if structured_joined and structured_joined.strip():
        return aligned, structured_joined, CHAR_BASIS_STRUCTURED_ROW

    if carrier_text and carrier_text.strip():
        name = carrier_basis or CHAR_BASIS_LEGAL_CHUNKER
        stamped: List[Document] = []
        for doc in aligned:
            md = dict(doc.metadata or {})
            md.setdefault("char_basis", name)
            stamped.append(Document(page_content=doc.page_content, metadata=md))
        return stamped, carrier_text, name

    fallback = loader_text if isinstance(loader_text, str) else ""
    return aligned, fallback, CHAR_BASIS_LOADER_JOIN
