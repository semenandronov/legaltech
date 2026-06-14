#!/usr/bin/env python3
"""Собрать DOCX-шаблоны с {{ переменными }} из sources/*.txt."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.draft_docxtpl_service import build_docx_from_text  # noqa: E402

DRAFT_DIR = ROOT / "app" / "templates" / "draft"
SOURCES = DRAFT_DIR / "sources"

TEMPLATE_FILES = {
    "creditor_ul_general": "creditor_ul_general.docx",
    "debtor_ul_general": "debtor_ul_general.docx",
    "debtor_fl_general": "debtor_fl_general.docx",
    "creditor_fl_general": "creditor_fl_general.docx",
}


def main() -> None:
    for template_id, docx_name in TEMPLATE_FILES.items():
        src = SOURCES / f"{template_id}.txt"
        if not src.is_file():
            print(f"SKIP missing source: {src}")
            continue
        body = src.read_text(encoding="utf-8")
        out = DRAFT_DIR / docx_name
        build_docx_from_text(body, out)
        print(f"OK {out}")


if __name__ == "__main__":
    main()
