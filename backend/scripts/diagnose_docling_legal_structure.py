#!/usr/bin/env python3
"""Диагностика Docling AST для кодекса: какие статьи видны как заголовки vs обычный текст.

Примеры:
    cd backend && python -m scripts.diagnose_docling_legal_structure
    cd backend && python -m scripts.diagnose_docling_legal_structure --pdf /path/to/127-FZ-full.pdf
    cd backend && python -m scripts.diagnose_docling_legal_structure --article-range 54 62
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_ARTICLE_HEAD_RE = re.compile(
    r"^\s*статья\s+([0-9]{1,5}(?:\.[0-9]{1,3})?)",
    re.IGNORECASE,
)
_ARTICLE_ANYWHERE_RE = re.compile(
    r"(?:ст\.?|статья)\s+([0-9]{1,5}(?:\.[0-9]{1,3})?)",
    re.IGNORECASE,
)


def _load_pdf_bytes(*, pdf_path: Optional[Path], db_filename: str) -> Tuple[bytes, str]:
    if pdf_path is not None:
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF не найден: {pdf_path}")
        return pdf_path.read_bytes(), pdf_path.name

    from sqlalchemy import create_engine, text

    from app.config import config

    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, file_content, filename
                FROM legal_corpus_files
                WHERE filename = :fn
                ORDER BY created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"fn": db_filename},
        ).fetchone()
        if row is None:
            raise FileNotFoundError(
                f"В legal_corpus_files нет файла {db_filename!r}; укажите --pdf"
            )
        content = row.file_content
        if not content:
            raise ValueError(f"file_content пуст для {db_filename}")
        return bytes(content), str(row.filename or db_filename)


def _convert_docling(
    pdf_bytes: bytes, filename: str, *, do_ocr: bool, max_pages: int = 0
) -> Any:
    from docling.datamodel.base_models import DocumentStream

    from app.services.document_converter_service import DocumentConverterService

    converter = DocumentConverterService.get_cached_converter(".pdf", do_ocr=do_ocr)
    if converter is None:
        raise RuntimeError("Docling converter недоступен")

    from app.config import config

    max_pages_cfg = max(1, int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 2000) or 2000))
    max_pages_eff = min(max_pages_cfg, max_pages) if max_pages > 0 else max_pages_cfg
    max_size = max(
        1,
        int(getattr(config, "DOCLING_MAX_FILE_SIZE_BYTES", 60 * 1024 * 1024) or 60 * 1024 * 1024),
    )
    source = DocumentStream(name=filename, stream=BytesIO(pdf_bytes))
    try:
        try:
            result = converter.convert(
                source=source, max_num_pages=max_pages_eff, max_file_size=max_size
            )
        except TypeError:
            result = converter.convert(source=source)
    finally:
        source.stream.close()

    doc = getattr(result, "document", None)
    if doc is None:
        raise RuntimeError("Docling convert() не вернул document")
    return doc


def _item_type_name(item: Any) -> str:
    return type(item).__name__


def _is_docling_heading(item: Any) -> bool:
    try:
        from docling_core.types.doc.document import SectionHeaderItem, TitleItem

        return isinstance(item, (SectionHeaderItem, TitleItem))
    except Exception:
        return False


def _item_text(item: Any) -> str:
    raw = getattr(item, "text", None)
    if raw is None and hasattr(item, "export_to_markdown"):
        try:
            raw = item.export_to_markdown()
        except Exception:
            raw = ""
    return (str(raw or "")).strip().replace("\n", " ")


def _article_at_start(text: str) -> Optional[str]:
    m = _ARTICLE_HEAD_RE.match((text or "").strip())
    return m.group(1) if m else None


def _iter_flat_items(doc: Any, *, with_groups: bool) -> Iterable[Tuple[Any, int]]:
    try:
        for item, level in doc.iterate_items(with_groups=with_groups, traverse_pictures=False):
            yield item, int(level or 0)
    except TypeError:
        for item, level in doc.iterate_items():
            yield item, int(level or 0)


def _analyze_ast(
    doc: Any,
    *,
    with_groups: bool,
    article_lo: int,
    article_hi: int,
) -> None:
    type_counts: Counter[str] = Counter()
    article_heading_items: List[Tuple[str, str, int]] = []
    article_textitem_start: List[Tuple[str, str, int]] = []
    article_inside_text: List[Tuple[str, str, int, str]] = []

    for idx, (item, level) in enumerate(_iter_flat_items(doc, with_groups=with_groups)):
        tname = _item_type_name(item)
        type_counts[tname] += 1
        text = _item_text(item)
        if not text:
            continue

        art_start = _article_at_start(text)
        is_heading = _is_docling_heading(item)

        if art_start is not None:
            root = art_start.split(".")[0]
            try:
                root_n = int(root)
            except ValueError:
                root_n = -1
            if article_lo <= root_n <= article_hi or (
                art_start.replace(",", ".").startswith(f"{article_lo}.")
            ):
                preview = text[:100]
                if is_heading:
                    article_heading_items.append((art_start, tname, idx))
                elif tname == "TextItem":
                    article_textitem_start.append((art_start, tname, idx))
                print(f"  [{'H' if is_heading else 'T'}] #{idx} level={level} {tname} art={art_start}")
                print(f"       {preview}...")

        elif tname == "TextItem":
            for m in _ARTICLE_ANYWHERE_RE.finditer(text):
                art = m.group(1)
                root = art.split(".")[0]
                try:
                    root_n = int(root)
                except ValueError:
                    continue
                if article_lo <= root_n <= article_hi and m.start() > 0:
                    snippet = text[max(0, m.start() - 20) : m.start() + 60]
                    article_inside_text.append((art, tname, idx, snippet))
                    break

    print("\n--- Сводка типов AST ---")
    for name, cnt in type_counts.most_common(12):
        print(f"  {name}: {cnt}")

    print("\n--- Статьи в диапазоне: начало блока ---")
    print(f"  SectionHeader/Title (заголовок Docling): {len(article_heading_items)}")
    print(f"  TextItem начинается со «Статья N»: {len(article_textitem_start)}")
    print(f"  TextItem со «Статья N» внутри (не в начале): {len(article_inside_text)}")

    if article_inside_text[:8]:
        print("\n--- Примеры «Статья N» внутри TextItem (склейка) ---")
        for art, tname, idx, snippet in article_inside_text[:8]:
            print(f"  art={art} #{idx} {tname}: …{snippet.replace(chr(10), ' ')}…")


def _analyze_markdown(doc: Any, article_lo: int, article_hi: int) -> None:
    exporter = getattr(doc, "export_to_markdown", None)
    if not callable(exporter):
        print("\n--- Markdown export: недоступен ---")
        return
    try:
        md = exporter() or ""
    except Exception as exc:
        print(f"\n--- Markdown export failed: {exc} ---")
        return

    lines = md.splitlines()
    header_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        low = stripped.lower()
        if "статья" not in low and "ст." not in low:
            continue
        m = _ARTICLE_ANYWHERE_RE.search(stripped)
        if not m:
            continue
        art = m.group(1)
        root = art.split(".")[0]
        try:
            if article_lo <= int(root) <= article_hi:
                header_lines.append(stripped[:120])
        except ValueError:
            pass

    print(f"\n--- Markdown: строки-заголовки (#) со «статья» в диапазоне {article_lo}-{article_hi} ---")
    print(f"  найдено: {len(header_lines)}")
    for line in header_lines[:15]:
        print(f"  {line}")


def _extract_pdf_page_range(pdf_bytes: bytes, page_from: int, page_to: int) -> bytes:
    """1-based inclusive page range."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        start = max(1, page_from)
        end = min(len(doc), page_to)
        out = fitz.open()
        out.insert_pdf(doc, from_page=start - 1, to_page=end - 1)
        return out.tobytes()
    finally:
        doc.close()


