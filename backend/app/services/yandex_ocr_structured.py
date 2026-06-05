"""Structured parsing for Yandex Cloud OCR (new API) — blocks, bbox, page text."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class YandexOcrBlock:
    text: str
    layout_type: str = ""
    bbox: Optional[Dict[str, float]] = None
    page_no_1based: Optional[int] = None


@dataclass
class YandexOcrPage:
    page_index: int
    page_text: str
    markdown: str = ""
    blocks: List[YandexOcrBlock] = field(default_factory=list)
    page_bbox: Optional[Dict[str, float]] = None


def pick_yandex_ocr_model(
    filename: str,
    *,
    scan_model: str = "page",
    table_model: str = "page",
    pdf_async_model: str | None = None,
) -> str:
    """PDF OCR: единственная модель — page (recognizeTextAsync, гайд Yandex)."""
    del filename, scan_model, table_model, pdf_async_model
    return "page"


def vertices_to_xyxy(
    vertices: Sequence[Dict[str, Any]],
    *,
    page_height: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """Polygon vertices (image/top-left) -> PDF user-space x0,y0,x1,y1 for UI overlay."""
    if not vertices:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for v in vertices:
        if not isinstance(v, dict):
            continue
        x = v.get("x")
        y = v.get("y")
        if x is None or y is None:
            continue
        try:
            xs.append(float(x))
            ys.append(float(y))
        except (TypeError, ValueError):
            continue
    if not xs or not ys:
        return None
    x0, x1 = min(xs), max(xs)
    y_top, y_bottom = min(ys), max(ys)
    if page_height and page_height > 0:
        ph = float(page_height)
        return {
            "x0": x0,
            "y0": ph - y_bottom,
            "x1": x1,
            "y1": ph - y_top,
        }
    return {"x0": x0, "y0": y_top, "x1": x1, "y1": y_bottom}


def _bbox_from_block(block: Dict[str, Any], page_height: Optional[float]) -> Optional[Dict[str, float]]:
    bb = block.get("boundingBox") or block.get("bounding_box")
    if isinstance(bb, dict):
        verts = bb.get("vertices") or bb.get("vertexes")
        if isinstance(verts, list) and verts:
            return vertices_to_xyxy(verts, page_height=page_height)
    verts = block.get("vertices")
    if isinstance(verts, list) and verts:
        return vertices_to_xyxy(verts, page_height=page_height)
    return None


def _block_text(block: Dict[str, Any]) -> str:
    md = block.get("markdown")
    if isinstance(md, str) and md.strip():
        return md.strip()
    lines_out: List[str] = []
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        t = line.get("text") or ""
        if not t and line.get("words"):
            parts = []
            for w in line.get("words") or []:
                if isinstance(w, dict) and w.get("text"):
                    parts.append(str(w["text"]))
            t = " ".join(parts)
        if t:
            lines_out.append(str(t).strip())
    return "\n".join(lines_out).strip()


def _page_dimensions(ta: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    for key in ("width", "pageWidth", "page_width"):
        w = ta.get(key)
        if w is not None:
            try:
                width = float(w)
                break
            except (TypeError, ValueError):
                width = None
    else:
        width = None
    for key in ("height", "pageHeight", "page_height"):
        h = ta.get(key)
        if h is not None:
            try:
                height = float(h)
                break
            except (TypeError, ValueError):
                height = None
    else:
        height = None
    return width, height


def parse_text_annotation(
    ta: Dict[str, Any],
    *,
    page_index: int,
    page_no_1based: Optional[int] = None,
) -> YandexOcrPage:
    """Parse one page textAnnotation from getRecognition."""
    if not isinstance(ta, dict):
        return YandexOcrPage(page_index=page_index, page_text="")

    width, height = _page_dimensions(ta)
    page_bbox: Optional[Dict[str, float]] = None
    if width and height:
        page_bbox = {"width": width, "height": height}

    markdown = ""
    raw_md = ta.get("markdown")
    if isinstance(raw_md, str) and raw_md.strip():
        markdown = raw_md.strip()

    blocks: List[YandexOcrBlock] = []
    for block in ta.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        text = _block_text(block)
        if not text:
            continue
        layout = (
            block.get("layoutType")
            or block.get("layout_type")
            or block.get("type")
            or ""
        )
        bbox = _bbox_from_block(block, height)
        blocks.append(
            YandexOcrBlock(
                text=text,
                layout_type=str(layout),
                bbox=bbox,
                page_no_1based=page_no_1based,
            )
        )

    if markdown:
        page_text = markdown
    else:
        full_text = ta.get("fullText")
        if isinstance(full_text, str) and full_text.strip():
            page_text = full_text.strip()
        elif blocks:
            page_text = "\n\n".join(b.text for b in blocks if b.text)
        else:
            page_text = ""

    return YandexOcrPage(
        page_index=page_index,
        page_text=page_text,
        markdown=markdown or page_text,
        blocks=blocks,
        page_bbox=page_bbox,
    )


def yandex_blocks_to_prov_items(
    blocks: Sequence[YandexOcrBlock],
    *,
    page_no_1based: int,
) -> List[Dict[str, Any]]:
    """Build dl_meta-compatible prov list for LegalChunkerV2 / citations."""
    prov: List[Dict[str, Any]] = []
    for block in blocks:
        if not block.bbox:
            continue
        bb = block.bbox
        prov.append(
            {
                "page_no": page_no_1based,
                "bbox": {
                    "l": bb["x0"],
                    "t": bb["y1"],
                    "r": bb["x1"],
                    "b": bb["y0"],
                },
            }
        )
    return prov


def merge_pages_markdown(pages: Sequence[YandexOcrPage]) -> str:
    parts = []
    for p in sorted(pages, key=lambda x: x.page_index):
        t = (p.markdown or p.page_text or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


__all__ = [
    "YandexOcrBlock",
    "YandexOcrPage",
    "pick_yandex_ocr_model",
    "parse_text_annotation",
    "vertices_to_xyxy",
    "yandex_blocks_to_prov_items",
    "merge_pages_markdown",
]
