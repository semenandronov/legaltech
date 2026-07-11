"""Превью сырой структуры DoclingDocument для /docling-structure (без legal chunking)."""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.services.legal_chunker import _build_docling_converter, _extract_page_sizes_from_doc, _file_ext


def _item_type_name(item: Any) -> str:
    return type(item).__name__


def _is_docling_heading(item: Any) -> bool:
    try:
        from docling_core.types.doc.document import SectionHeaderItem, TitleItem

        return isinstance(item, (SectionHeaderItem, TitleItem))
    except Exception:
        return False


def _serialize_prov(item: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    prov = getattr(item, "prov", None) or []
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
            out.append(prov_dict)
    return out


def _extract_item_text(item: Any, doc: Any) -> str:
    try:
        from docling_core.types.doc.document import GroupItem, PictureItem, TableItem
    except Exception:
        GroupItem = PictureItem = TableItem = ()  # type: ignore[misc, assignment]

    if isinstance(item, GroupItem):
        name = (getattr(item, "name", None) or "").strip()
        label = getattr(item, "label", None)
        label_s = str(label) if label is not None else ""
        if name and label_s:
            return f"{name} ({label_s})"
        return name or label_s

    if isinstance(item, TableItem):
        try:
            return (item.export_to_markdown(doc=doc) or "").strip()
        except Exception:
            try:
                df = item.export_to_dataframe(doc=doc)
                return df.to_markdown(index=False).strip()
            except Exception:
                return ""

    if isinstance(item, PictureItem):
        meta = getattr(item, "meta", None)
        if meta is not None:
            desc = getattr(meta, "description", None)
            if desc:
                text = getattr(desc, "text", None) or str(desc)
                if str(text).strip():
                    return str(text).strip()
        return ""

    raw = getattr(item, "text", None)
    if raw is not None:
        return str(raw).strip()
    return ""


def _convert_docling_document(
    content_bytes: bytes,
    filename: str,
    ext: str,
    *,
    do_ocr: bool,
) -> Any:
    try:
        from docling.datamodel.base_models import DocumentStream
    except Exception as exc:
        raise ValueError(f"Docling недоступен: {exc}") from exc

    converter = _build_docling_converter(ext, do_ocr=do_ocr)
    if converter is None:
        raise ValueError("Docling converter недоступен для этого формата")

    max_pages = max(1, int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 2000) or 2000))
    max_size = max(
        1,
        int(getattr(config, "DOCLING_MAX_FILE_SIZE_BYTES", 60 * 1024 * 1024) or 60 * 1024 * 1024),
    )

    from app.services.file_processing_concurrency import docling_slot

    source = DocumentStream(name=filename or "input", stream=BytesIO(content_bytes))
    try:
        with docling_slot():
            try:
                result = converter.convert(
                    source=source, max_num_pages=max_pages, max_file_size=max_size
                )
            except TypeError:
                result = converter.convert(source=source)
    finally:
        source.stream.close()

    doc = getattr(result, "document", None)
    if doc is None:
        raise ValueError("Docling convert() не вернул document")
    return doc


def _iter_raw_docling_items(doc: Any) -> List[Tuple[Any, int]]:
    items: List[Tuple[Any, int]] = []
    try:
        iterator = doc.iterate_items(with_groups=True, traverse_pictures=True)
    except TypeError:
        iterator = doc.iterate_items()
    for item, level in iterator:
        items.append((item, int(level or 0)))
    return items


def _item_to_dict(item: Any, doc: Any, index: int, level: int) -> Dict[str, Any]:
    text = _extract_item_text(item, doc)
    prov = _serialize_prov(item)
    page_no = prov[0]["page_no"] if prov and prov[0].get("page_no") is not None else None

    row: Dict[str, Any] = {
        "index": index,
        "level": level,
        "type": _item_type_name(item),
        "is_heading": _is_docling_heading(item),
        "chars": len(text),
        "text": text,
        "text_preview": text[:400],
        "page_no": page_no,
        "prov": prov,
    }

    label = getattr(item, "label", None)
    if label is not None:
        row["label"] = str(label)

    marker = getattr(item, "marker", None)
    if marker:
        row["marker"] = str(marker).strip()

    enumerated = getattr(item, "enumerated", None)
    if enumerated is not None:
        row["enumerated"] = bool(enumerated)

    name = getattr(item, "name", None)
    if name and str(name).strip():
        row["name"] = str(name).strip()

    return row


def preview_docling_structure(
    content: bytes,
    filename: str,
    *,
    do_ocr: bool = True,
    native_text: bool = False,
    max_items: int = 500,
) -> Dict[str, Any]:
    """
    Сырая структура DoclingDocument: iterate_items без legal-нормализации и chunking.
    """
    safe_name = (filename or "document.pdf").replace("\\", "/").split("/")[-1] or "document.pdf"
    ext = _file_ext(safe_name)
    if ext not in {".pdf", ".docx", ".html", ".htm", ".md", ".pptx"}:
        raise ValueError(f"Формат {ext or '(нет)'} не поддерживается Docling в этом превью")

    docling_ocr = do_ocr and not native_text
    doc = _convert_docling_document(
        content,
        safe_name,
        ext,
        do_ocr=docling_ocr,
    )

    raw_pairs = _iter_raw_docling_items(doc)
    type_counts: Counter[str] = Counter()
    for item, _level in raw_pairs:
        type_counts[_item_type_name(item)] += 1

    cap = max(1, min(int(max_items or 500), 5000))
    item_rows = [
        _item_to_dict(item, doc, i, level)
        for i, (item, level) in enumerate(raw_pairs[:cap])
    ]

    page_sizes = _extract_page_sizes_from_doc(doc)
    pages = [
        {"page_no": page_no, **size}
        for page_no, size in sorted(page_sizes.items(), key=lambda x: x[0])
    ]

    export_md_chars = 0
    try:
        export_md_chars = len((doc.export_to_markdown() or "").strip())
    except Exception:
        pass

    return {
        "filename": safe_name,
        "extension": ext,
        "content_bytes": len(content or b""),
        "docling_ocr": docling_ocr,
        "native_text": bool(native_text),
        "pages": pages,
        "type_counts": dict(type_counts),
        "items_total": len(raw_pairs),
        "items_returned": len(item_rows),
        "items_truncated": len(raw_pairs) > cap,
        "export_markdown_chars": export_md_chars,
        "items": item_rows,
    }