def _analyze_chunker_segments(
    segments: list,
    article_lo: int,
    article_hi: int,
) -> None:
    from app.services.legal_chunker import (
        _group_segments_into_articles,
        _is_article_boundary_segment,
        _normalize_docling_segments,
        _select_profile,
        GLOBAL_LEGAL_CORPUS_CASE_ID,
    )

    print(f"\n--- LegalChunker _iter_docling_segments: {len(segments)} сегментов ---")
    if not segments:
        print("  (пусто)")
        return

    profile = _select_profile(GLOBAL_LEGAL_CORPUS_CASE_ID, "legal_reference")
    norm = _normalize_docling_segments(list(segments), profile)
    print(f"  после _normalize_docling_segments: {len(norm)} сегментов")

    def _in_range(text: str) -> bool:
        m = _ARTICLE_HEAD_RE.match((text or "").strip())
        if not m:
            return False
        root = m.group(1).split(".")[0]
        try:
            return article_lo <= int(root) <= article_hi
        except ValueError:
            return False

    print(f"\n--- Сегменты (raw), начинающиеся со статьи {article_lo}-{article_hi} ---")
    for i, seg in enumerate(segments):
        head = (seg.text or "").lstrip()[:100].replace("\n", " ")
        if _in_range(seg.text or ""):
            b = _is_article_boundary_segment(seg)
            print(
                f"  raw[{i}] heading={seg.is_heading} boundary={b} "
                f"section_title={seg.section_title[:50]!r}…"
            )
            print(f"       {head}…")

    print(f"\n--- Сегменты (normalized) ---")
    for i, seg in enumerate(norm):
        head = (seg.text or "").lstrip()[:100].replace("\n", " ")
        if _in_range(seg.text or ""):
            b = _is_article_boundary_segment(seg)
            print(
                f"  norm[{i}] heading={seg.is_heading} boundary={b} "
                f"section_title={seg.section_title[:50]!r}…"
            )
            print(f"       {head}…")

    groups = _group_segments_into_articles(norm)
    print(f"\n--- _group_segments_into_articles: {len(groups)} групп ---")
    for gi, group in enumerate(groups):
        joined = "".join(s.text for s in group)
        start = joined.lstrip()[:90].replace("\n", " ")
        if _ARTICLE_ANYWHERE_RE.search(start):
            m = _ARTICLE_ANYWHERE_RE.search(start)
            art = m.group(1) if m else "?"
            root = art.split(".")[0]
            try:
                in_rng = article_lo <= int(root) <= article_hi
            except ValueError:
                in_rng = False
            if in_rng or any(
                _ARTICLE_ANYWHERE_RE.search(s.text or "")
                and article_lo
                <= int((_ARTICLE_ANYWHERE_RE.search(s.text or "") or m).group(1).split(".")[0])
                <= article_hi
                for s in group
            ):
                arts_in_group = set()
                for m2 in _ARTICLE_ANYWHERE_RE.finditer(joined[:8000]):
                    arts_in_group.add(m2.group(1))
                print(f"  group[{gi}] segs={len(group)} arts_in_first_8k={sorted(arts_in_group)[:12]}")
                print(f"    starts: {start}…")


