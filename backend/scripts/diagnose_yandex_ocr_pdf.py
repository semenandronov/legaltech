#!/usr/bin/env python3
"""Диагностика Yandex OCR для одного PDF: по 1 странице, fail-fast на non-OK."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# backend/ on PYTHONPATH when run from repo root or backend/
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.yandex_vision_ocr import (  # noqa: E402
    vision_api_configured,
    yandex_vision_ocr_pdf_structured,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Yandex OCR structured smoke for PDF")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--model", default="page", help="OCR model (only page is used)")
    args = parser.parse_args()

    if not vision_api_configured():
        print("YANDEX_API_KEY / YANDEX_FOLDER_ID не заданы", file=sys.stderr)
        return 2

    path = args.pdf_path
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 2

    content = path.read_bytes()
    print(f"PDF: {path.name} ({len(content)} bytes)")
    try:
        pages = yandex_vision_ocr_pdf_structured(content, path.name, model=args.model)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {len(pages)} страниц с текстом")
    for p in pages[:3]:
        preview = (p.page_text or "")[:120].replace("\n", " ")
        print(f"  page {p.page_index + 1}: {len(p.page_text)} chars — {preview!r}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
