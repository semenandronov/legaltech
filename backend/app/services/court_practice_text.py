"""Парсинг и подготовка текстов судебных актов для индексации."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

# Номера дел: А40-277413/2018, 305-ЭС21-14303(9)
_CASE_NUM_RE = re.compile(
    r"\b([АAВBСCЕEНHКKМMОOРPТTУUXХ]\d{1,2}-\d{2,7}/\d{2,4}(?:\(\d+\))?)\b",
    re.IGNORECASE,
)
_BANKRUPTCY_CASE_RE = re.compile(
    r"дел[оа]?\s*№?\s*([АA]\d{1,2}-\d{2,7}/\d{2,4})",
    re.IGNORECASE,
)

_COURT_TIER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("vs_rf", re.compile(r"верховн\w+\s+суд", re.IGNORECASE)),
    ("cassation", re.compile(r"арбитражн\w+\s+суд\w+\s+.*округ|кассацион", re.IGNORECASE)),
    ("appeal", re.compile(r"апелляцион", re.IGNORECASE)),
    ("first", re.compile(r"арбитражн\w+\s+суд\s+города|суд\s+первой", re.IGNORECASE)),
)

_RESOLUTIVE_MARKERS = (
    "определил:",
    "о п р е д е л и л:",
    "постановил:",
    "р е ш и л:",
    "решил:",
)

_MOTIVATION_MARKERS = (
    "у с т а н о в и л:",
    "установил:",
    "мотивировочн",
    "суд установил",
)


@dataclass(frozen=True)
class CourtActMetadata:
    case_number: str
    cad_case_number: Optional[str]
    court_name: Optional[str]
    court_tier: str
    judgment_date: Optional[date]
    act_kind: Optional[str]


@dataclass(frozen=True)
class PreparedCourtChunk:
    chunk_index: int
    chunk_text: str


def _normalize_case_number(raw: str) -> str:
    s = (raw or "").strip().upper().replace("A", "А").replace("B", "В").replace("C", "С")
    s = s.replace("E", "Е").replace("H", "Н").replace("K", "К").replace("M", "М")
    s = s.replace("O", "О").replace("P", "Р").replace("T", "Т").replace("X", "Х")
    return s


def extract_case_numbers(text: str) -> List[str]:
    found = [_normalize_case_number(m.group(1)) for m in _CASE_NUM_RE.finditer(text or "")]
    seen: set[str] = set()
    out: List[str] = []
    for num in found:
        if num not in seen:
            seen.add(num)
            out.append(num)
    return out


def infer_court_tier(text: str) -> str:
    head = (text or "")[:2500]
    for tier, pat in _COURT_TIER_PATTERNS:
        if pat.search(head):
            return tier
    return "unknown"


def infer_court_name(text: str) -> Optional[str]:
    head = (text or "")[:1200]
    m = re.search(
        r"(Верховный\s+Суд\s+Российской\s+Федерации|"
        r"Арбитражный\s+суд\s+[^\n,]{3,80}|"
        r"Судебная\s+коллегия[^\n,]{0,60})",
        head,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def parse_judgment_date(raw: Optional[str], text: str) -> Optional[date]:
    if raw:
        s = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
    m = re.search(
        r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)\s+(\d{4})\s*г",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    months = {
        "января": 1,
        "февраля": 2,
        "марта": 3,
        "апреля": 4,
        "мая": 5,
        "июня": 6,
        "июля": 7,
        "августа": 8,
        "сентября": 9,
        "октября": 10,
        "ноября": 11,
        "декабря": 12,
    }
    try:
        return date(int(m.group(3)), months[m.group(2).lower()], int(m.group(1)))
    except (KeyError, ValueError):
        return None


def extract_metadata(
    text: str,
    *,
    case_number: Optional[str] = None,
    court_name: Optional[str] = None,
    judgment_date: Optional[str] = None,
    court_tier: Optional[str] = None,
) -> CourtActMetadata:
    numbers = extract_case_numbers(text)
    primary = _normalize_case_number(case_number) if case_number else (numbers[0] if numbers else "")
    cad_match = _BANKRUPTCY_CASE_RE.search(text or "")
    cad_num = _normalize_case_number(cad_match.group(1)) if cad_match else None
    if not primary and cad_num:
        primary = cad_num
    tier = (court_tier or "").strip() or infer_court_tier(text)
    return CourtActMetadata(
        case_number=primary or "UNKNOWN",
        cad_case_number=cad_num,
        court_name=(court_name or "").strip() or infer_court_name(text),
        court_tier=tier,
        judgment_date=parse_judgment_date(judgment_date, text),
        act_kind=_infer_act_kind(text),
    )


def _infer_act_kind(text: str) -> Optional[str]:
    head = (text or "")[:800].lower()
    if "определение" in head:
        return "определение"
    if "постановление" in head:
        return "постановление"
    if "решение" in head:
        return "решение"
    return None


def clean_act_text(text: str) -> str:
    """Убрать лишние пробелы; сохранить структуру абзацев."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def focus_motivational_text(text: str) -> str:
    """
    Сместить фокус на мотивировочную часть: от «установил» до резолютивной части.
    Если маркеры не найдены — вернуть весь очищенный текст.
    """
    s = clean_act_text(text)
    if not s:
        return ""
    lower = s.lower()
    start = 0
    for marker in _MOTIVATION_MARKERS:
        idx = lower.find(marker)
        if idx >= 0:
            start = idx
            break
    end = len(s)
    for marker in _RESOLUTIVE_MARKERS:
        idx = lower.find(marker, start + 20)
        if idx >= 0:
            tail = s[idx : idx + 400]
            end = idx + len(tail)
            break
    focused = s[start:end].strip()
    return focused if len(focused) >= 200 else s


def chunk_act_text(
    text: str,
    *,
    single_chunk_max_chars: int = 10_000,
    split_chunk_chars: int = 2500,
    overlap_chars: int = 300,
) -> List[PreparedCourtChunk]:
    body = focus_motivational_text(text)
    if not body:
        return []
    if len(body) <= single_chunk_max_chars:
        return [PreparedCourtChunk(chunk_index=0, chunk_text=body)]

    chunks: List[PreparedCourtChunk] = []
    start = 0
    idx = 0
    n = len(body)
    step = max(500, split_chunk_chars - overlap_chars)
    while start < n:
        end = min(start + split_chunk_chars, n)
        if end < n:
            boundary = body.rfind("\n\n", start, end)
            if boundary > start + 400:
                end = boundary
        piece = body[start:end].strip()
        if piece:
            chunks.append(PreparedCourtChunk(chunk_index=idx, chunk_text=piece))
            idx += 1
        if end >= n:
            break
        start = max(end - overlap_chars, start + step)
    return chunks
