"""Подготовка PDF законов (КонсультантПлюс и аналоги) к norm-индексации справочника."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_ARTICLE_BODY_START_RE = re.compile(
    r"(?m)^\s*Статья\s+\d",
    re.IGNORECASE,
)
_TOC_ARTICLE_LINE_RE = re.compile(
    r"^\s*Статья\s+\d+(?:\.\d+)*\s*[\.\s]{4,}\d*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CONSULTANT_MARKERS = (
    "consultant.ru",
    "consultant",
    "консультантплюс",
    "консультант плюс",
    "kplus",
    "справочная правовая система",
)
_PAGE_NUM_ONLY_RE = re.compile(r"^\s*\d{1,4}\s*$")
_WATERMARK_LINE_RE = re.compile(
    r"(?:www\.)?consultant\.ru|консультант\s*плюс|kplus|справочная\s+правовая\s+система",
    re.IGNORECASE,
)
_MULTI_SPACE_RE = re.compile(r"[ \t\u00a0]{2,}")


@dataclass(frozen=True)
class ConsultantPdfPrepareResult:
    plain_text: str
    page_count: int
    stripped_chars: int


def is_pdf_content(content: bytes) -> bool:
    return bool(content) and content[:5].startswith(b"%PDF")


def is_consultant_plus_pdf(content: bytes, *, filename: str = "") -> bool:
    """Эвристика: PDF из КонсультантПлюс или другой НПА-базы."""
    if not is_pdf_content(content):
        return False
    head = content[:131072].decode("latin-1", errors="ignore").lower()
    fn = (filename or "").lower()
    if any(m in head for m in _CONSULTANT_MARKERS):
        return True
    if "консультант" in fn or "consultant" in fn or "127" in fn or "фз" in fn:
        return True
    try:
        import fitz

        doc = fitz.open(stream=content, filetype="pdf")
        try:
            meta = doc.metadata or {}
            combined = " ".join(
                str(meta.get(k) or "") for k in ("title", "author", "subject", "creator", "producer")
            ).lower()
            if any(m in combined for m in _CONSULTANT_MARKERS):
                return True
            if len(doc) > 0:
                sample = (doc[0].get_text("text") or "")[:4000].lower()
                if any(m in sample for m in _CONSULTANT_MARKERS):
                    return True
                if _ARTICLE_BODY_START_RE.search(sample):
                    return True
        finally:
            doc.close()
    except Exception as exc:
        logger.debug("is_consultant_plus_pdf metadata check failed: %s", exc)
    return False


def should_preprocess_legal_pdf(*, instrument_id: Optional[str], ext: str) -> bool:
    """PDF законов/НПА в справочнике — всегда через text-prep pipeline."""
    if (ext or "").lower() != "pdf":
        return False
    iid = (instrument_id or "").strip().lower()
    if not iid or iid == "other":
        return True
    return iid in {
        "fz-127",
        "gk-rf",
        "apk-rf",
        "gpk-rf",
        "plenum-63",
        "plenum-vs-53",
    }


def extract_pdf_plain_text(content: bytes) -> tuple[str, int]:
    """Извлечь текст из PDF через PyMuPDF (blocks → reading order)."""
    import fitz

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        page_parts: list[str] = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("blocks") or []
            blocks_sorted = sorted(blocks, key=lambda b: (round(float(b[1]), 1), float(b[0])))
            lines: list[str] = []
            for block in blocks_sorted:
                if len(block) < 5:
                    continue
                text = str(block[4] or "").strip()
                if not text:
                    continue
                lines.append(text)
            if lines:
                page_parts.append("\n".join(lines))
        return "\n\n".join(page_parts), len(doc)
    finally:
        doc.close()


def _find_law_body_start(text: str) -> int:
    """Первая «настоящая» статья, не строка оглавления с точками."""
    for m in _ARTICLE_BODY_START_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        if _TOC_ARTICLE_LINE_RE.match(line):
            continue
        if re.search(r"\.{4,}", line):
            continue
        return m.start()
    return -1


def clean_legal_pdf_text(raw: str) -> str:
    """Убрать оглавление, колонтитулы, водяные знаки; оставить тело закона."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ""

    start = _find_law_body_start(text)
    if start >= 0:
        text = text[start:]

    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if _PAGE_NUM_ONLY_RE.match(stripped):
            continue
        if _WATERMARK_LINE_RE.search(stripped):
            continue
        cleaned_lines.append(_MULTI_SPACE_RE.sub(" ", stripped))

    out = "\n".join(cleaned_lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def prepare_consultant_pdf_for_ingest(
    content: bytes,
    *,
    filename: str = "",
) -> Optional[ConsultantPdfPrepareResult]:
    """
    Подготовить PDF к norm chunking: PyMuPDF extract + очистка структуры закона.
    Возвращает None, если из PDF не извлечён осмысленный текст.
    """
    if not is_pdf_content(content):
        return None

    raw, page_count = extract_pdf_plain_text(content)
    if not raw.strip():
        return None

    cleaned = clean_legal_pdf_text(raw)
    if len(cleaned) < 80:
        return None

    if not _ARTICLE_BODY_START_RE.search(cleaned):
        logger.warning(
            "PDF %s: после очистки не найдено «Статья N» — norm chunking может быть неполным",
            filename or "?",
        )

    return ConsultantPdfPrepareResult(
        plain_text=cleaned,
        page_count=page_count,
        stripped_chars=max(0, len(raw) - len(cleaned)),
    )
