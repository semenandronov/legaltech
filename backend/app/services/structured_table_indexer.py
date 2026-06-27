"""Structured table indexer — one chunk per Docling table row (contract v1)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.documents import Document

from app.config import config
from app.services.chunk_ids import generate_chunk_id
from app.services.legal_chunker import (
    _Segment,
    _apply_hidden_embedding_context,
    _parse_markdown_pipe_table,
)

logger = logging.getLogger(__name__)

_CONTRACT_VERSION = "structured-table-v1"
_INDEX_PROFILE = "structured_table"

_PIPE_ROW_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _split_pipe_row(line: str) -> List[str]:
    inner = (line or "").strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in _PIPE_ROW_SPLIT_RE.split(inner)]


def _parse_header_columns(header_line: str) -> List[str]:
    cells = _split_pipe_row(header_line)
    return [c if c else f"column_{i}" for i, c in enumerate(cells)]


def _format_row_content(columns: Sequence[str], values: Sequence[str]) -> str:
    pairs: List[str] = []
    for idx, col in enumerate(columns):
        val = values[idx] if idx < len(values) else ""
        if col and val:
            pairs.append(f"{col}: {val}")
    return "\n".join(pairs)


def _preamble_text(segment: _Segment) -> str:
    return (segment.text or "").strip()


class StructuredTableIndexer:
    """Build vector chunks from Docling AST for tabular-dominant documents."""

    contract_version = _CONTRACT_VERSION

    def index(
        self,
        *,
        segments: Sequence[_Segment],
        full_text: str,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
    ) -> List[Document]:
        if not segments:
            raise ValueError(f"StructuredTableIndexer: empty segments for {filename}")

        md_base = dict(base_metadata or {})
        doc_id = str(md_base.get("doc_id") or md_base.get("file_id") or filename)

        documents: List[Document] = []
        chunk_index = 0
        char_offset = 0
        global_row_index = 0
        table_index = 0

        for seg in segments:
            if seg.is_table:
                row_docs = self._index_table_segment(
                    seg=seg,
                    table_index=table_index,
                    global_row_index_start=global_row_index,
                    chunk_index_start=chunk_index,
                    char_offset_start=char_offset,
                    base_metadata=md_base,
                    preseg_strategy=preseg_strategy,
                    filename=filename,
                    doc_id=doc_id,
                )
                global_row_index += len(row_docs)
                chunk_index += len(row_docs)
                if row_docs:
                    last = row_docs[-1]
                    char_offset = int(last.metadata.get("char_end") or char_offset)
                table_index += 1
                documents.extend(row_docs)
                continue

            text = _preamble_text(seg)
            if not text:
                continue

            chunk_text = text + "\n"
            char_start = char_offset
            char_end = char_start + len(chunk_text)
            char_offset = char_end

            metadata = self._build_metadata(
                base_metadata=md_base,
                preseg_strategy=preseg_strategy,
                filename=filename,
                doc_id=doc_id,
                chunk_index=chunk_index,
                chunk_level="preamble",
                char_start=char_start,
                char_end=char_end,
                section_title=seg.section_title,
                page_no=seg.page_no,
                prov_items=seg.prov_items,
                page_bbox=seg.page_bbox,
            )
            documents.append(Document(page_content=chunk_text, metadata=metadata))
            chunk_index += 1

        if not documents:
            raise ValueError(f"StructuredTableIndexer: produced no chunks for {filename}")

        _apply_hidden_embedding_context(
            documents,
            enabled=bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True)),
        )

        logger.info(
            "[StructuredTableIndexer] %s: %s chunks (preamble=%s, rows=%s, tables=%s)",
            filename,
            len(documents),
            sum(1 for d in documents if d.metadata.get("chunk_level") == "preamble"),
            sum(1 for d in documents if d.metadata.get("chunk_level") == "row"),
            table_index,
        )
        return documents

    def _index_table_segment(
        self,
        *,
        seg: _Segment,
        table_index: int,
        global_row_index_start: int,
        chunk_index_start: int,
        char_offset_start: int,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
        doc_id: str,
    ) -> List[Document]:
        parsed = _parse_markdown_pipe_table(seg.text or "")
        if not parsed:
            logger.warning(
                "[StructuredTableIndexer] table segment %s has no parseable markdown; skipping",
                table_index,
            )
            return []

        header_line, _sep, data_lines = parsed
        columns = _parse_header_columns(header_line)
        documents: List[Document] = []
        char_offset = char_offset_start
        chunk_index = chunk_index_start

        for row_index, line in enumerate(data_lines):
            values = _split_pipe_row(line)
            if not any(values):
                continue

            row_columns = {
                columns[i]: values[i]
                for i in range(min(len(columns), len(values)))
                if columns[i]
            }
            body = _format_row_content(columns, values)
            if not body.strip():
                continue

            chunk_text = body + "\n"
            char_start = char_offset
            char_end = char_start + len(chunk_text)
            char_offset = char_end

            metadata = self._build_metadata(
                base_metadata=base_metadata,
                preseg_strategy=preseg_strategy,
                filename=filename,
                doc_id=doc_id,
                chunk_index=chunk_index,
                chunk_level="row",
                char_start=char_start,
                char_end=char_end,
                section_title=seg.section_title,
                page_no=seg.page_no,
                prov_items=seg.prov_items,
                page_bbox=seg.page_bbox,
                table_index=table_index,
                row_index=row_index,
                global_row_index=global_row_index_start + row_index,
                row_columns=row_columns,
            )
            documents.append(Document(page_content=chunk_text, metadata=metadata))
            chunk_index += 1

        return documents

    @staticmethod
    def _build_metadata(
        *,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
        doc_id: str,
        chunk_index: int,
        chunk_level: str,
        char_start: int,
        char_end: int,
        section_title: str,
        page_no: Optional[int],
        prov_items: Optional[List[Dict[str, Any]]],
        page_bbox: Optional[Dict[str, float]],
        table_index: Optional[int] = None,
        row_index: Optional[int] = None,
        global_row_index: Optional[int] = None,
        row_columns: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        md: Dict[str, Any] = dict(base_metadata)
        md["source_file"] = filename
        md["doc_id"] = doc_id
        md["chunk_index"] = int(chunk_index)
        md["chunk_id"] = generate_chunk_id(str(doc_id), int(chunk_index), int(char_start))
        md["chunk_level"] = chunk_level
        md["chunk_profile"] = _INDEX_PROFILE
        md["index_profile"] = _INDEX_PROFILE
        md["chunking_contract_version"] = _CONTRACT_VERSION
        md["preseg_strategy"] = preseg_strategy
        md["char_start"] = int(char_start)
        md["char_end"] = int(char_end)
        md["section_title"] = section_title or ""
        md["section_number"] = ""
        md["parent_path"] = []
        md["clause_type"] = ""
        md["cross_references"] = []
        md["macro_id"] = ""
        md["parent_macro_id"] = ""
        md["is_table_fragment"] = False

        if page_no is not None:
            md["page_start"] = int(page_no)
            md["page_end"] = int(page_no)

        if chunk_level == "row":
            md["is_table_row"] = True
            md["table_index"] = int(table_index if table_index is not None else 0)
            md["row_index"] = int(row_index if row_index is not None else 0)
            md["global_row_index"] = int(
                global_row_index if global_row_index is not None else 0
            )
            if row_columns:
                md["row_columns"] = row_columns

        if prov_items:
            dl_meta: Dict[str, Any] = {"doc_items": [{"prov": prov_items}]}
            if page_bbox:
                dl_meta["page_bbox"] = page_bbox
            md["dl_meta"] = dl_meta

        return md


def is_structured_table_document(documents: Sequence[Document]) -> bool:
    return any(
        (d.metadata or {}).get("index_profile") == _INDEX_PROFILE for d in documents
    )
