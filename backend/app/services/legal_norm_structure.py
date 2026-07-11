"""AST закона: нарезка по пунктам и ключи структурных узлов графа норм."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.legal_norm_cross_ref import make_norm_node_key, normalize_article_number

# Пункт / подпункт в начале строки: «1. », «1.1. », не дата «18.06.»
_CLAUSE_LINE_START_RE = re.compile(
    r"(?m)^(?P<num>\d+(?:\.\d+)*)\.\s+",
)

# PDF ГАРАНТ/Docling: «1 .» вместо «1.»; пункт после заголовка статьи в той же строке.
_CLAUSE_SPACED_DOT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)*)\s+\.")
_INLINE_CLAUSE_BREAK_RE = re.compile(
    r"(?<=[а-яёa-z»\"»\);\.])\s+(?P<num>\d+(?:\.\d+)*)\.\s+(?=[А-ЯA-Z«(])",
)

_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?P<kind>Часть|Раздел|Глава|Параграф|§)\s*"
    r"(?P<num>[\dIVXLCDM]+(?:[.\-–][\dIVXLCDM]+)*)?"
    r"(?:\s*[\.]\s*|\s+)"
    r"(?P<title>.*)$",
    re.IGNORECASE | re.DOTALL,
)

_STRUCTURE_KINDS = frozenset({"часть", "раздел", "глава", "параграф", "§"})


@dataclass(frozen=True)
class NormClausePiece:
    """Один индексируемый фрагмент статьи (пункт или преамбула статьи)."""

    clause_ref: str
    text: str


@dataclass(frozen=True)
class StructureChapter:
    chapter_ref: str
    title: str


def make_law_node_key(instrument_id: str) -> str:
    iid = (instrument_id or "unknown").strip().lower()
    return f"{iid}::law"


def make_chapter_node_key(instrument_id: str, chapter_ref: str) -> str:
    iid = (instrument_id or "unknown").strip().lower()
    ref = (chapter_ref or "").strip()
    return f"{iid}::chapter::{ref}"


def make_article_structure_key(instrument_id: str, article_number: str) -> str:
    return make_norm_node_key(instrument_id, article_number)


def chapter_ref_from_title(title: str) -> str:
    t = (title or "").strip()
    m = _CHAPTER_HEADING_RE.match(t)
    if m:
        kind = (m.group("kind") or "").strip().lower()
        num = (m.group("num") or "").strip()
        if num:
            return f"{kind}-{num}".replace(" ", "")
        title_tail = (m.group("title") or "").strip()[:40]
        return f"{kind}-{_slug(title_tail or t)}"
    return _slug(t)


def _slug(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _is_valid_clause_number(num: str) -> bool:
    """Отсекает ложные срабатывания на датах (18.06.) и номерах страниц."""
    parts = num.split(".")
    if len(parts) >= 3:
        return False
    if len(parts) == 2:
        left, right = parts
        if not left.isdigit() or not right.isdigit():
            return False
        # DD.MM — типичный колонтитул даты
        if len(left) <= 2 and len(right) == 2 and int(left) <= 31 and int(right) <= 12:
            return False
    return True


def extract_chapters_from_parent_path(parent_path: Sequence[str]) -> List[StructureChapter]:
    out: List[StructureChapter] = []
    seen: set[str] = set()
    for raw in parent_path or []:
        title = (raw or "").strip()
        if not title:
            continue
        m = _CHAPTER_HEADING_RE.match(title)
        if not m:
            continue
        kind = (m.group("kind") or "").strip().lower()
        if kind not in _STRUCTURE_KINDS:
            continue
        ref = chapter_ref_from_title(title)
        if ref in seen:
            continue
        seen.add(ref)
        out.append(StructureChapter(chapter_ref=ref, title=title))
    return out


def normalize_article_text_for_clause_split(article_text: str) -> str:
    """
    Подготовка текста статьи перед split по пунктам.

    - «1 .» → «1.» (типичная вёрстка КонсультантПлюс / Docling)
    - inline «…банкротстве 1. Дела» → перенос, чтобы сработал ^1. в split
    """
    text = (article_text or "").strip()
    if not text:
        return ""
    text = _CLAUSE_SPACED_DOT_RE.sub(r"\1.", text)

    def _inline_break(m: re.Match[str]) -> str:
        prefix = text[: m.start()]
        if re.search(r"(?i)статья\s*$", prefix) or re.search(r"(?i)ст\.\s*$", prefix):
            return m.group(0)
        return f"\n{m.group('num')}. "

    text = _INLINE_CLAUSE_BREAK_RE.sub(_inline_break, text)
    return text


def split_article_into_clauses(article_text: str) -> List[NormClausePiece]:
    """Делит текст статьи на пункты; преамбула (заголовок статьи) — clause_ref=''."""
    text = normalize_article_text_for_clause_split(article_text)
    if not text:
        return []

    matches = [m for m in _CLAUSE_LINE_START_RE.finditer(text) if _is_valid_clause_number(m.group("num") or "")]
    if not matches:
        return [NormClausePiece(clause_ref="", text=text)]

    pieces: List[NormClausePiece] = []
    preamble_end = matches[0].start()
    preamble = text[:preamble_end].strip()
    if preamble:
        pieces.append(NormClausePiece(clause_ref="", text=preamble))

    for idx, m in enumerate(matches):
        num = normalize_article_number(m.group("num") or "")
        if not num:
            continue
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            pieces.append(NormClausePiece(clause_ref=num, text=body))
    return pieces or [NormClausePiece(clause_ref="", text=text)]


def split_oversized_clause(
    piece: NormClausePiece,
    max_chars: int,
) -> List[NormClausePiece]:
    """Дробит слишком длинный пункт по абзацам, сохраняя clause_ref."""
    t = piece.text.strip()
    if len(t) <= max_chars:
        return [piece]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if len(paragraphs) <= 1:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chars,
            chunk_overlap=0,
            separators=["\n\n", "\n", ". ", " "],
        )
        return [
            NormClausePiece(clause_ref=f"{piece.clause_ref}.{i + 1}" if piece.clause_ref else str(i + 1), text=chunk)
            for i, chunk in enumerate(splitter.split_text(t))
            if chunk.strip()
        ]

    out: List[NormClausePiece] = []
    buf = ""
    part_idx = 0
    for para in paragraphs:
        if len(buf) + len(para) + 2 > max_chars and buf:
            part_idx += 1
            suffix = f".{part_idx}" if piece.clause_ref else str(part_idx)
            cref = f"{piece.clause_ref}{suffix}" if piece.clause_ref else suffix
            out.append(NormClausePiece(clause_ref=cref, text=buf.strip()))
            buf = para
        else:
            buf = f"{buf}\n\n{para}".strip() if buf else para
    if buf.strip():
        if part_idx:
            suffix = f".{part_idx + 1}" if piece.clause_ref else str(part_idx + 1)
            cref = f"{piece.clause_ref}{suffix}" if piece.clause_ref else suffix
        else:
            cref = piece.clause_ref
        out.append(NormClausePiece(clause_ref=cref, text=buf.strip()))
    return out


def expand_article_to_clause_pieces(
    article_text: str,
    *,
    max_chars: int,
) -> List[NormClausePiece]:
    """Полный pipeline: статья → пункты → при необходимости дробление длинных пунктов."""
    raw = split_article_into_clauses(article_text)
    out: List[NormClausePiece] = []
    for piece in raw:
        if len(piece.text) <= max_chars:
            out.append(piece)
        else:
            out.extend(split_oversized_clause(piece, max_chars))
    return out


def clause_sort_key(clause_ref: str) -> Tuple[int, ...]:
    """Сортировка пунктов: преамбула < 1 < 1.1 < 2 < 10."""
    ref = (clause_ref or "").strip()
    if not ref:
        return (0,)
    nums: List[int] = []
    for segment in ref.split("."):
        nums.append(int(segment) if segment.isdigit() else 10_000)
    return (1, *nums)
