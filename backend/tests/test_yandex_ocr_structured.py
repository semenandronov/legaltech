"""Tests for Yandex OCR structured parser."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.yandex_ocr_structured import (
    parse_text_annotation,
    pick_yandex_ocr_model,
    vertices_to_xyxy,
    yandex_blocks_to_prov_items,
)

FIXTURE = Path(__file__).parent / "fixtures" / "yandex_ocr_sample_annotation.json"


def test_vertices_to_xyxy_pdf_space():
    verts = [
        {"x": 100, "y": 50},
        {"x": 300, "y": 50},
        {"x": 300, "y": 80},
        {"x": 100, "y": 80},
    ]
    box = vertices_to_xyxy(verts, page_height=842)
    assert box is not None
    assert box["x0"] == 100
    assert box["x1"] == 300
    assert box["y1"] > box["y0"]


def test_parse_sample_annotation():
    ta = json.loads(FIXTURE.read_text(encoding="utf-8"))
    page = parse_text_annotation(ta, page_index=0, page_no_1based=1)
    assert "Договор" in page.page_text
    assert page.markdown.startswith("#")
    assert len(page.blocks) == 2
    assert page.page_bbox == {"width": 595.0, "height": 842.0}
    assert page.blocks[0].bbox is not None


def test_pick_model_always_page():
    assert pick_yandex_ocr_model("реестр требований.pdf") == "page"
    assert pick_yandex_ocr_model("договор.pdf") == "page"
    assert pick_yandex_ocr_model("договор.pdf", pdf_async_model="page") == "page"


def test_yandex_blocks_to_prov():
    ta = json.loads(FIXTURE.read_text(encoding="utf-8"))
    page = parse_text_annotation(ta, page_index=0, page_no_1based=1)
    prov = yandex_blocks_to_prov_items(page.blocks, page_no_1based=1)
    assert len(prov) == 2
    assert prov[0]["page_no"] == 1
    assert "l" in prov[0]["bbox"]
