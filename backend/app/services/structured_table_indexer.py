"""Structured table indexer — hybrid narrative + one chunk per table row (contract v1)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chunk_ids import generate_chunk_id
from app.services.document_structure_classifier import _count_table_data_rows
from app.services.legal_chunker import (
    LegalChunkerV2,
    _Profile,
    _Segment,
    _apply_hidden_embedding_context,
    _join_segments_text,
    _normalize_docling_segments,
    _parse_markdown_pipe_table,
    _select_profile,
)
from app.services.table_schema_normalize import (
    ColumnRole,
    ParsedPipeTable,
    align_values_to_schema,
    assess_operation_row_quality,
    extract_ordered_cells,
    lock_or_align_schema,
    normalize_header_schema,
    parse_markdown_pipe_table_schema,
    parsed_pipe_table_from_geometry,
    remap_row_columns_to_canonical,
    repair_parsed_table,
)
from app.services.docling_table_geometry import extract_pdf_page_words
from app.services.table_amount_geometry_recover import (
    recover_operation_table_from_page_geometry,
)

logger = logging.getLogger(__name__)

_CONTRACT_VERSION = "structured-table-v1"
_INDEX_PROFILE = "structured_table"
_HYBRID_FILE_PROFILE_KEY = "hybrid_file_profile"

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


def _min_transaction_rows() -> int:
    return max(1, int(getattr(config, "STRUCTURED_TABLE_MIN_ROWS", 8) or 8))


def is_transaction_table_segment(segment: _Segment) -> bool:
    """
    True when a Docling table segment should be indexed as operation rows (SQL + row RAG).

    Small layout tables (header metadata, ≤7 data rows) stay in the narrative path.
    """
    if not segment.is_table:
        return False
    return _count_table_data_rows(segment.text or "") >= _min_transaction_rows()


@dataclass(frozen=True)
class _IndexingCursor:
    chunk_index: int = 0
    char_offset: int = 0
    global_row_index: int = 0
    table_index: int = 0
    # File-level locked column schema (shared across multi-page table segments).
    canonical_columns: Tuple[str, ...] = ()
    canonical_roles: Tuple[str, ...] = ()


def _stamp_hybrid_file_profile(documents: Sequence[Document]) -> List[Document]:
    out: List[Document] = []
    for doc in documents:
        md = dict(doc.metadata or {})
        md[_HYBRID_FILE_PROFILE_KEY] = _INDEX_PROFILE
        out.append(Document(page_content=doc.page_content, metadata=md))
    return out


def _renumber_documents(
    documents: Sequence[Document],
    *,
    doc_id: str,
    cursor: _IndexingCursor,
) -> Tuple[List[Document], _IndexingCursor]:
    """Assign sequential chunk_index / char offsets across hybrid narrative + row chunks."""
    out: List[Document] = []
    chunk_index = cursor.chunk_index
    char_offset = cursor.char_offset

    for doc in documents:
        text = doc.page_content or ""
        if not text:
            continue
        char_start = char_offset
        char_end = char_start + len(text)
        md = dict(doc.metadata or {})
        md["chunk_index"] = chunk_index
        md["char_start"] = int(char_start)
        md["char_end"] = int(char_end)
        md["chunk_id"] = generate_chunk_id(str(doc_id), chunk_index, int(char_start))
        out.append(Document(page_content=text, metadata=md))
        chunk_index += 1
        char_offset = char_end

    return out, _IndexingCursor(
        chunk_index=chunk_index,
        char_offset=char_offset,
        global_row_index=cursor.global_row_index,
        table_index=cursor.table_index,
        canonical_columns=cursor.canonical_columns,
        canonical_roles=cursor.canonical_roles,
    )


def _chunk_narrative_segments(
    segments: Sequence[_Segment],
    *,
    profile: _Profile,
    preseg_strategy: str,
    base_metadata: Dict[str, Any],
    filename: str,
) -> List[Document]:
    """Macro/micro chunking for non-transaction blocks (document header, footnotes, small tables)."""
    if not segments:
        return []

    normalized = _normalize_docling_segments(list(segments), profile)
    if not normalized:
        return []

    batch_text = _join_segments_text(normalized)
    docs = LegalChunkerV2().chunk_from_segments(
        segments=normalized,
        full_text=batch_text,
        preseg_strategy=preseg_strategy,
        profile=profile,
        base_metadata=base_metadata,
        filename=filename,
    )
    return _stamp_hybrid_file_profile(docs)


class StructuredTableIndexer:
    """Hybrid indexer: narrative blocks via LegalChunkerV2, transaction tables one row per chunk."""

    contract_version = _CONTRACT_VERSION

    def index(
        self,
        *,
        segments: Sequence[_Segment],
        full_text: str,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
        profile: Optional[_Profile] = None,
        doc_type: Optional[str] = None,
        pdf_bytes: Optional[bytes] = None,
    ) -> List[Document]:
        if not segments:
            raise ValueError(f"StructuredTableIndexer: empty segments for {filename}")

        md_base = dict(base_metadata or {})
        doc_id = str(md_base.get("doc_id") or md_base.get("file_id") or filename)
        case_id = str(md_base.get("case_id") or "")
        chunk_profile = profile or _select_profile(
            case_id=case_id or None,
            doc_type=doc_type,
        )

        documents: List[Document] = []
        cursor = _IndexingCursor()
        narrative_batch: List[_Segment] = []

        def flush_narrative() -> None:
            nonlocal cursor, narrative_batch
            if not narrative_batch:
                return
            narrative_docs = _chunk_narrative_segments(
                narrative_batch,
                profile=chunk_profile,
                preseg_strategy=preseg_strategy,
                base_metadata=md_base,
                filename=filename,
            )
            renumbered, cursor = _renumber_documents(
                narrative_docs,
                doc_id=doc_id,
                cursor=cursor,
            )
            documents.extend(renumbered)
            narrative_batch = []

        for seg in segments:
            if is_transaction_table_segment(seg):
                flush_narrative()
                row_docs, next_canonical, next_roles = self._index_table_segment(
                    seg=seg,
                    table_index=cursor.table_index,
                    global_row_index_start=cursor.global_row_index,
                    base_metadata=md_base,
                    preseg_strategy=preseg_strategy,
                    filename=filename,
                    doc_id=doc_id,
                    canonical_columns=list(cursor.canonical_columns),
                    canonical_roles=list(cursor.canonical_roles),
                    pdf_bytes=pdf_bytes,
                )
                row_docs = _stamp_hybrid_file_profile(row_docs)
                renumbered, cursor = _renumber_documents(
                    row_docs,
                    doc_id=doc_id,
                    cursor=cursor,
                )
                documents.extend(renumbered)
                cursor = _IndexingCursor(
                    chunk_index=cursor.chunk_index,
                    char_offset=cursor.char_offset,
                    global_row_index=cursor.global_row_index + len(row_docs),
                    table_index=cursor.table_index + 1,
                    canonical_columns=tuple(next_canonical),
                    canonical_roles=tuple(next_roles),
                )
                continue

            text = (seg.text or "").strip()
            if text:
                narrative_batch.append(seg)

        flush_narrative()

        if not documents:
            raise ValueError(f"StructuredTableIndexer: produced no chunks for {filename}")

        _apply_hidden_embedding_context(
            documents,
            enabled=bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True)),
        )

        macro_n = sum(1 for d in documents if d.metadata.get("chunk_level") == "macro")
        micro_n = sum(1 for d in documents if d.metadata.get("chunk_level") == "micro")
        row_n = sum(1 for d in documents if d.metadata.get("chunk_level") == "row")
        logger.info(
            "[StructuredTableIndexer] %s: %s chunks (macro=%s micro=%s rows=%s tables=%s)",
            filename,
            len(documents),
            macro_n,
            micro_n,
            row_n,
            cursor.table_index,
        )
        return documents

    def _index_table_segment(
        self,
        *,
        seg: _Segment,
        table_index: int,
        global_row_index_start: int,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
        doc_id: str,
        canonical_columns: Optional[Sequence[str]] = None,
        canonical_roles: Optional[Sequence[str]] = None,
        pdf_bytes: Optional[bytes] = None,
    ) -> Tuple[List[Document], List[str], List[str]]:
        locked = list(canonical_columns) if canonical_columns else None
        locked_roles = list(canonical_roles) if canonical_roles and locked else None

        parsed: Optional[ParsedPipeTable] = None
        geom = getattr(seg, "table_geometry", None)
        if geom is not None and getattr(geom, "headers", None):
            parsed = parsed_pipe_table_from_geometry(
                list(geom.headers),
                list(geom.rows or []),
                locked_columns=locked,
                locked_roles=locked_roles,
                source=str(getattr(geom, "source", None) or "docling_grid"),
            )
            if parsed is not None:
                logger.info(
                    "[StructuredTableIndexer] table %s via native grid (%s rows, source=%s)",
                    table_index,
                    len(parsed.data_rows),
                    getattr(geom, "source", "docling_grid"),
                )

        if not parsed:
            parsed = parse_markdown_pipe_table_schema(
                seg.text or "",
                locked_columns=locked,
                locked_roles=locked_roles,
            )
        if not parsed:
            # Fallback: legacy single-header parser for odd markdown, then same repair path.
            legacy = _parse_markdown_pipe_table(seg.text or "")
            if not legacy:
                logger.warning(
                    "[StructuredTableIndexer] table segment %s has no parseable markdown; skipping",
                    table_index,
                )
                return [], list(canonical_columns or []), list(canonical_roles or [])
            header_line, _sep, data_lines = legacy
            raw_headers = _parse_header_columns(header_line)
            local_columns, value_indices = normalize_header_schema(raw_headers)
            provisional = ParsedPipeTable(
                columns=local_columns,
                data_rows=[_split_pipe_row(line) for line in data_lines],
                raw_header_cells=list(raw_headers),
                value_indices=value_indices,
            )
            parsed = repair_parsed_table(
                provisional,
                locked_columns=locked,
                locked_roles=(
                    [ColumnRole(r) for r in locked_roles] if locked_roles else None
                ),
            )

        parsed = self._maybe_recover_amounts_from_pdf(
            parsed,
            page_no=seg.page_no,
            pdf_bytes=pdf_bytes,
        )

        local_columns = list(parsed.columns)
        value_indices = list(parsed.value_indices or range(len(parsed.columns)))
        data_rows = list(parsed.data_rows)

        schema, established = lock_or_align_schema(
            local_columns=local_columns,
            canonical=list(canonical_columns) if canonical_columns else None,
        )
        if not schema:
            return [], list(canonical_columns or []), list(canonical_roles or [])

        # Once locked, never rebuild schema from repeated page headers.
        if canonical_columns:
            next_canonical = list(canonical_columns)
            next_roles = list(canonical_roles or parsed.column_roles or ())
            schema = next_canonical
        else:
            next_canonical = schema if established else list(local_columns)
            next_roles = list(parsed.column_roles or ())

        documents: List[Document] = []
        for row_index, values in enumerate(data_rows):
            if not any(str(v or "").strip() for v in values):
                continue

            ordered_cells = extract_ordered_cells(values, value_indices)
            if len(ordered_cells) == len(schema):
                # Same arity as locked schema → positional map onto canonical names.
                row_columns = align_values_to_schema(ordered_cells, schema)
            else:
                provisional = align_values_to_schema(ordered_cells, local_columns)
                row_columns = remap_row_columns_to_canonical(provisional, schema)

            if not row_columns:
                continue

            ordered_vals = [row_columns.get(c, "") for c in schema]
            body = _format_row_content(list(schema), ordered_vals)
            if not body.strip():
                continue

            # Trailing newline was historically appended for display; it broke
            # char spans vs original_text ("\n\n".join). Keep body clean —
            # align_structured_table_row_stream owns the join contract.
            chunk_text = body.strip()
            metadata = self._build_row_metadata(
                base_metadata=base_metadata,
                preseg_strategy=preseg_strategy,
                filename=filename,
                doc_id=doc_id,
                section_title=seg.section_title,
                page_no=seg.page_no,
                prov_items=seg.prov_items,
                page_bbox=seg.page_bbox,
                table_index=table_index,
                row_index=row_index,
                global_row_index=global_row_index_start + row_index,
                row_columns=row_columns,
                column_roles=list(next_roles or parsed.column_roles or ()),
                schema_quality=float(parsed.quality_score or 1.0),
            )
            documents.append(Document(page_content=chunk_text, metadata=metadata))

        return documents, next_canonical, next_roles

    @staticmethod
    def _maybe_recover_amounts_from_pdf(
        parsed: ParsedPipeTable,
        *,
        page_no: Optional[int],
        pdf_bytes: Optional[bytes],
    ) -> ParsedPipeTable:
        """
        Second pass via PDF word geometry: empty amount/balance cells, channel
        text on multi-line ops, and missing amount+balance spines dropped by
        TableFormer.
        """
        if not pdf_bytes or page_no is None or int(page_no) < 1:
            return parsed
        if not parsed.column_roles or not parsed.data_rows:
            return parsed
        if "amount" not in parsed.column_roles:
            return parsed

        words, _height = extract_pdf_page_words(pdf_bytes, int(page_no) - 1)
        if not words:
            return parsed

        new_rows, geo_stats = recover_operation_table_from_page_geometry(
            parsed.columns,
            parsed.data_rows,
            list(parsed.column_roles),
            words,
        )
        if not geo_stats.total:
            return parsed

        warnings = tuple(parsed.quality_warnings or ()) + (
            f"amount_geometry_recovered:{geo_stats.amounts}",
            f"balance_geometry_recovered:{geo_stats.balances}",
            f"category_geometry_recovered:{geo_stats.categories}",
            f"rows_geometry_inserted:{geo_stats.rows_inserted}",
        )
        return ParsedPipeTable(
            columns=list(parsed.columns),
            data_rows=new_rows,
            raw_header_cells=list(parsed.raw_header_cells),
            value_indices=list(parsed.value_indices),
            quality_score=parsed.quality_score,
            quality_warnings=warnings,
            column_roles=tuple(parsed.column_roles),
        )

    @staticmethod
    def _build_row_metadata(
        *,
        base_metadata: Dict[str, Any],
        preseg_strategy: str,
        filename: str,
        doc_id: str,
        section_title: str,
        page_no: Optional[int],
        prov_items: Optional[List[Dict[str, Any]]],
        page_bbox: Optional[Dict[str, float]],
        table_index: int,
        row_index: int,
        global_row_index: int,
        row_columns: Dict[str, str],
        column_roles: Optional[Sequence[str]] = None,
        schema_quality: float = 1.0,
    ) -> Dict[str, Any]:
        md: Dict[str, Any] = dict(base_metadata)
        md["source_file"] = filename
        md["doc_id"] = doc_id
        md["chunk_level"] = "row"
        md["chunk_profile"] = _INDEX_PROFILE
        md["index_profile"] = _INDEX_PROFILE
        md["chunking_contract_version"] = _CONTRACT_VERSION
        md["preseg_strategy"] = preseg_strategy
        md["section_title"] = section_title or ""
        md["section_number"] = ""
        md["parent_path"] = []
        md["clause_type"] = ""
        md["cross_references"] = []
        md["macro_id"] = ""
        md["parent_macro_id"] = ""
        md["is_table_fragment"] = False
        md["is_table_row"] = True
        md["table_index"] = int(table_index)
        md["row_index"] = int(row_index)
        md["global_row_index"] = int(global_row_index)
        md["row_columns"] = row_columns
        if column_roles:
            md["column_roles"] = list(column_roles)
        md["schema_quality"] = float(schema_quality)
        row_score, row_warnings = assess_operation_row_quality(
            row_columns,
            column_roles=column_roles,
        )
        md["row_quality"] = float(row_score)
        if row_warnings:
            md["row_quality_warnings"] = list(row_warnings)

        if page_no is not None:
            md["page_start"] = int(page_no)
            md["page_end"] = int(page_no)

        if prov_items:
            dl_meta: Dict[str, Any] = {"doc_items": [{"prov": prov_items}]}
            if page_bbox:
                dl_meta["page_bbox"] = page_bbox
            md["dl_meta"] = dl_meta

        return md


def is_structured_table_document(documents: Sequence[Document]) -> bool:
    return any(
        (d.metadata or {}).get("index_profile") == _INDEX_PROFILE
        or (d.metadata or {}).get(_HYBRID_FILE_PROFILE_KEY) == _INDEX_PROFILE
        for d in documents
    )
