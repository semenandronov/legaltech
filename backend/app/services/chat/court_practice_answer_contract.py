"""
Contract + validation for court_practice answers.

Goal: the assistant is a precedent-finder, not a legal consultant.
We enforce a stable output shape: case cards grounded in citations [N],
and prohibit advice/strategy language in this mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


_ARBITRAZH_CASE_RE = re.compile(
    r"\b[АA]\d{1,3}-\d{1,8}/\d{2,4}\b"
)

_UNICODE_DASHES_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]")

_FORBIDDEN_ADVICE_RE = re.compile(
    r"\b("
    r"рекоменд(ую|уется|ация|овать)|"
    r"совет(ую|ует|ы|ом)|"
    r"вам\s+стоит|"
    r"следует\s+сделать|"
    r"нужно\s+сделать|"
    r"лучше\s+сделать|"
    r"стратег(ия|ически)|"
    r"тактик(а|тически)"
    r")\b",
    re.IGNORECASE,
)

_MISSING_TEXT_CLAIM_RE = re.compile(
    r"\b("
    r"отсутствует\s+текст|"
    r"нет\s+текста|"
    r"не\s+содерж(ит|ат)\s+текст|"
    r"не\s+включа(ет|ют)\s+текст|"
    r"без\s+полного\s+текста|"
    r"исходн(ые|ая)\s+данн(ые|ая)\s+не\s+содерж(ат|ит)\s+текст"
    r")\b",
    re.IGNORECASE,
)


def _normalize_case_number(cn: str) -> str:
    if not cn:
        return ""
    cn = str(cn).strip()
    cn = _UNICODE_DASHES_RE.sub("-", cn)
    return cn


def _normalize_answer_text_for_validation(text: str) -> str:
    s = (text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _UNICODE_DASHES_RE.sub("-", s)
    # Normalize common bullet drift: "•" → "-" and ensure cards don't glue together.
    s = re.sub(r"\s*•\s+", "\n- ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _citations_have_any_text(citations: Sequence[Dict[str, Any]]) -> bool:
    for c in citations or []:
        if str(c.get("source_type") or "") != "court_practice":
            continue
        for key in ("quote", "page_content", "text", "content", "chunk_text"):
            v = c.get(key)
            if isinstance(v, str) and v.strip():
                return True
    return False


@dataclass(frozen=True)
class CourtPracticeAnswerValidation:
    ok: bool
    status: str
    reasons: List[str]
    metrics: Dict[str, Any]


def extract_case_numbers_from_citations(citations: Sequence[Dict[str, Any]]) -> List[str]:
    """
    Best-effort: collect case numbers from citations (file_name/quote_anchor/text).
    Returns unique list preserving first-seen order.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for c in citations or []:
        if str(c.get("source_type") or "") != "court_practice":
            continue
        hay = " ".join(
            [
                str(c.get("file_name") or ""),
                str(c.get("quote_anchor") or ""),
                str(c.get("quote") or ""),
            ]
        )
        hay = _UNICODE_DASHES_RE.sub("-", hay)
        for m in _ARBITRAZH_CASE_RE.findall(hay):
            if m not in seen:
                seen.add(m)
                out.append(m)
    return out


def extract_case_numbers_from_context(context: str) -> List[str]:
    """
    Best-effort: parse <document case="..."> tags in court practice context.
    """
    if not context:
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for m in re.findall(r'case\s*=\s*"([^"]+)"', context):
        case = _normalize_case_number(m or "")
        if not case:
            continue
        # Normalize and also accept embedded arbitrazh pattern.
        cand = _ARBITRAZH_CASE_RE.findall(case) or [case]
        for c in cand:
            c = _normalize_case_number(c)
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def validate_court_practice_answer(
    *,
    answer_text: str,
    citations: Sequence[Dict[str, Any]],
    available_case_numbers: Optional[Sequence[str]] = None,
    min_cases: int = 2,
) -> CourtPracticeAnswerValidation:
    """
    Hard-ish validation:
    - Must contain inline citation markers [N] if citations exist
    - Must mention at least min_cases distinct case numbers (from available list or from citations)
    - Each mentioned case number should appear in a "case card" line (bullet or header) with [N]
    - Must not contain advice/strategy verbs/phrases
    """
    text = _normalize_answer_text_for_validation(answer_text or "")
    cits = list(citations or [])
    reasons: List[str] = []

    if not text:
        return CourtPracticeAnswerValidation(
            ok=False,
            status="empty_answer",
            reasons=["Пустой ответ."],
            metrics={"text_chars": 0, "citations_count": len(cits)},
        )

    if cits and not re.search(r"\[\d+\]", text):
        reasons.append("В ответе нет inline-ссылок вида [N], хотя есть citations.")

    if _FORBIDDEN_ADVICE_RE.search(text):
        reasons.append("В ответе найден совет/рекомендация/стратегия — в режиме судебной практики это запрещено.")

    if _MISSING_TEXT_CLAIM_RE.search(text) and _citations_have_any_text(cits):
        reasons.append(
            "В ответе заявлено, что «нет текста/исходные данные не содержат текст», "
            "но в citations есть текст — это недопустимо. Если в найденных фрагментах нет позиции по вопросу, "
            "нужно так и написать (не подменять это «нет текста»)."
        )

    avail = [x for x in (available_case_numbers or []) if x]
    if not avail:
        avail = extract_case_numbers_from_citations(cits)
    avail = [_normalize_case_number(x) for x in avail if _normalize_case_number(x)]

    # Detect mentioned case numbers.
    mentioned: Set[str] = set()
    if avail:
        for cn in avail:
            if cn and cn in text:
                mentioned.add(cn)
    else:
        # Fallback: any arbitrazh-like case number in text.
        for cn in _ARBITRAZH_CASE_RE.findall(text):
            mentioned.add(_normalize_case_number(cn))

    if len(mentioned) < max(1, int(min_cases or 1)):
        reasons.append(
            f"Недостаточно конкретных дел в ответе (нашлось {len(mentioned)}; нужно минимум {max(1, int(min_cases or 1))})."
        )

    # Case card heuristic: case number appears in a bullet/header line and has [N] nearby.
    bad_cards: List[str] = []
    if mentioned:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for cn in sorted(mentioned):
            has_card_line = False
            for ln in lines:
                if cn not in ln:
                    continue
                if not (ln.startswith("-") or ln.startswith("*") or ln.startswith("#")):
                    continue
                if re.search(r"\[\d+\]", ln):
                    has_card_line = True
                    break
            if not has_card_line:
                bad_cards.append(cn)
        if bad_cards:
            reasons.append(
                "Не по всем упомянутым делам есть карточка (bullet/header строка с делом и [N]): "
                + ", ".join(bad_cards[:6])
                + ("…" if len(bad_cards) > 6 else "")
            )

    ok = len(reasons) == 0
    return CourtPracticeAnswerValidation(
        ok=ok,
        status="ok" if ok else "contract_violation",
        reasons=reasons,
        metrics={
            "text_chars": len(text),
            "citations_count": len(cits),
            "available_cases_count": len(avail),
            "mentioned_cases_count": len(mentioned),
        },
    )

