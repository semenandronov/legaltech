"""Layer 1: fast document triage using upload-time metadata (no full-file LLM)."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.services.chat.retrieval_router import CaseFileCatalogEntry, build_case_file_catalog
from app.services.draft_pipeline.document_roles import (
    CORE_DATA_ROLES,
    SIDEBAR_ROLES,
    doc_types_for_role,
    normalize_doc_type,
)
from app.services.draft_pipeline.schemas import DocumentTriageResult, DraftTaskPlan, TriagedFile

logger = logging.getLogger(__name__)

_MAX_CORE_PER_ROLE = 2
_MAX_SIDEBAR = 4


def _score_file_for_role(entry: CaseFileCatalogEntry, role: str) -> float:
    norm_type = normalize_doc_type(entry.doc_type)
    acceptable = {normalize_doc_type(t) for t in doc_types_for_role(role)}
    score = 0.0
    if norm_type in acceptable:
        score += 0.75
    blob = f"{entry.filename} {entry.summary} {' '.join(entry.key_points)}".lower()
    keywords: Dict[str, List[str]] = {
        "contract": ["договор", "контракт", "поставк"],
        "primary_execution_act": ["акт", "упд", "отгруз", "прием", "передач"],
        "payment_order": ["плат", "п/п", "поручен", "оплат"],
        "pretension": ["претенз"],
        "egrul_extract": ["егрюл", "егрип", "выписк"],
        "charter": ["устав"],
        "requisites": ["инн", "огрн", "реквизит", "егрюл"],
    }
    for kw in keywords.get(role, []):
        if kw in blob:
            score += 0.15
    if role in SIDEBAR_ROLES and norm_type == "other" and role == "requisites":
        if any(x in blob for x in ("инн", "огрн", "устав", "егрюл")):
            score += 0.35
    return min(score, 1.0)


def triage_case_documents(
    *,
    db: Session,
    case_id: str,
    task_plan: DraftTaskPlan,
    attached_file_ids: Optional[List[str]] = None,
) -> DocumentTriageResult:
    """
    Map required_doc_roles → concrete files using catalog metadata only.

    Uses DocumentClassification + file passport summaries from upload pipeline.
    """
    catalog = build_case_file_catalog(db, str(case_id))
    if attached_file_ids:
        allowed: Set[str] = {str(x) for x in attached_file_ids if str(x).strip()}
        catalog = [e for e in catalog if e.file_id in allowed]

    required_roles = list(task_plan.required_doc_roles or [])
    if not required_roles:
        required_roles = ["contract", "primary_execution_act", "payment_order", "requisites"]

    core_files: List[TriagedFile] = []
    sidebar_files: List[TriagedFile] = []
    used_ids: Set[str] = set()

    def _pick_best(role: str, tier: str, limit: int) -> None:
        scored: List[tuple[float, CaseFileCatalogEntry]] = []
        for entry in catalog:
            if entry.file_id in used_ids:
                continue
            s = _score_file_for_role(entry, role)
            if s < 0.35:
                continue
            scored.append((s, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        for s, entry in scored[:limit]:
            used_ids.add(entry.file_id)
            tf = TriagedFile(
                file_id=entry.file_id,
                filename=entry.filename,
                doc_type=normalize_doc_type(entry.doc_type),
                role=role,
                tier="core_data" if tier == "core" else "sidebar_context",
                score=round(s, 3),
            )
            if tier == "core":
                core_files.append(tf)
            else:
                sidebar_files.append(tf)

    for role in required_roles:
        if role in CORE_DATA_ROLES:
            _pick_best(role, "core", _MAX_CORE_PER_ROLE)
        elif role in SIDEBAR_ROLES:
            _pick_best(role, "sidebar", 1)

    if not sidebar_files:
        _pick_best("requisites", "sidebar", _MAX_SIDEBAR)

    # Fallback: if no core files matched, take top files by any sub_query keyword overlap
    if not core_files and catalog:
        for entry in catalog[: min(7, len(catalog))]:
            if entry.file_id in used_ids:
                continue
            used_ids.add(entry.file_id)
            core_files.append(
                TriagedFile(
                    file_id=entry.file_id,
                    filename=entry.filename,
                    doc_type=normalize_doc_type(entry.doc_type),
                    role="unspecified",
                    tier="core_data",
                    score=0.2,
                )
            )

    excluded = max(0, len(catalog) - len(used_ids))
    logger.info(
        "[draft_pipeline.triage] case=%s core=%s sidebar=%s excluded=%s",
        case_id,
        len(core_files),
        len(sidebar_files),
        excluded,
    )
    return DocumentTriageResult(
        core_files=core_files,
        sidebar_files=sidebar_files,
        excluded_count=excluded,
    )