def main() -> int:
    parser = argparse.ArgumentParser(description="Docling structure diagnostic for legal corpus PDF")
    parser.add_argument("--pdf", type=Path, default=None, help="Путь к PDF (иначе из legal_corpus_files)")
    parser.add_argument(
        "--db-filename",
        default="127-FZ-full.pdf",
        help="Имя файла в legal_corpus_files если --pdf не задан",
    )
    parser.add_argument("--article-lo", type=int, default=54)
    parser.add_argument("--article-hi", type=int, default=62)
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Также прогнать Docling с do_ocr=True (медленнее)",
    )
    parser.add_argument(
        "--pages",
        default="",
        help="Диапазон страниц PDF 1-based, напр. 70-78 (быстрый тест вокруг ст. 54–61)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Ограничить число страниц PDF с начала (0 = весь документ)",
    )
    args = parser.parse_args()

    try:
        pdf_bytes, filename = _load_pdf_bytes(pdf_path=args.pdf, db_filename=args.db_filename)
    except Exception as exc:
        print(f"Ошибка загрузки PDF: {exc}", file=sys.stderr)
        return 2

    if args.pages.strip():
        part = args.pages.replace(" ", "").split("-", 1)
        if len(part) != 2:
            print("Неверный --pages, ожидается FROM-TO", file=sys.stderr)
            return 2
        page_from, page_to = int(part[0]), int(part[1])
        pdf_bytes = _extract_pdf_page_range(pdf_bytes, page_from, page_to)
        filename = f"{filename}#pages{page_from}-{page_to}"
        print(f"=== Вырезка страниц {page_from}–{page_to} → {len(pdf_bytes)} bytes ===")

    print(f"=== Docling diagnostic: {filename} ({len(pdf_bytes)} bytes) ===")
    print(f"=== Диапазон статей: {args.article_lo}–{args.article_hi} ===\n")

    try:
        doc = _convert_docling(
            pdf_bytes, filename, do_ocr=False, max_pages=args.max_pages
        )
    except Exception as exc:
        print(f"Docling convert (native) FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    from app.services.legal_chunker import (
        _extract_page_sizes_from_doc,
        _iter_docling_segments,
    )

    page_sizes = _extract_page_sizes_from_doc(doc)
    chunker_segments = list(_iter_docling_segments(doc, page_sizes=page_sizes))

    print("=== AST flat (with_groups=False) — как в LegalChunker ===")
    _analyze_ast(
        doc,
        with_groups=False,
        article_lo=args.article_lo,
        article_hi=args.article_hi,
    )

    print("\n=== AST with_groups=True (иерархия Docling) ===")
    _analyze_ast(
        doc,
        with_groups=True,
        article_lo=args.article_lo,
        article_hi=args.article_hi,
    )

    _analyze_markdown(doc, args.article_lo, args.article_hi)
    _analyze_chunker_segments(chunker_segments, args.article_lo, args.article_hi)

    if args.ocr:
        print("\n\n########## do_ocr=True ##########")
        try:
            doc_ocr = _convert_docling(
                pdf_bytes, filename, do_ocr=True, max_pages=args.max_pages
            )
            _analyze_ast(
                doc_ocr,
                with_groups=False,
                article_lo=args.article_lo,
                article_hi=args.article_hi,
            )
        except Exception as exc:
            print(f"Docling OCR path failed: {exc}")

    print("\n=== Готово ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
