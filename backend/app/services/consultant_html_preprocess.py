"""Подготовка HTML-экспорта КонсультантПлюс к индексации справочника."""
from __future__ import annotations

import re
from html import unescape
from typing import Match

_FIRST_ARTICLE_ANCHOR_RE = re.compile(
    r'<a\s+id="Par\d+"\s*></a>\s*Статья\s+\d',
    re.IGNORECASE,
)
_LINK_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_WS_RE = re.compile(r"[ \t\u00a0]{2,}")


def prepare_consultant_html_for_ingest(content: bytes) -> bytes:
    """Возвращает очищенный HTML (bytes) для Docling / norm chunker."""
    raw = content.decode("utf-8", errors="replace")
    return clean_consultant_html(raw).encode("utf-8")


def clean_consultant_html(html: str) -> str:
    """Убирает оглавление, ссылки и шапку; оставляет текст закона с якорями статей."""
    text = html or ""
    start = _find_body_start(text)
    body = text[start:] if start >= 0 else text
    body = re.sub(r"</body>\s*</html>\s*$", "", body, flags=re.IGNORECASE).strip()
    body = _SCRIPT_STYLE_RE.sub(" ", body)
    body = _IMG_RE.sub(" ", body)
    body = _strip_links(body)
    body = _WS_RE.sub(" ", body)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>\n'
        f"{body}\n</body></html>"
    )


def html_to_plain_text(html: str) -> str:
    """Грубое извлечение текста для fallback_text (чанкер всё равно идёт через Docling)."""
    text = _SCRIPT_STYLE_RE.sub(" ", html or "")
    text = _IMG_RE.sub(" ", text)
    text = _strip_links(text)
    text = _TAG_RE.sub("\n", text)
    text = unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def is_consultant_plus_html(content: bytes) -> bool:
    head = content[:65536].decode("utf-8", errors="ignore").lower()
    return "consultant.ru" in head or "консультантплюс" in head


def _find_body_start(html: str) -> int:
    m = _FIRST_ARTICLE_ANCHOR_RE.search(html)
    if m:
        return m.start()
    m2 = re.search(r"<a\s+id=\"Par\d+\"\s*></a>", html, re.IGNORECASE)
    if m2:
        return m2.start()
    return html.lower().find("<body>")


def _strip_links(html: str) -> str:
    def _repl(match: Match[str]) -> str:
        return match.group(1) or ""

    return _LINK_RE.sub(_repl, html)
