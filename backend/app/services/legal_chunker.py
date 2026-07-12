"""LegalChunkerV2 — Docling-aware двухуровневый chunker (macro/micro).

Восстанавливает контракт `v2.1` из `backend/docs/LEGAL_CHUNKING_CONTRACT.md`:

- macro: section-level блоки (1100–1400 chars) для широкого контекста.
- micro: clause-level блоки (240–320 chars) для точного цитирования.

Pre-segmentation работает напрямую по AST DoclingDocument (sections, paragraphs,
list items, tables). Для не-Docling форматов (TXT, прочее) — fallback на
RecursiveCharacterTextSplitter с legal-сепараторами.

Все чанки получают набор полей метаданных, описанный в контракте:
    chunk_id, chunk_index, chunk_level, chunk_profile,
    char_start, char_end,
    section_title, section_number, parent_path,
    clause_type, cross_references,
    parent_macro_id, macro_id,
    chunking_contract_version="v2.1",
    preseg_strategy ("docling_ast_first" | "text_recursive_legal").

Модуль не делает запись в БД и не зависит от FastAPI/SQLAlchemy. Подключается из
`document_processor.split_documents` под флагом `LEGAL_CHUNKING_DUAL_ENABLED`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chunk_ids import generate_chunk_id
from app.services.docling_table_geometry import export_table_item_markdown

logger = logging.getLogger(__name__)


# --- Profiles --------------------------------------------------------------

@dataclass(frozen=True)
class _Profile:
    name: str
    macro_size: int
    macro_overlap: int
    micro_size: int
    micro_overlap: int


_PROFILES: Dict[str, _Profile] = {
    "regulations": _Profile("regulations", 1100, 120, 240, 32),
    "court_docs": _Profile("court_docs", 1200, 160, 260, 40),
    "contracts": _Profile("contracts", 1400, 180, 320, 40),
}

_REGULATIONS_DOC_TYPES = {"law", "regulation", "code", "legal_reference"}
_COURT_DOC_DOC_TYPES = {
    "court_decision",
    "claim",
    "complaint",
    "statement_of_claim",
    "ruling",
    "lawsuit",
    "court_order",
    "court_act",
}

GLOBAL_LEGAL_CORPUS_CASE_ID = "GLOBAL_LEGAL_CORPUS"

_EMBED_HINTS: Dict[str, str] = {
    "fz-127": (
        "оспаривание сделок, заинтересованные лица, недействительность сделки должника, "
        "подозрительная сделка, родственники, аффилированность, период подозрительности, "
        "неравноценное встречное исполнение, вред кредиторам, контролирующее лицо"
    ),
    "plenum-63": (
        "оспаривание сделок должника, подозрительные сделки, предпочтительные сделки, "
        "злоупотребление правом, заинтересованность, срок исковой давности"
    ),
    "gk-rf": (
        "недействительность сделки, ничтожность, оспоримость, злоупотребление правом, "
        "притворная сделка, мнимая сделка"
    ),
}


def _select_profile(case_id: Optional[str], doc_type: Optional[str]) -> _Profile:
    """Выбираем профиль чанкинга по case_id и doc_type."""
    if case_id and str(case_id) == GLOBAL_LEGAL_CORPUS_CASE_ID:
        return _PROFILES["regulations"]

    dt = (doc_type or "").strip().lower()
    if dt in _REGULATIONS_DOC_TYPES:
        return _PROFILES["regulations"]
    if dt in _COURT_DOC_DOC_TYPES:
        return _PROFILES["court_docs"]

    default_name = str(getattr(config, "LEGAL_CHUNKING_DEFAULT_PROFILE", "contracts") or "contracts").strip().lower()
    return _PROFILES.get(default_name, _PROFILES["contracts"])


# --- Legal-aware regexes ---------------------------------------------------

_LEGAL_SEPARATORS: List[str] = [
    "\n\nЧасть ",
    "\n\nРаздел ",
    "\n\nГлава ",
    "\n\nПараграф ",
    "\n\n§ ",
    "\n\nСтатья ",
    "\n\nПункт ",
    "\n\n",
    "\n",
    ". ",
    " ",
    "",
]

_SECTION_HEAD_RE = re.compile(
    r"^\s*(?P<kind>"
    r"Часть|Раздел|Глава|Параграф|§|Статья|Пункт|Подпункт|Приложение"
    r")\s*"
    r"(?P<num>[\dIVXLCDM]+(?:[.\-–]\d+)*)?",
    re.IGNORECASE,
)

_CLAUSE_KIND_MAP: Dict[str, str] = {
    "часть": "part",
    "раздел": "section",
    "глава": "chapter",
    "параграф": "paragraph",
    "§": "paragraph",
    "статья": "article",
    "пункт": "clause",
    "подпункт": "subclause",
    "приложение": "annex",
}

_CROSS_REF_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bст\.?\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\bстат(?:ья|ьи|ье|ью|ьей|ей|ьми|ями)\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\bп\.?\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\bпункт(?:а|ом|ы|ах)?\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\bч\.?\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\bчаст(?:ь|и|ью)\s*\d+(?:[.,]\d+)*", re.IGNORECASE),
    re.compile(r"\b§\s*\d+(?:[.,]\d+)*"),
]

_DOCLING_SUPPORTED_EXTS = {".pdf", ".docx", ".html", ".htm", ".md", ".pptx"}


# --- Internal data structures ---------------------------------------------

@dataclass
class _Segment:
    """Плоский AST-сегмент Docling/Loader, нормализованный для группировки."""

    text: str
    section_title: str
    section_number: str
    parent_path: List[str] = field(default_factory=list)
    page_no: Optional[int] = None
    char_start: int = 0
    char_end: int = 0
    is_heading: bool = False
    is_table: bool = False
    is_table_fragment: bool = False
    table_shard_index: Optional[int] = None
    prov_items: List[Dict[str, Any]] = field(default_factory=list)
    page_bbox: Optional[Dict[str, float]] = None


@dataclass
class _MacroChunk:
    text: str
    char_start: int
    char_end: int
    section_title: str
    section_number: str
    parent_path: List[str]
    page_start: Optional[int]
    page_end: Optional[int]
    macro_id: str
    macro_index: int
    has_table_fragment: bool = False
    prov_items: List[Dict[str, Any]] = field(default_factory=list)
    page_bbox: Optional[Dict[str, float]] = None
    # Per-segment prov with char spans — used to scope bbox to micro chunks.
    prov_spans: List[Tuple[int, int, List[Dict[str, Any]]]] = field(default_factory=list)


# --- Public API ------------------------------------------------------------

class LegalChunkerV2:
    """Двухуровневый legal-aware chunker (контракт v2.1).

    Использование:
        chunker = LegalChunkerV2()
        documents = chunker.chunk(
            content_bytes=raw_bytes,
            filename="kodeks.pdf",
            base_metadata={"doc_id": file_id, "case_id": case_id, ...},
            doc_type="code",
            case_id=case_id,
            fallback_text=plain_text,  # для не-Docling форматов
        )
    """

    contract_version = "v2.1"

    def chunk(
        self,
        *,
        content_bytes: Optional[bytes],
        filename: str,
        base_metadata: Dict[str, Any],
        doc_type: Optional[str] = None,
        case_id: Optional[str] = None,
        fallback_text: Optional[str] = None,
        loader_did_ocr: bool = False,
        loader_native_text: bool = False,
        loader_documents: Optional[List[Document]] = None,
    ) -> List[Document]:
        if not isinstance(base_metadata, dict):
            base_metadata = dict(base_metadata or {})

        segments, full_text, preseg_strategy, profile = _collect_legal_segments(
            content_bytes=content_bytes,
            filename=filename,
            doc_type=doc_type,
            case_id=case_id,
            fallback_text=fallback_text,
            loader_did_ocr=loader_did_ocr,
            loader_native_text=loader_native_text,
            loader_documents=loader_documents,
        )
        if not segments:
            raise ValueError(f"LegalChunkerV2: empty segment list for {filename}")

        return self.chunk_from_segments(
            segments=segments,
            full_text=full_text,
            preseg_strategy=preseg_strategy,
            profile=profile,
            base_metadata=base_metadata,
            filename=filename,
        )

    def chunk_from_segments(
        self,
        *,
        segments: Sequence[_Segment],
        full_text: str,
        preseg_strategy: str,
        profile: _Profile,
        base_metadata: Dict[str, Any],
        filename: str,
    ) -> List[Document]:
        if not isinstance(base_metadata, dict):
            base_metadata = dict(base_metadata or {})

        macros = _build_macro_chunks(list(segments), profile, base_metadata)
        if not macros:
            raise ValueError(f"LegalChunkerV2: macro layer is empty for {filename}")

        micros = _build_micro_chunks(macros, profile, base_metadata)

        documents: List[Document] = []
        chunk_index = 0
        doc_id = str(base_metadata.get("doc_id") or base_metadata.get("file_id") or filename)

        for macro in macros:
            md = _build_chunk_metadata(
                base_metadata=base_metadata,
                profile=profile,
                full_text=full_text,
                preseg_strategy=preseg_strategy,
                level="macro",
                section_title=macro.section_title,
                section_number=macro.section_number,
                parent_path=macro.parent_path,
                page_start=macro.page_start,
                page_end=macro.page_end,
                char_start=macro.char_start,
                char_end=macro.char_end,
                chunk_text=macro.text,
                chunk_index=chunk_index,
                macro_id=macro.macro_id,
                parent_macro_id=None,
                doc_id=doc_id,
                filename=filename,
                is_table_fragment=bool(getattr(macro, "has_table_fragment", False)),
                prov_items=macro.prov_items or None,
                page_bbox=macro.page_bbox,
            )
            documents.append(Document(page_content=macro.text, metadata=md))
            chunk_index += 1

        for micro in micros:
            md = _build_chunk_metadata(
                base_metadata=base_metadata,
                profile=profile,
                full_text=full_text,
                preseg_strategy=preseg_strategy,
                level="micro",
                section_title=micro["section_title"],
                section_number=micro["section_number"],
                parent_path=micro["parent_path"],
                page_start=micro["page_start"],
                page_end=micro["page_end"],
                char_start=micro["char_start"],
                char_end=micro["char_end"],
                chunk_text=micro["text"],
                chunk_index=chunk_index,
                macro_id=micro["macro_id"],
                parent_macro_id=micro["macro_id"],
                doc_id=doc_id,
                filename=filename,
                is_table_fragment=bool(micro.get("is_table_fragment", False)),
                prov_items=micro.get("prov_items") or None,
                page_bbox=micro.get("page_bbox"),
            )
            documents.append(Document(page_content=micro["text"], metadata=md))
            chunk_index += 1

        _apply_hidden_embedding_context(
            documents,
            enabled=bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True)),
        )

        return documents

    def chunk_corpus_norms(
        self,
        *,
        content_bytes: Optional[bytes],
        filename: str,
        base_metadata: Dict[str, Any],
        doc_type: Optional[str] = None,
        case_id: Optional[str] = None,
        fallback_text: Optional[str] = None,
        loader_did_ocr: bool = False,
        loader_native_text: bool = False,
        loader_documents: Optional[List[Document]] = None,
        prepared_pdf_text: Optional[str] = None,
    ) -> List[Document]:
        """Article/clause-level chunking для GLOBAL_LEGAL_CORPUS (фаза A)."""
        if not isinstance(base_metadata, dict):
            base_metadata = dict(base_metadata or {})

        pdf_text = (prepared_pdf_text or "").strip() or None
        text_first = bool(getattr(config, "LEGAL_CORPUS_PDF_TEXT_FIRST", False))
        ext = _file_ext(filename)
        use_pdf_text_only = bool(text_first and pdf_text and ext == ".pdf")

        primary_fallback = pdf_text or fallback_text
        content_for_docling = None if use_pdf_text_only else content_bytes
        native_text = loader_native_text and not use_pdf_text_only

        segments, full_text, preseg_strategy, profile = _collect_legal_segments(
            content_bytes=content_for_docling,
            filename=filename,
            doc_type=doc_type or "legal_reference",
            case_id=case_id or "GLOBAL_LEGAL_CORPUS",
            fallback_text=primary_fallback,
            loader_did_ocr=loader_did_ocr,
            loader_native_text=native_text,
            loader_documents=loader_documents,
        )
        if not segments:
            raise ValueError(f"LegalChunkerV2: empty segment list for {filename}")

        documents = _build_norm_documents_from_segments(
            segments=segments,
            profile=profile,
            base_metadata=base_metadata,
            full_text=full_text,
            preseg_strategy=preseg_strategy,
            filename=filename,
        )
        if not documents:
            raise ValueError(f"LegalChunkerV2: norm layer is empty for {filename}")

        if pdf_text and not use_pdf_text_only and not _norm_documents_look_structured(documents):
            logger.info(
                "[LegalChunkerV2] PDF norm structure weak for %s — retry with PyMuPDF text extract",
                filename,
            )
            segments2, full_text2, preseg2, profile2 = _collect_legal_segments(
                content_bytes=None,
                filename=filename,
                doc_type=doc_type or "legal_reference",
                case_id=case_id or "GLOBAL_LEGAL_CORPUS",
                fallback_text=pdf_text,
                loader_did_ocr=False,
                loader_native_text=False,
                loader_documents=None,
            )
            if segments2:
                documents2 = _build_norm_documents_from_segments(
                    segments=segments2,
                    profile=profile2,
                    base_metadata=base_metadata,
                    full_text=full_text2,
                    preseg_strategy=preseg2,
                    filename=filename,
                )
                if documents2 and (
                    _norm_documents_look_structured(documents2)
                    or len(documents2) > len(documents)
                ):
                    documents = documents2

        _apply_hidden_embedding_context(
            documents,
            enabled=bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True)),
        )
        return documents


# --- Docling AST pre-segmentation -----------------------------------------

def _file_ext(filename: str) -> str:
    if not filename:
        return ""
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _build_docling_converter(ext: str, *, do_ocr: bool = True):
    """Возвращает process-wide кэшированный DocumentConverter (PDF + прочие форматы)."""
    from app.services.document_converter_service import DocumentConverterService

    return DocumentConverterService.get_cached_converter(ext, do_ocr=do_ocr)


def _extract_page_sizes_from_doc(doc: Any) -> Dict[int, Dict[str, float]]:
    """Extract {page_no: {width, height}} from DoclingDocument.pages."""
    page_sizes: Dict[int, Dict[str, float]] = {}
    try:
        pages = getattr(doc, "pages", None)
        if isinstance(pages, dict):
            for page_no, page_item in pages.items():
                size = getattr(page_item, "size", None)
                if size is not None:
                    w = getattr(size, "width", None)
                    h = getattr(size, "height", None)
                    if w is not None and h is not None:
                        page_sizes[int(page_no)] = {"width": float(w), "height": float(h)}
                        continue
                geom = getattr(page_item, "geometry", None) or getattr(page_item, "page_geometry", None)
                if geom is not None:
                    w = getattr(geom, "width", None)
                    h = getattr(geom, "height", None)
                    if w is not None and h is not None:
                        page_sizes[int(page_no)] = {"width": float(w), "height": float(h)}
    except Exception:
        pass
    return page_sizes


def _convert_docling_bytes_to_segments(
    *,
    converter: Any,
    content_bytes: bytes,
    filename: str,
    ext: str,
    max_pages: int,
    max_size: int,
) -> List[_Segment]:
    """One Docling convert() → flat segments. Caller holds docling_slot."""
    try:
        from docling.datamodel.base_models import DocumentStream
    except Exception as exc:
        logger.debug("[LegalChunkerV2] docling not importable: %s", exc)
        return []

    source = DocumentStream(name=filename or "input", stream=BytesIO(content_bytes))
    try:
        try:
            result = converter.convert(
                source=source, max_num_pages=max_pages, max_file_size=max_size
            )
        except TypeError:
            result = converter.convert(source=source)

        doc = getattr(result, "document", None)
        if doc is None:
            return []

        page_sizes = _extract_page_sizes_from_doc(doc)
        return list(
            _iter_docling_segments(
                doc,
                page_sizes=page_sizes,
                pdf_bytes=content_bytes if ext == ".pdf" else None,
            )
        )
    finally:
        source.stream.close()


def _docling_pre_segmentation(
    content_bytes: bytes, filename: str, ext: str, *, do_ocr: bool = True
) -> Tuple[List[_Segment], str]:
    """Парсит документ через Docling и собирает плоский список AST-сегментов.

    Large PDFs are converted in page windows (see DOCLING_PDF_BATCH_*) so a
    weak VM never loads a 500-page DoclingDocument in one shot.
    """

    converter = _build_docling_converter(ext, do_ocr=do_ocr)
    if ext == ".pdf" and not do_ocr:
        logger.info(
            "[LegalChunkerV2] Docling PDF parse without OCR (native text layer): %s",
            filename,
        )
    if converter is None:
        return [], ""

    max_pages = max(1, int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 2000) or 2000))
    max_size = max(
        1,
        int(getattr(config, "DOCLING_MAX_FILE_SIZE_BYTES", 60 * 1024 * 1024) or 60 * 1024 * 1024),
    )

    from app.services.docling_page_batch import (
        convert_pdf_in_page_batches,
        pdf_page_count,
        should_batch_pdf,
    )
    from app.services.file_processing_concurrency import docling_slot
    from app.services.ingest_progress import IngestProgress, report_ingest_progress

    batch_enabled = bool(getattr(config, "DOCLING_PDF_BATCH_ENABLED", True))
    batch_pages = max(1, int(getattr(config, "DOCLING_PDF_BATCH_PAGES", 30) or 30))
    batch_min_pages = max(2, int(getattr(config, "DOCLING_PDF_BATCH_MIN_PAGES", 40) or 40))

    def _one_shot() -> List[_Segment]:
        return _convert_docling_bytes_to_segments(
            converter=converter,
            content_bytes=content_bytes,
            filename=filename,
            ext=ext,
            max_pages=max_pages,
            max_size=max_size,
        )

    try:
        with docling_slot():
            if ext == ".pdf":
                total_pages = pdf_page_count(content_bytes)
                if total_pages > max_pages:
                    logger.warning(
                        "[LegalChunkerV2] PDF %s has %s pages; capping to DOCLING_MAX_PAGES_PER_DOC=%s",
                        filename,
                        total_pages,
                        max_pages,
                    )
                    # Page batching respects max_pages via truncated byte extract below.
                    content_for_convert = content_bytes
                    try:
                        from app.services.docling_page_batch import extract_pdf_page_range_bytes

                        content_for_convert = extract_pdf_page_range_bytes(
                            content_bytes, 0, max_pages
                        )
                        total_pages = max_pages
                    except Exception as cap_exc:
                        logger.warning(
                            "[LegalChunkerV2] could not truncate PDF to max_pages: %s",
                            cap_exc,
                        )
                        content_for_convert = content_bytes
                else:
                    content_for_convert = content_bytes

                if should_batch_pdf(
                    total_pages=total_pages,
                    min_pages=batch_min_pages,
                    enabled=batch_enabled,
                ):
                    logger.info(
                        "[LegalChunkerV2] page-batched Docling for %s (%s pages, batch=%s)",
                        filename,
                        total_pages,
                        batch_pages,
                    )
                    report_ingest_progress(
                        IngestProgress(
                            stage="docling",
                            percent=35,
                            message=f"Структурный разбор PDF ({total_pages} стр.)",
                            pages_done=0,
                            pages_total=total_pages,
                        )
                    )

                    def _convert_batch(batch_bytes: bytes, batch_name: str) -> Tuple[List[_Segment], str]:
                        segs = _convert_docling_bytes_to_segments(
                            converter=converter,
                            content_bytes=batch_bytes,
                            filename=batch_name,
                            ext=ext,
                            # Each window is small; allow full window through Docling limits.
                            max_pages=max(batch_pages + 5, 50),
                            max_size=max_size,
                        )
                        return segs, ""

                    def _on_batch_done(batch: Any, batch_i: int, batch_n: int) -> None:
                        pages_done = int(getattr(batch, "end", 0) or 0)
                        pct = 35 + int(50 * (batch_i / max(1, batch_n)))
                        report_ingest_progress(
                            IngestProgress(
                                stage="docling",
                                percent=min(85, pct),
                                message=f"Docling: страницы {getattr(batch, 'label', '?')} ({batch_i}/{batch_n})",
                                pages_done=pages_done,
                                pages_total=total_pages,
                                batch_index=batch_i,
                                batch_count=batch_n,
                            )
                        )

                    segments, _ = convert_pdf_in_page_batches(
                        pdf_bytes=content_for_convert,
                        filename=filename,
                        batch_pages=batch_pages,
                        convert_batch=_convert_batch,
                        on_batch_done=_on_batch_done,
                    )
                    if segments:
                        segments = _renumber_segment_offsets(list(segments))
                else:
                    report_ingest_progress(
                        IngestProgress(
                            stage="docling",
                            percent=40,
                            message="Структурный разбор документа",
                            pages_total=total_pages or None,
                        )
                    )
                    segments = _convert_docling_bytes_to_segments(
                        converter=converter,
                        content_bytes=content_for_convert,
                        filename=filename,
                        ext=ext,
                        max_pages=max_pages,
                        max_size=max_size,
                    )
            else:
                report_ingest_progress(
                    IngestProgress(
                        stage="docling",
                        percent=40,
                        message="Структурный разбор документа",
                    )
                )
                segments = _one_shot()
    except Exception as exc:
        logger.warning("[LegalChunkerV2] Docling convert() failed for %s: %s", filename, exc)
        return [], ""

    if not segments:
        return [], ""

    full_text = _join_segments_text(segments)
    return segments, full_text


def _iter_docling_segments(
    doc: Any,
    *,
    page_sizes: Optional[Dict[int, Dict[str, float]]] = None,
    pdf_bytes: Optional[bytes] = None,
) -> Iterable[_Segment]:
    """Обходим DoclingDocument, собирая heading/paragraph/list/table в _Segment.

    char_start/char_end заполняем последовательно по порядку обхода.
    For PDF tables, prefer geometry-refined markdown over lossy export_to_markdown.
    """
    try:
        from docling_core.types.doc.document import (
            CodeItem,
            ListItem,
            SectionHeaderItem,
            TableItem,
            TextItem,
            TitleItem,
        )
    except Exception as exc:
        logger.warning("[LegalChunkerV2] cannot import docling item types: %s", exc)
        return

    parent_stack: List[Tuple[int, str]] = []
    current_section_title: str = ""
    current_section_number: str = ""

    offset = 0

    try:
        items_iter = doc.iterate_items(with_groups=False, traverse_pictures=False)
    except Exception as exc:
        logger.warning("[LegalChunkerV2] iterate_items failed: %s", exc)
        return

    for item, _level in items_iter:
        text = ""
        page_no: Optional[int] = None
        is_heading = False
        item_prov_dicts: List[Dict[str, Any]] = []

        try:
            prov = getattr(item, "prov", None) or []
            if prov:
                page_no = getattr(prov[0], "page_no", None)
                for prov_entry in prov:
                    prov_dict: Dict[str, Any] = {}
                    p_page = getattr(prov_entry, "page_no", None)
                    if p_page is not None:
                        prov_dict["page_no"] = int(p_page)
                    p_bbox = getattr(prov_entry, "bbox", None)
                    if p_bbox is not None:
                        bbox_dict: Dict[str, Any] = {}
                        for coord in ("l", "t", "r", "b"):
                            val = getattr(p_bbox, coord, None)
                            if val is not None:
                                bbox_dict[coord] = float(val)
                        if len(bbox_dict) == 4:
                            prov_dict["bbox"] = bbox_dict
                    if prov_dict:
                        item_prov_dicts.append(prov_dict)
        except Exception:
            page_no = None

        seg_page_bbox: Optional[Dict[str, float]] = None
        if page_sizes and page_no is not None:
            seg_page_bbox = page_sizes.get(int(page_no))

        if isinstance(item, (SectionHeaderItem, TitleItem)):
            text = _clean_text(getattr(item, "text", "") or "")
            if not text:
                continue
            is_heading = True
            level = int(getattr(item, "level", 1) or 1)
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            parent_stack.append((level, text))
            current_section_title = text
            current_section_number = _extract_section_number(text)

        elif isinstance(item, ListItem):
            inner = _clean_text(getattr(item, "text", "") or "")
            if not inner:
                continue
            marker = (getattr(item, "marker", "") or "").strip()
            text = f"{marker} {inner}".strip() if marker else inner

        elif isinstance(item, TableItem):
            md = export_table_item_markdown(
                item,
                doc=doc,
                pdf_bytes=pdf_bytes,
                page_no=int(page_no) if page_no is not None else None,
            )
            text = _clean_text(md or "")

        elif isinstance(item, CodeItem):
            text = _clean_text(getattr(item, "text", "") or "")

        elif isinstance(item, TextItem):
            text = _clean_text(getattr(item, "text", "") or "")

        else:
            continue

        if not text:
            continue

        article_line = _first_line(text)
        if _ARTICLE_HEADING_NUM_RE.match(article_line):
            current_section_title = article_line
            current_section_number = _article_number_from_heading(article_line)

        segment_text = text + "\n\n"
        char_start = offset
        char_end = char_start + len(segment_text)
        offset = char_end

        yield _Segment(
            text=segment_text,
            section_title=current_section_title,
            section_number=current_section_number,
            parent_path=[t for _l, t in parent_stack],
            page_no=page_no,
            char_start=char_start,
            char_end=char_end,
            is_heading=is_heading,
            is_table=isinstance(item, TableItem),
            prov_items=item_prov_dicts,
            page_bbox=seg_page_bbox,
        )


def _join_segments_text(segments: Sequence[_Segment]) -> str:
    return "".join(s.text for s in segments)


def _collect_legal_segments(
    *,
    content_bytes: Optional[bytes],
    filename: str,
    doc_type: Optional[str],
    case_id: Optional[str],
    fallback_text: Optional[str],
    loader_did_ocr: bool,
    loader_native_text: bool,
    loader_documents: Optional[List[Document]],
    apply_segment_normalization: bool = True,
) -> Tuple[List[_Segment], str, str, _Profile]:
    """Общий pre-segmentation pipeline для macro/micro и norm chunking."""
    profile = _select_profile(case_id=case_id, doc_type=doc_type)
    ext = _file_ext(filename)

    segments: List[_Segment] = []
    full_text = ""
    preseg_strategy = "text_recursive_legal"

    skip_docling = bool(loader_did_ocr)
    docling_do_ocr = not bool(loader_native_text)

    if not skip_docling and content_bytes and ext in _DOCLING_SUPPORTED_EXTS:
        try:
            segments, full_text = _docling_pre_segmentation(
                content_bytes, filename, ext, do_ocr=docling_do_ocr
            )
            if segments:
                preseg_strategy = (
                    "docling_ast_native_text" if loader_native_text else "docling_ast_first"
                )
        except Exception as exc:
            logger.warning(
                "[LegalChunkerV2] Docling pre-segmentation failed for %s: %s — using text fallback",
                filename,
                exc,
            )
            segments = []

    if not segments:
        text_for_fallback = fallback_text
        if not text_for_fallback and content_bytes:
            try:
                text_for_fallback = content_bytes.decode("utf-8", errors="ignore")
            except Exception:
                text_for_fallback = None
        if not text_for_fallback or not text_for_fallback.strip():
            raise ValueError(
                f"LegalChunkerV2: no text available for {filename}; "
                f"expected content_bytes (Docling) or fallback_text"
            )
        if skip_docling and loader_documents:
            segments, full_text = _yandex_loader_documents_segmentation(loader_documents)
            preseg_strategy = "ocr_markdown_recursive_legal"
        elif _looks_like_markdown(text_for_fallback):
            segments, full_text = _heading_aware_markdown_segmentation(text_for_fallback)
            preseg_strategy = (
                "ocr_markdown_recursive_legal" if skip_docling else "text_recursive_legal"
            )
        else:
            segments, full_text = _heading_aware_text_segmentation(text_for_fallback)
            preseg_strategy = (
                "ocr_text_recursive_legal" if skip_docling else "text_recursive_legal"
            )

    if not segments:
        return [], "", preseg_strategy, profile

    if apply_segment_normalization:
        segments = _normalize_docling_segments(list(segments), profile)
    full_text = _join_segments_text(segments)
    return segments, full_text, preseg_strategy, profile


def _renumber_segment_offsets(segments: List[_Segment]) -> List[_Segment]:
    """После шардирования AST-сегментов пересчитываем char_start/char_end последовательно."""
    offset = 0
    out: List[_Segment] = []
    for s in segments:
        t = s.text
        cs = offset
        ce = offset + len(t)
        offset = ce
        out.append(
            _Segment(
                text=t,
                section_title=s.section_title,
                section_number=s.section_number,
                parent_path=list(s.parent_path or []),
                page_no=s.page_no,
                char_start=cs,
                char_end=ce,
                is_heading=s.is_heading,
                is_table=s.is_table,
                is_table_fragment=s.is_table_fragment,
                table_shard_index=s.table_shard_index,
                prov_items=list(s.prov_items or []),
                page_bbox=s.page_bbox,
            )
        )
    return out


_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")


def _parse_markdown_pipe_table(md: str) -> Optional[Tuple[str, str, List[str]]]:
    """Возвращает (header_line, separator_line, data_lines) или None."""
    lines = [ln for ln in (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None
    header = lines[i].strip()
    if "|" not in header:
        return None
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return None
    sep = lines[j].strip()
    if "|" not in sep or not _MD_TABLE_SEP_RE.search(sep):
        return None
    data_lines = [lines[k] for k in range(j + 1, len(lines)) if lines[k].strip()]
    return header, sep, data_lines


def _shard_markdown_table_text(md: str, rows_per_group: int) -> List[str]:
    """Группы строк markdown-таблицы; каждая группа включает header + separator."""
    parsed = _parse_markdown_pipe_table(md)
    if not parsed:
        return []
    header, sep, data = parsed
    if not data:
        return [f"{header}\n{sep}\n".strip() + "\n"]
    rows_per_group = max(1, int(rows_per_group))
    out: List[str] = []
    for g in range(0, len(data), rows_per_group):
        chunk_lines = [header, sep] + data[g : g + rows_per_group]
        out.append("\n".join(chunk_lines).strip() + "\n")
    return out


def _split_oversized_segment_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except Exception as exc:
        logger.warning("[LegalChunkerV2] RecursiveCharacterTextSplitter unavailable: %s", exc)
        return [text]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max(400, int(chunk_size)),
        chunk_overlap=max(0, min(int(chunk_overlap), int(chunk_size) // 3)),
        length_function=len,
        separators=_LEGAL_SEPARATORS,
    )
    parts = splitter.split_text(text)
    return [p for p in parts if (p or "").strip()]


def _expand_table_segment(seg: _Segment, min_chars: int, rows_per_group: int, profile: _Profile) -> List[_Segment]:
    if len(seg.text) < min_chars:
        return [seg]
    shards = _shard_markdown_table_text(seg.text, rows_per_group)
    if not shards:
        max_seg = max(
            int(getattr(config, "LEGAL_SEGMENT_MAX_CHARS", 2200) or 2200),
            int(profile.macro_size),
        )
        return _expand_oversized_non_table_segment(seg, max_seg, int(profile.macro_overlap))
    if len(shards) <= 1:
        return [seg]
    logger.info(
        "table_shards filename_hint chars=%s shards=%s",
        len(seg.text),
        len(shards),
    )
    out: List[_Segment] = []
    for idx, body in enumerate(shards):
        out.append(
            _Segment(
                text=body if body.endswith("\n") else body + "\n",
                section_title=seg.section_title,
                section_number=seg.section_number,
                parent_path=list(seg.parent_path or []),
                page_no=seg.page_no,
                char_start=seg.char_start,
                char_end=seg.char_end,
                is_heading=False,
                is_table=True,
                is_table_fragment=True,
                table_shard_index=idx,
                prov_items=list(seg.prov_items or []),
                page_bbox=seg.page_bbox,
            )
        )
    return out


def _expand_oversized_non_table_segment(seg: _Segment, max_chars: int, overlap: int) -> List[_Segment]:
    if len(seg.text) <= max_chars:
        return [seg]
    pieces = _split_oversized_segment_text(seg.text, max_chars, overlap)
    if len(pieces) <= 1:
        return [seg]
    logger.info(
        "oversized_docling_segments chars=%s pieces=%s max_chars=%s",
        len(seg.text),
        len(pieces),
        max_chars,
    )
    out: List[_Segment] = []
    for body in pieces:
        t = (body or "").rstrip() + "\n\n"
        out.append(
            _Segment(
                text=t,
                section_title=seg.section_title,
                section_number=seg.section_number,
                parent_path=list(seg.parent_path or []),
                page_no=seg.page_no,
                char_start=seg.char_start,
                char_end=seg.char_end,
                is_heading=False,
                is_table=seg.is_table,
                is_table_fragment=seg.is_table_fragment,
                table_shard_index=seg.table_shard_index,
                prov_items=list(seg.prov_items or []),
                page_bbox=seg.page_bbox,
            )
        )
    return out


def _normalize_docling_segments(segments: List[_Segment], profile: _Profile) -> List[_Segment]:
    """
    Дробим монолитные Docling-узлы (таблицы / длинный текст) до macro-слоя.
    """
    max_seg = max(
        int(getattr(config, "LEGAL_SEGMENT_MAX_CHARS", 2200) or 2200),
        int(profile.macro_size),
    )
    table_min = int(getattr(config, "LEGAL_TABLE_SHARD_MIN_CHARS", 1500) or 1500)
    rows_pg = int(getattr(config, "LEGAL_TABLE_SHARD_ROWS_PER_GROUP", 8) or 8)
    overlap = int(profile.macro_overlap)

    expanded: List[_Segment] = []
    for seg in segments:
        if seg.is_table and len(seg.text) >= table_min:
            expanded.extend(_expand_table_segment(seg, table_min, rows_pg, profile))
        elif len(seg.text) > max_seg:
            expanded.extend(_expand_oversized_non_table_segment(seg, max_seg, overlap))
        else:
            expanded.append(seg)

    return _renumber_segment_offsets(expanded)


def _embedding_breadcrumb_prefix(parent_path: Sequence[str], section_title: str) -> str:
    parts: List[str] = [p for p in (parent_path or []) if (p or "").strip()]
    st = (section_title or "").strip()
    if st and st not in parts:
        parts.append(st)
    if not parts:
        return ""
    return " > ".join(parts)


def _apply_hidden_embedding_context(documents: List[Document], *, enabled: bool) -> None:
    """Мутирует metadata: embedding_text = префикс + page_content; page_content без изменений."""
    if not enabled or not documents:
        return
    for d in documents:
        md = dict(d.metadata or {})
        inst = str(md.get("instrument_short_name") or "").strip()
        path = _embedding_breadcrumb_prefix(
            md.get("parent_path") or [],
            str(md.get("section_title") or ""),
        )
        body = d.page_content or ""
        # Hidden context should reduce cross-instrument noise: include act short name when available.
        ctx_parts = []
        if inst:
            ctx_parts.append(inst)
        if path:
            ctx_parts.append(path)
        ctx = " > ".join([p for p in ctx_parts if p])
        syn = ""
        if bool(getattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", False)):
            iid = str(md.get("instrument_id") or "").strip().lower()
            hint = _EMBED_HINTS.get(iid, "")
            if hint:
                syn = f" | {hint}"
        if ctx and syn:
            md["embedding_text"] = f"[Контекст: {ctx}{syn}]\n{body}"
        elif ctx:
            md["embedding_text"] = f"[Контекст: {ctx}]\n{body}"
        elif syn:
            md["embedding_text"] = f"[Контекст:{syn}]\n{body}"
        else:
            md.pop("embedding_text", None)
        d.metadata = md


# --- Heading-aware fallback for plain text --------------------------------

_MD_HEAD_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+)$")


def _looks_like_markdown(text: str) -> bool:
    t = (text or "")[:8000]
    return bool(_MD_HEAD_RE.search(t)) or "|---" in t


def _yandex_loader_documents_segmentation(
    loader_documents: List[Document],
) -> Tuple[List[_Segment], str]:
    """Build segments from per-page Yandex OCR blocks (bbox + page)."""
    from app.services.yandex_ocr_structured import YandexOcrBlock, yandex_blocks_to_prov_items

    segments: List[_Segment] = []
    full_parts: List[str] = []
    offset = 0
    parent_stack: List[Tuple[int, str]] = []

    for doc in loader_documents:
        meta = getattr(doc, "metadata", None) or {}
        page_idx = meta.get("source_page")
        try:
            page_1based = int(page_idx) + 1 if page_idx is not None else 1
        except (TypeError, ValueError):
            page_1based = 1
        page_bbox = meta.get("yandex_page_bbox") if isinstance(meta.get("yandex_page_bbox"), dict) else None
        blocks = meta.get("yandex_blocks") or []
        page_text = (meta.get("yandex_markdown") or doc.page_content or "").strip()
        if not page_text and not blocks:
            continue

        if blocks:
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btext = str(block.get("text") or "").strip()
                if not btext:
                    continue
                layout = str(block.get("layout_type") or "")
                is_heading = layout.upper().endswith("TITLE") or layout.upper().endswith("HEADER")
                if is_heading:
                    while parent_stack and parent_stack[-1][0] >= 2:
                        parent_stack.pop()
                    parent_stack.append((2, btext[:200]))
                segment_text = btext + "\n\n"
                char_start = offset
                char_end = char_start + len(segment_text)
                offset = char_end
                bbox = block.get("bbox") if isinstance(block.get("bbox"), dict) else None
                prov = []
                if bbox:
                    prov = yandex_blocks_to_prov_items(
                        [
                            YandexOcrBlock(
                                text=btext,
                                layout_type=layout,
                                bbox=bbox,
                                page_no_1based=page_1based,
                            )
                        ],
                        page_no_1based=page_1based,
                    )
                segments.append(
                    _Segment(
                        text=segment_text,
                        section_title=btext[:200] if is_heading else (parent_stack[-1][1] if parent_stack else ""),
                        section_number="",
                        parent_path=[t for _l, t in parent_stack],
                        page_no=page_1based,
                        char_start=char_start,
                        char_end=char_end,
                        is_heading=is_heading,
                        prov_items=prov or None,
                        page_bbox=page_bbox,
                    )
                )
                full_parts.append(segment_text)
        else:
            segment_text = page_text + "\n\n"
            char_start = offset
            char_end = char_start + len(segment_text)
            offset = char_end
            segments.append(
                _Segment(
                    text=segment_text,
                    section_title="",
                    section_number="",
                    parent_path=[t for _l, t in parent_stack],
                    page_no=page_1based,
                    char_start=char_start,
                    char_end=char_end,
                    prov_items=None,
                    page_bbox=page_bbox,
                )
            )
            full_parts.append(segment_text)

    return segments, "".join(full_parts)


def _heading_aware_markdown_segmentation(text: str) -> Tuple[List[_Segment], str]:
    """Segment markdown (# headers) + legal section patterns."""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return [], ""

    segments: List[_Segment] = []
    full_parts: List[str] = []
    parent_stack: List[Tuple[int, str]] = []
    current_section_title = ""
    current_section_number = ""
    offset = 0

    for line in cleaned.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        md_m = _MD_HEAD_RE.match(stripped)
        head_m = _SECTION_HEAD_RE.match(stripped) if not md_m else None
        is_heading = bool(md_m or head_m)
        if md_m:
            level = len(md_m.group("hashes") or "#")
            title = (md_m.group("title") or "").strip()
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            parent_stack.append((level, title))
            current_section_title = title
            current_section_number = ""
        elif head_m:
            kind = (head_m.group("kind") or "").strip()
            num = (head_m.group("num") or "").strip()
            level = _heading_level(kind)
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            parent_stack.append((level, stripped))
            current_section_title = stripped
            current_section_number = num

        segment_text = stripped + "\n"
        char_start = offset
        char_end = char_start + len(segment_text)
        offset = char_end
        segments.append(
            _Segment(
                text=segment_text,
                section_title=current_section_title,
                section_number=current_section_number,
                parent_path=[t for _l, t in parent_stack],
                page_no=None,
                char_start=char_start,
                char_end=char_end,
                is_heading=is_heading,
            )
        )
        full_parts.append(segment_text)

    return segments, "".join(full_parts)


def _heading_aware_text_segmentation(text: str) -> Tuple[List[_Segment], str]:
    """Грубое деление plain text по заголовкам Раздел/Глава/Статья/Пункт."""

    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return [], ""

    chunks_by_lines: List[List[str]] = []
    current: List[str] = []
    for line in cleaned.split("\n"):
        if _SECTION_HEAD_RE.match(line) and current:
            chunks_by_lines.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks_by_lines.append(current)

    full_text_parts: List[str] = []
    segments: List[_Segment] = []
    parent_stack: List[Tuple[int, str]] = []
    current_section_title = ""
    current_section_number = ""
    offset = 0

    for block_lines in chunks_by_lines:
        block_text = "\n".join(line for line in block_lines if line.strip())
        if not block_text.strip():
            continue
        head_match = _SECTION_HEAD_RE.match(block_lines[0]) if block_lines else None
        if head_match:
            kind = (head_match.group("kind") or "").strip()
            num = (head_match.group("num") or "").strip()
            level = _heading_level(kind)
            heading_line = block_lines[0].strip()
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            parent_stack.append((level, heading_line))
            current_section_title = heading_line
            current_section_number = num

        segment_text = block_text + "\n\n"
        char_start = offset
        char_end = char_start + len(segment_text)
        offset = char_end

        segments.append(
            _Segment(
                text=segment_text,
                section_title=current_section_title,
                section_number=current_section_number,
                parent_path=[t for _l, t in parent_stack],
                page_no=None,
                char_start=char_start,
                char_end=char_end,
                is_heading=bool(head_match),
            )
        )
        full_text_parts.append(segment_text)

    return segments, "".join(full_text_parts)


def _heading_level(kind: str) -> int:
    k = (kind or "").strip().lower()
    return {
        "часть": 1,
        "раздел": 2,
        "глава": 3,
        "параграф": 4,
        "§": 4,
        "статья": 5,
        "пункт": 6,
        "подпункт": 7,
        "приложение": 2,
    }.get(k, 5)


# --- Macro / micro layering -----------------------------------------------

def _build_macro_chunks(
    segments: Sequence[_Segment],
    profile: _Profile,
    base_metadata: Dict[str, Any],
) -> List[_MacroChunk]:
    """Склеиваем сегменты в macro-чанки по target size профиля."""

    target = max(400, int(profile.macro_size))
    overlap = max(0, int(profile.macro_overlap))

    macros: List[_MacroChunk] = []
    buffer: List[_Segment] = []
    buffer_chars = 0

    def flush(buf: List[_Segment]) -> None:
        if not buf:
            return
        text = "".join(s.text for s in buf).rstrip("\n") + "\n"
        if not text.strip():
            return

        first = buf[0]
        last = buf[-1]
        section_segment = next((s for s in buf if s.section_title), first)
        macro_index = len(macros)
        macro_id = _macro_id(base_metadata, macro_index, first.char_start)

        has_table_fragment = any(getattr(s, "is_table_fragment", False) for s in buf)

        from app.services.prov_span_utils import collect_prov_spans_from_segments, prov_items_for_char_span

        prov_spans = collect_prov_spans_from_segments(buf)
        macro_cs, macro_ce = first.char_start, last.char_end
        scoped_prov = prov_items_for_char_span(prov_spans, macro_cs, macro_ce)

        chunk_page_bbox: Optional[Dict[str, float]] = None
        for s in buf:
            if chunk_page_bbox is None and s.page_bbox:
                chunk_page_bbox = s.page_bbox

        macros.append(
            _MacroChunk(
                text=text,
                char_start=macro_cs,
                char_end=macro_ce,
                section_title=section_segment.section_title or "",
                section_number=section_segment.section_number or "",
                parent_path=list(section_segment.parent_path or []),
                page_start=first.page_no,
                page_end=last.page_no,
                macro_id=macro_id,
                macro_index=macro_index,
                has_table_fragment=bool(has_table_fragment),
                prov_items=scoped_prov,
                page_bbox=chunk_page_bbox,
                prov_spans=prov_spans,
            )
        )

    for seg in segments:
        seg_len = len(seg.text)

        if seg.is_heading and buffer_chars >= max(400, target // 2):
            flush(buffer)
            buffer = []
            buffer_chars = 0

        if buffer_chars + seg_len > target and buffer_chars > 0:
            flush(buffer)
            tail: List[_Segment] = []
            tail_chars = 0
            for prev in reversed(buffer):
                if tail_chars + len(prev.text) > overlap:
                    break
                tail.insert(0, prev)
                tail_chars += len(prev.text)
            buffer = list(tail)
            buffer_chars = tail_chars

        buffer.append(seg)
        buffer_chars += seg_len

    flush(buffer)
    return macros


def _build_micro_chunks(
    macros: Sequence[_MacroChunk],
    profile: _Profile,
    base_metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Делим каждый macro на micro-чанки RecursiveCharacterTextSplitter с legal-сепараторами."""

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except Exception as exc:
        logger.warning("[LegalChunkerV2] RecursiveCharacterTextSplitter unavailable: %s", exc)
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max(120, int(profile.micro_size)),
        chunk_overlap=max(0, int(profile.micro_overlap)),
        length_function=len,
        separators=_LEGAL_SEPARATORS,
    )

    from app.services.prov_span_utils import prov_items_for_char_span

    out: List[Dict[str, Any]] = []
    for macro in macros:
        try:
            pieces = splitter.split_text(macro.text)
        except Exception as exc:
            logger.debug("[LegalChunkerV2] split_text failed for macro %s: %s", macro.macro_id, exc)
            pieces = [macro.text]
        if not pieces:
            continue

        prov_spans = list(getattr(macro, "prov_spans", None) or [])

        cursor = 0
        for piece in pieces:
            piece_clean = (piece or "").strip()
            if not piece_clean:
                continue

            try:
                rel = macro.text.find(piece, cursor) if piece else -1
            except Exception:
                rel = -1
            if rel < 0:
                rel = cursor
            cursor = rel + len(piece)

            char_start = macro.char_start + rel
            char_end = char_start + len(piece)

            micro_prov = prov_items_for_char_span(prov_spans, char_start, char_end)

            out.append(
                {
                    "text": piece,
                    "char_start": char_start,
                    "char_end": char_end,
                    "section_title": macro.section_title,
                    "section_number": macro.section_number,
                    "parent_path": list(macro.parent_path),
                    "page_start": macro.page_start,
                    "page_end": macro.page_end,
                    "macro_id": macro.macro_id,
                    "is_table_fragment": bool(getattr(macro, "has_table_fragment", False)),
                    "prov_items": micro_prov,
                    "page_bbox": macro.page_bbox,
                }
            )
    return out


# --- Metadata builders -----------------------------------------------------

def _macro_id(base_metadata: Dict[str, Any], macro_index: int, char_start: int) -> str:
    doc_id = str(
        base_metadata.get("doc_id")
        or base_metadata.get("file_id")
        or base_metadata.get("source_file")
        or "doc"
    )
    raw = f"{doc_id}|macro|{macro_index}|{char_start}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    short = doc_id[:8] if len(doc_id) > 8 else doc_id
    return f"{short}_macro_{macro_index}_{digest}"


def _extract_section_number(title: str) -> str:
    if not title:
        return ""
    m = _SECTION_HEAD_RE.match(title)
    if not m:
        return ""
    return (m.group("num") or "").strip()


def _detect_clause_type(section_title: str, parent_path: Sequence[str], chunk_text: str) -> str:
    candidates = [section_title or "", *(parent_path or [])]
    for candidate in reversed(candidates):
        m = _SECTION_HEAD_RE.match(candidate or "")
        if m:
            kind = (m.group("kind") or "").strip().lower()
            mapped = _CLAUSE_KIND_MAP.get(kind)
            if mapped:
                return mapped

    head = (chunk_text or "").lstrip()[:64]
    m = _SECTION_HEAD_RE.match(head)
    if m:
        kind = (m.group("kind") or "").strip().lower()
        mapped = _CLAUSE_KIND_MAP.get(kind)
        if mapped:
            return mapped

    return "general"


def _extract_cross_references(text: str) -> List[str]:
    if not text:
        return []
    found: List[str] = []
    seen: set = set()
    for pattern in _CROSS_REF_PATTERNS:
        for match in pattern.finditer(text):
            ref = match.group(0).strip()
            if not ref:
                continue
            key = ref.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(ref)
            if len(found) >= 32:
                return found
    return found


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\x00", "")
    cleaned = re.sub(r"[ \t\u00a0]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_chunk_metadata(
    *,
    base_metadata: Dict[str, Any],
    profile: _Profile,
    full_text: str,
    preseg_strategy: str,
    level: str,
    section_title: str,
    section_number: str,
    parent_path: Sequence[str],
    page_start: Optional[int],
    page_end: Optional[int],
    char_start: int,
    char_end: int,
    chunk_text: str,
    chunk_index: int,
    macro_id: Optional[str],
    parent_macro_id: Optional[str],
    doc_id: str,
    filename: str,
    is_table_fragment: bool = False,
    prov_items: Optional[List[Dict[str, Any]]] = None,
    page_bbox: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    md: Dict[str, Any] = dict(base_metadata or {})
    md["source_file"] = filename
    md["doc_id"] = doc_id
    md["chunk_index"] = int(chunk_index)
    md["chunk_id"] = generate_chunk_id(str(doc_id), int(chunk_index), int(char_start))
    md["chunk_level"] = level
    md["chunk_profile"] = profile.name
    md["chunking_contract_version"] = LegalChunkerV2.contract_version
    md["preseg_strategy"] = preseg_strategy
    md["char_start"] = int(char_start)
    md["char_end"] = int(char_end)
    md["section_title"] = section_title or ""
    md["section_number"] = section_number or ""
    md["parent_path"] = list(parent_path or [])
    md["clause_type"] = _detect_clause_type(section_title, parent_path, chunk_text)
    md["cross_references"] = _extract_cross_references(chunk_text)
    md["macro_id"] = macro_id or ""
    md["parent_macro_id"] = parent_macro_id or ""
    md["is_table_fragment"] = bool(is_table_fragment)
    if page_start is not None:
        md["page_start"] = int(page_start)
    if page_end is not None:
        md["page_end"] = int(page_end)

    if prov_items:
        dl_meta: Dict[str, Any] = {
            "doc_items": [{"prov": prov_items}],
        }
        if page_bbox:
            dl_meta["page_bbox"] = page_bbox
        md["dl_meta"] = dl_meta

    return md


# --- Corpus norm (article/clause) chunking --------------------------------

# Только заголовок статьи («Статья 61. …»), не перекрёстные ссылки («статьями 61.2»).
_ARTICLE_HEADING_NUM_RE = re.compile(
    r"^\s*Статья\s+(?P<num>\d+(?:\.\d+)*)\s*(?:[.\u2014\-–]|$)",
    re.IGNORECASE,
)
_CLAUSE_BODY_SPLIT_RE = re.compile(
    r"(?=\n\s*(?:\d+[\.)]\s|Пункт\s+\d+|п\.\s*\d+))",
    re.IGNORECASE | re.MULTILINE,
)


def _norm_documents_look_structured(documents: Sequence[Document]) -> bool:
    """Есть ли в norm-чанках реальные заголовки статей (не только fallback 1,2,3)."""
    norm = [d for d in documents if (d.metadata or {}).get("chunk_level") == "norm"]
    if len(norm) < 2:
        return False
    article_like = 0
    for d in norm:
        title = str((d.metadata or {}).get("section_title") or "")
        head = ((d.page_content or "")[:160]).split("\n", 1)[0]
        if _ARTICLE_HEADING_NUM_RE.match(title.strip()) or _ARTICLE_HEADING_NUM_RE.match(head.strip()):
            article_like += 1
    return article_like >= 2


def _first_line(text: str) -> str:
    return ((text or "").lstrip().split("\n", 1)[0]).strip()


def _article_number_from_heading(text: str) -> str:
    line = _first_line(text)
    m = _ARTICLE_HEADING_NUM_RE.match(line)
    if not m:
        return ""
    return (m.group("num") or "").strip().replace(",", ".")


def _is_article_boundary_segment(seg: _Segment) -> bool:
    line = _first_line(seg.text or "")
    if line and _ARTICLE_HEADING_NUM_RE.match(line):
        return True
    if seg.is_heading:
        title = (seg.section_title or line).strip()
        return bool(title and _ARTICLE_HEADING_NUM_RE.match(title))
    return False


def _article_number_from_segment_group(segments: Sequence[_Segment]) -> str:
    for seg in segments:
        if not _is_article_boundary_segment(seg):
            continue
        num = _article_number_from_heading(_first_line(seg.text or ""))
        if num:
            return num
        if seg.is_heading:
            num = _article_number_from_heading(seg.section_title or "")
            if num:
                return num
    return ""


def _split_oversized_article(text: str, max_chars: int) -> List[Tuple[str, str]]:
    """Разбивает длинную статью по пунктам; возвращает (text, clause_ref)."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return [(t, "")]
    parts = [p.strip() for p in _CLAUSE_BODY_SPLIT_RE.split(t) if p.strip()]
    if len(parts) <= 1:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=max_chars,
                chunk_overlap=0,
                separators=["\n\n", "\n", ". ", " "],
            )
            return [(p, str(i + 1)) for i, p in enumerate(splitter.split_text(t)) if p.strip()]
        except Exception:
            return [(t[:max_chars], ""), (t[max_chars:], "cont")]

    out: List[Tuple[str, str]] = []
    buf = ""
    clause_idx = 0
    for part in parts:
        if len(buf) + len(part) + 2 > max_chars and buf:
            out.append((buf.strip(), str(clause_idx) if clause_idx else ""))
            buf = part
            clause_idx += 1
        else:
            buf = f"{buf}\n\n{part}".strip() if buf else part
    if buf.strip():
        out.append((buf.strip(), str(clause_idx) if clause_idx else ""))
    return out


def _group_segments_into_articles(segments: Sequence[_Segment]) -> List[List[_Segment]]:
    groups: List[List[_Segment]] = []
    current: List[_Segment] = []
    saw_article = False

    for seg in segments:
        if _is_article_boundary_segment(seg) and current:
            groups.append(current)
            current = [seg]
            saw_article = True
        else:
            if _is_article_boundary_segment(seg):
                saw_article = True
            current.append(seg)
    if current:
        groups.append(current)

    if saw_article:
        return groups

    # Fallback: один norm-чанк на каждый heading-сегмент или весь документ
    fallback_groups: List[List[_Segment]] = []
    buf: List[_Segment] = []
    for seg in segments:
        if seg.is_heading and buf:
            fallback_groups.append(buf)
            buf = [seg]
        else:
            buf.append(seg)
    if buf:
        fallback_groups.append(buf)
    return fallback_groups or [list(segments)]


def _build_norm_documents_from_segments(
    *,
    segments: Sequence[_Segment],
    profile: _Profile,
    base_metadata: Dict[str, Any],
    full_text: str,
    preseg_strategy: str,
    filename: str,
) -> List[Document]:
    from app.services.legal_norm_cross_ref import make_full_path, make_norm_node_key, normalize_article_number
    from app.services.legal_norm_structure import expand_article_to_clause_pieces

    max_article_chars = int(getattr(config, "LEGAL_CORPUS_NORM_MAX_ARTICLE_CHARS", 12000) or 12000)
    doc_id = str(base_metadata.get("doc_id") or base_metadata.get("file_id") or filename)
    instrument_id = str(base_metadata.get("instrument_id") or "unknown").strip().lower()
    instrument_short = str(base_metadata.get("instrument_short_name") or instrument_id)

    article_groups = _group_segments_into_articles(segments)
    documents: List[Document] = []
    chunk_index = 0
    fallback_article_idx = 0

    for group in article_groups:
        text = "".join(s.text for s in group).rstrip("\n") + "\n"
        if not text.strip():
            continue

        first = group[0]
        last = group[-1]
        boundary_seg = next((s for s in group if _is_article_boundary_segment(s)), first)
        boundary_line = _first_line(boundary_seg.text or "") or (boundary_seg.section_title or "").strip()
        section_title = boundary_line or boundary_seg.section_title or ""
        parent_path = list(boundary_seg.parent_path or [])
        article_number = _article_number_from_segment_group(group)
        if not article_number:
            fallback_article_idx += 1
            article_number = str(fallback_article_idx)

        article_number = normalize_article_number(article_number)
        full_path_base = make_full_path(instrument_short, parent_path, section_title)

        from app.services.prov_span_utils import collect_prov_spans_from_segments, prov_items_for_char_span

        prov_spans = collect_prov_spans_from_segments(group)
        char_start = first.char_start
        char_end = last.char_end
        scoped_prov = prov_items_for_char_span(prov_spans, char_start, char_end)
        page_start = first.page_no
        page_end = last.page_no
        page_bbox = next((s.page_bbox for s in group if s.page_bbox), None)

        pieces_raw = expand_article_to_clause_pieces(text, max_chars=max_article_chars)
        pieces = [(p.text, p.clause_ref) for p in pieces_raw]
        piece_offset = char_start
        for piece_text, clause_ref in pieces:
            if not piece_text.strip():
                continue
            norm_unit = "clause" if clause_ref else "article"
            norm_key = make_norm_node_key(
                instrument_id,
                article_number,
                clause_ref=clause_ref,
            )
            fp = full_path_base
            if clause_ref:
                fp = f"{fp} > п. {clause_ref}" if fp else f"п. {clause_ref}"

            md = _build_chunk_metadata(
                base_metadata=base_metadata,
                profile=profile,
                full_text=full_text,
                preseg_strategy=preseg_strategy,
                level="norm",
                section_title=section_title,
                section_number=article_number,
                parent_path=parent_path,
                page_start=page_start,
                page_end=page_end,
                char_start=piece_offset,
                char_end=piece_offset + len(piece_text),
                chunk_text=piece_text,
                chunk_index=chunk_index,
                macro_id=None,
                parent_macro_id=None,
                doc_id=doc_id,
                filename=filename,
                is_table_fragment=any(getattr(s, "is_table_fragment", False) for s in group),
                prov_items=scoped_prov or None,
                page_bbox=page_bbox,
            )
            md["norm_unit"] = norm_unit
            md["article_number"] = article_number
            md["clause_ref"] = clause_ref or ""
            md["full_path"] = fp
            md["norm_node_key"] = norm_key
            md["chunking_contract_version"] = "corpus-norm-v1"
            documents.append(Document(page_content=piece_text, metadata=md))
            chunk_index += 1
            piece_offset += len(piece_text)

    return documents


__all__ = ["LegalChunkerV2"]
