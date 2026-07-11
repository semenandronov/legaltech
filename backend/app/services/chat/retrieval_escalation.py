"""
Deterministic retrieval escalation for case assistant.

Production contract (no LLM on the hot path):

1. deepen_in_files — scope already bound to the right file(s) but weak/missing
   anchors → second pass inside those files (higher recall + within-file expand).
2. broaden_full_case — narrow scope looks wrong (no hit overlap / unbound) →
   search the whole case.
3. deepen_in_files — full_case found concrete files → deepen inside them.

FAST path may use exactly one escalation round (max_retrieval_rounds=2).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

EscalationAction = Literal["accept", "broaden_full_case", "deepen_in_files"]

_NARROW_SCOPES = frozenset({"resolved", "relaxed", "attached", "summary_hybrid", "doc_type"})

# High-precision anchors that must appear in retrieved text when present in the question.
_ANCHOR_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"а\s*40[-\s]?\d{2,6}\s*/\s*\d{2,4}", re.IGNORECASE),
    re.compile(r"\b\d{2}:\d{2}:\d{5,}:\d+\b"),
    re.compile(r"№\s*\d{1,4}(?:\s*/\s*\d{4})?", re.IGNORECASE),
    re.compile(r"\b\d{1,3}(?:[\s\u00a0.]\d{3}){1,3}\b"),  # money-like 2 443 000
    re.compile(r"\bинн\s*[:№]?\s*\d{10,12}\b", re.IGNORECASE),
)

_BOUND_RATIONALE_MARKERS = (
    "document_ref_catalog_match",
    "attached_file_ids",
    "active_document_id",
    "small_case_filename_match",
    "file_summary_",
)


@dataclass(frozen=True)
class RetrievalEscalationPlan:
    action: EscalationAction
    reason: str
    file_ids: Tuple[str, ...] = ()
    search_query: str = ""
    recall_k_bump: int = 0
    merge_prior_docs: bool = False
    within_file_expand: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _norm_text(value: str) -> str:
    s = (value or "").lower().replace("ё", "е")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_question_anchors(question: str) -> List[str]:
    """Distinctive tokens from the question that retrieval should cover."""
    q = question or ""
    found: List[str] = []
    seen = set()
    for pattern in _ANCHOR_PATTERNS:
        for match in pattern.finditer(q):
            token = _norm_text(match.group(0))
            token = token.replace(" ", "")
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            found.append(token)
    return found


def _doc_text(doc: Any) -> str:
    if isinstance(doc, Mapping):
        return str(doc.get("page_content") or "")
    return str(getattr(doc, "page_content", "") or "")


def _doc_metadata(doc: Any) -> Dict[str, Any]:
    if isinstance(doc, Mapping):
        md = doc.get("metadata") or {}
        return md if isinstance(md, dict) else {}
    md = getattr(doc, "metadata", None) or {}
    return md if isinstance(md, dict) else {}


def _doc_file_id(doc: Any) -> str:
    md = _doc_metadata(doc)
    for key in ("file_id", "source_file_id", "doc_id"):
        value = md.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def question_anchors_covered(question: str, docs: Sequence[Any]) -> bool:
    """
    True when every high-precision question anchor appears in at least one chunk,
    or when the question has no such anchors.
    """
    anchors = extract_question_anchors(question)
    if not anchors:
        return True
    blob = _norm_text("\n".join(_doc_text(d) for d in docs))
    blob_compact = blob.replace(" ", "")
    for anchor in anchors:
        if anchor not in blob_compact and anchor not in blob:
            return False
    return True


def dominant_hit_file_ids(docs: Sequence[Any], *, limit: int = 3) -> List[str]:
    """Rank file_ids by hit frequency then best score."""
    counts: Dict[str, int] = {}
    best_score: Dict[str, float] = {}
    for doc in docs:
        fid = _doc_file_id(doc)
        if not fid:
            continue
        counts[fid] = counts.get(fid, 0) + 1
        score = None
        md = _doc_metadata(doc)
        for key in ("rerank_score", "combined_score", "score", "relevance_score", "bm25_score"):
            value = md.get(key)
            if isinstance(value, (int, float)):
                score = float(value)
                break
        if score is not None:
            best_score[fid] = max(best_score.get(fid, float("-inf")), score)
    ranked = sorted(
        counts.keys(),
        key=lambda fid: (counts[fid], best_score.get(fid, 0.0)),
        reverse=True,
    )
    return ranked[: max(1, limit)]


def _doc_identity(doc: Any) -> str:
    md = _doc_metadata(doc)
    for key in ("chunk_id", "id", "vector_id"):
        value = md.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{value}"
    content = _doc_text(doc).strip()
    fid = _doc_file_id(doc)
    return f"{fid}:{hash(content[:240])}"


def merge_retrieval_documents(
    prior: Sequence[Any],
    new_docs: Sequence[Any],
    *,
    limit: int = 100,
) -> List[Any]:
    """Dedup by chunk identity; prefer newer docs when colliding."""
    merged: List[Any] = []
    seen = set()
    for doc in list(new_docs) + list(prior):
        key = _doc_identity(doc)
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= limit:
            break
    return merged


def _scope_looks_bound(task: Mapping[str, Any], scoped_files: Sequence[str]) -> bool:
    """True when router already locked onto concrete files with high confidence."""
    if not scoped_files:
        return False
    rationale = str(task.get("rationale") or "")
    if any(marker in rationale for marker in _BOUND_RATIONALE_MARKERS):
        return True
    try:
        conf = float(task.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return conf >= 0.85


def plan_retrieval_escalation(
    *,
    question: str,
    retrieval_task: Optional[Mapping[str, Any]],
    docs: Sequence[Any],
    retrieval_round: int,
    max_rounds: int,
) -> RetrievalEscalationPlan:
    """
    Decide the next retrieval action after a weak grade.

    Caller must only invoke this when another round is still allowed.
    """
    q = (question or "").strip()
    task = dict(retrieval_task or {})
    scope_mode = str(task.get("scope_mode") or "full_case").strip()
    scoped_files = [
        str(x).strip()
        for x in (task.get("file_ids") or [])
        if str(x).strip()
    ]
    hit_files = dominant_hit_file_ids(docs, limit=3)
    search_query = str(task.get("search_query") or q).strip() or q
    hit_overlap = [fid for fid in hit_files if fid in set(scoped_files)]

    if retrieval_round >= max(1, max_rounds) - 1:
        return RetrievalEscalationPlan(action="accept", reason="rounds_exhausted")

    # Bound narrow scope that already hit the target file(s) → deepen in-file,
    # do not throw away a correct document_ref / summary scope.
    if scoped_files and scope_mode in _NARROW_SCOPES:
        bound = _scope_looks_bound(task, scoped_files)
        if bound and (hit_overlap or not docs):
            return RetrievalEscalationPlan(
                action="deepen_in_files",
                reason="weak_under_bound_scope_deepen",
                file_ids=tuple(scoped_files[:3]),
                search_query=q or search_query,
                recall_k_bump=16,
                merge_prior_docs=True,
                within_file_expand=True,
            )
        if hit_overlap and not question_anchors_covered(q, docs):
            return RetrievalEscalationPlan(
                action="deepen_in_files",
                reason="weak_narrow_missing_anchors_deepen",
                file_ids=tuple(hit_overlap[:3]),
                search_query=q or search_query,
                recall_k_bump=12,
                merge_prior_docs=True,
                within_file_expand=True,
            )
        return RetrievalEscalationPlan(
            action="broaden_full_case",
            reason="weak_under_narrow_scope",
            search_query=q or search_query,
            recall_k_bump=8,
            merge_prior_docs=False,
        )

    # Concrete files already appeared on full_case → deepen inside them.
    if hit_files:
        return RetrievalEscalationPlan(
            action="deepen_in_files",
            reason="weak_deepen_hit_files",
            file_ids=tuple(hit_files),
            search_query=q or search_query,
            recall_k_bump=12,
            merge_prior_docs=True,
            within_file_expand=True,
        )

    # Empty / unscored pool: one wider full-case pass.
    return RetrievalEscalationPlan(
        action="broaden_full_case",
        reason="weak_empty_or_unscoped",
        search_query=q or search_query,
        recall_k_bump=16,
        merge_prior_docs=False,
    )


def build_escalated_retrieval_task(
    *,
    plan: RetrievalEscalationPlan,
    question: str,
    prior_task: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Materialize a locked RetrievalTask dict for the escalation pass."""
    prior = dict(prior_task or {})
    rationale = str(prior.get("rationale") or "")
    suffix = f"+escalate:{plan.action}:{plan.reason}"
    if suffix not in rationale:
        rationale = (rationale + suffix)[:500]
    query = (plan.search_query or question or "").strip()

    if plan.action == "deepen_in_files":
        return {
            "search_query": query,
            "file_ids": list(plan.file_ids),
            "doc_type": None,
            "scope_mode": "resolved",
            "confidence": 0.92,
            "rationale": rationale,
            "escalation_lock": True,
            "within_file_expand": True,
        }

    # broaden_full_case (and accept should not call this)
    return {
        "search_query": query,
        "file_ids": [],
        "doc_type": None,
        "scope_mode": "full_case",
        "confidence": 0.55,
        "rationale": rationale,
        "escalation_lock": True,
        "within_file_expand": False,
    }


def bump_recall_k(budget_profile: Mapping[str, Any], bump: int) -> Dict[str, Any]:
    bp = dict(budget_profile or {})
    if bump <= 0:
        return bp
    current = int(bp.get("recall_k") or 0)
    if current <= 0:
        return bp
    # Keep instant path snappy: cap escalate recall.
    bp["recall_k"] = min(current + int(bump), max(current, 48))
    return bp


def serialize_docs_for_state(docs: Iterable[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for doc in docs:
        if isinstance(doc, Mapping):
            out.append(
                {
                    "page_content": str(doc.get("page_content") or ""),
                    "metadata": dict(doc.get("metadata") or {}),
                }
            )
            continue
        out.append(
            {
                "page_content": str(getattr(doc, "page_content", "") or ""),
                "metadata": dict(getattr(doc, "metadata", None) or {}),
            }
        )
    return out
