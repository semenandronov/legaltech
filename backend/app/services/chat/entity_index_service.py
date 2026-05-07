"""Entity indexing helpers for case-level metadata registry."""
from __future__ import annotations

from typing import Any, Dict, List
import re

from app.models.case import Case

_JUDGE_LINE_RE = re.compile(
    r"(?:судья|председательствующ(?:ий|ая|его)|в\s+составе\s+суда)[^\n]{0,220}",
    re.IGNORECASE,
)
_FIO_RE = re.compile(r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.[А-ЯЁ]\.\b")
_CASE_NUMBER_RE = re.compile(r"\b[АA]\d{1,3}-\d+/\d{2,4}\b")


def extract_entity_candidates(text: str) -> Dict[str, List[str]]:
    src = text or ""
    judges: List[str] = []
    seen_judges: set[str] = set()
    for line in _JUDGE_LINE_RE.findall(src):
        for fio in _FIO_RE.findall(line):
            normalized = _normalize_space(fio)
            if normalized and normalized not in seen_judges:
                seen_judges.add(normalized)
                judges.append(normalized)

    numbers: List[str] = []
    seen_numbers: set[str] = set()
    for num in _CASE_NUMBER_RE.findall(src):
        normalized_num = _normalize_space(num).upper()
        if normalized_num and normalized_num not in seen_numbers:
            seen_numbers.add(normalized_num)
            numbers.append(normalized_num)

    return {"judges": judges, "case_numbers": numbers}


def merge_case_entity_index(
    case: Case,
    *,
    file_id: str,
    filename: str,
    text: str,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = dict(case.case_metadata or {})
    entity_index: Dict[str, Any] = dict(metadata.get("entity_index") or {})
    by_file: Dict[str, Any] = dict(entity_index.get("by_file") or {})
    summary: Dict[str, Any] = dict(entity_index.get("summary") or {})

    extracted = extract_entity_candidates(text)
    by_file[str(file_id)] = {
        "filename": filename,
        "judges": extracted.get("judges", []),
        "case_numbers": extracted.get("case_numbers", []),
    }

    all_judges: List[str] = []
    judges_seen: set[str] = set()
    all_numbers: List[str] = []
    numbers_seen: set[str] = set()
    for payload in by_file.values():
        for judge in payload.get("judges", []):
            normalized = _normalize_space(judge)
            if normalized and normalized not in judges_seen:
                judges_seen.add(normalized)
                all_judges.append(normalized)
        for num in payload.get("case_numbers", []):
            normalized_num = _normalize_space(num).upper()
            if normalized_num and normalized_num not in numbers_seen:
                numbers_seen.add(normalized_num)
                all_numbers.append(normalized_num)

    summary["judges"] = all_judges
    summary["case_numbers"] = all_numbers
    entity_index["by_file"] = by_file
    entity_index["summary"] = summary
    metadata["entity_index"] = entity_index

    if not metadata.get("case_number") and all_numbers:
        metadata["case_number"] = all_numbers[0]

    case.case_metadata = metadata
    return metadata


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())
