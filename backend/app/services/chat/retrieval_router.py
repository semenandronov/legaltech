"""
Case assistant retrieval router (Secretary): question → scoped RetrievalTask.

Funnel for large corpora (file_count > SMALL_CASE_MAX):
  1. file-summary hybrid (vector + FTS, dynamic K on upload-time passports)
  2. LLM catalog secretary (structured scope + query rewrite)
  3. relaxed summary near-miss (lower threshold / top-K from same candidates)
  4. full_case only when LLM explicitly requests it with sufficient confidence,
     or when no scope signal exists at all (empty summary index)

Small corpora (file_count <= SMALL_CASE_MAX): skip file picking → hybrid chunk
search over the entire case (low noise, high recall).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import config
from app.models.analysis import DocumentClassification
from app.models.case import File as CaseFile

logger = logging.getLogger(__name__)

ScopeMode = Literal[
    "attached",
    "resolved",
    "doc_type",
    "full_case",
    "passport",
    "summary_hybrid",
]


class RetrievalTask(BaseModel):
    search_query: str = Field(..., description="Normalized query for hybrid retrieval")
    file_ids: List[str] = Field(default_factory=list)
    doc_type: Optional[str] = None
    scope_mode: ScopeMode = "full_case"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""
    # When True, extract_retrieval_task must not re-route (escalation pass owns scope).
    escalation_lock: bool = False
    # When True, hybrid recall merges a within-file lexical channel for compact files.
    within_file_expand: bool = False


class CaseFileCatalogEntry(BaseModel):
    file_id: str
    filename: str
    doc_type: str = "other"
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)


def _count_case_files(db: Session, case_id: str) -> int:
    from app.utils.database import ensure_db_session_live

    ensure_db_session_live(db)
    return int(
        db.query(CaseFile.id).filter(CaseFile.case_id == case_id).count()
    )


def _batch_doc_types_by_file_id(db: Session, file_ids: List[str]) -> Dict[str, str]:
    """One query for all classifications (avoids N+1 per file)."""
    if not file_ids:
        return {}
    out: Dict[str, str] = {}
    try:
        rows = (
            db.query(DocumentClassification.file_id, DocumentClassification.doc_type)
            .filter(DocumentClassification.file_id.in_(file_ids))
            .all()
        )
        for fid, dtype in rows:
            if fid and dtype and str(fid) not in out:
                out[str(fid)] = str(dtype)
    except Exception:
        pass
    return out


def build_case_file_catalog(db: Session, case_id: str, *, limit: int = 80) -> List[CaseFileCatalogEntry]:
    """Load compact file catalog for router LLM."""
    from app.utils.database import ensure_db_session_live

    ensure_db_session_live(db)
    limit = max(1, min(int(limit), 200))
    files = (
        db.query(CaseFile)
        .filter(CaseFile.case_id == case_id)
        .order_by(CaseFile.created_at.asc())
        .limit(limit)
        .all()
    )
    file_ids = [str(f.id) for f in files]
    doc_types = _batch_doc_types_by_file_id(db, file_ids)
    entries: List[CaseFileCatalogEntry] = []
    for f in files:
        fid = str(f.id)
        doc_type = doc_types.get(fid, "other")
        kps = getattr(f, "doc_key_points", None) or []
        if not isinstance(kps, list):
            kps = []
        entries.append(
            CaseFileCatalogEntry(
                file_id=fid,
                filename=str(f.filename or ""),
                doc_type=doc_type,
                summary=str(getattr(f, "doc_summary_short", "") or "")[:400],
                key_points=[str(x) for x in kps[:5]],
            )
        )
    return entries


def _small_case_max_files() -> int:
    return int(getattr(config, "CASE_ASSISTANT_ROUTER_SMALL_CASE_MAX_FILES", 5) or 5)


def _is_small_case(case_file_count: int) -> bool:
    small_max = _small_case_max_files()
    return small_max > 0 and case_file_count > 0 and case_file_count <= small_max


def _small_case_task(question: str) -> RetrievalTask:
    q = question.strip()
    return RetrievalTask(
        search_query=q,
        scope_mode="full_case",
        confidence=0.75,
        rationale="small_case_full_corpus",
    )


def _try_document_ref_scope(
    catalog: List[CaseFileCatalogEntry],
    question: str,
) -> Optional[RetrievalTask]:
    """Deterministic №N → file_ids from catalog (filename/summary/key_points)."""
    from app.services.chat.document_ref_scope import resolve_document_ref_file_ids

    matched = resolve_document_ref_file_ids(catalog, question, limit=3)
    if not matched:
        return None
    return RetrievalTask(
        search_query=question.strip(),
        file_ids=matched,
        scope_mode="resolved",
        confidence=0.94,
        rationale="document_ref_catalog_match",
        within_file_expand=True,
    )


def _match_catalog_files_by_question(
    catalog: List[CaseFileCatalogEntry],
    question: str,
) -> List[str]:
    """Lightweight filename/date match without LLM — for small corpora."""
    q = (question or "").strip().lower()
    if not q or not catalog:
        return []

    # Prefer exact document-number matches before fuzzy filename tokens.
    from app.services.chat.document_ref_scope import resolve_document_ref_file_ids

    ref_matched = resolve_document_ref_file_ids(catalog, question, limit=3)
    if ref_matched:
        return ref_matched

    date_match = re.search(r"(\d{2})[./](\d{2})[./](\d{2,4})", q)
    date_variants: List[str] = []
    if date_match:
        d, m, y = date_match.groups()
        y4 = y if len(y) == 4 else f"20{y}"
        date_variants = [
            f"{d}.{m}.{y}",
            f"{d}.{m}.{y4}",
            f"{d}-{m}-{y}",
            f"{d}-{m}-{y4}",
            f"{d}_{m}_{y}",
            f"{d}_{m}_{y4}",
        ]

    scored: List[tuple[float, str]] = []
    for entry in catalog:
        fname = (entry.filename or "").lower()
        if not fname:
            continue
        score = 0.0
        if date_variants and any(v in fname for v in date_variants):
            score += 2.0
        for token in re.findall(r"[a-zа-яё0-9]{4,}", q):
            if token in fname:
                score += 0.75
        doc_hints = ("договор", "контракт", "иск", "заявлен", "акт", "протокол")
        if any(h in q for h in doc_hints) and any(h in fname for h in doc_hints):
            score += 1.0
        if score >= 1.5:
            scored.append((score, entry.file_id))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    return [fid for _, fid in scored[:3]]


def _is_near_full_case_scope(file_ids: List[str], case_file_count: int) -> bool:
    """True when 'scoped' IDs cover the whole corpus — not a useful file pick."""
    n = len([str(x).strip() for x in (file_ids or []) if str(x).strip()])
    if n <= 0 or case_file_count <= 0:
        return False
    return n >= int(case_file_count)


def _resolve_small_case_scope(
    *,
    db: Session,
    case_id: str,
    question: str,
    case_file_count: int,
) -> Optional[RetrievalTask]:
    """Try scoped retrieval before full-corpus fallback on small cases."""
    q = question.strip()

    from app.services.file_summary_index import file_summary_index_enabled, resolve_file_scope

    if file_summary_index_enabled():
        try:
            scope_result = resolve_file_scope(
                db,
                case_id=str(case_id),
                question=q,
                case_file_count=case_file_count,
            )
            if (
                scope_result.file_ids
                and scope_result.scope_hint in ("resolved", "relaxed")
                and not _is_near_full_case_scope(scope_result.file_ids, case_file_count)
            ):
                return _task_from_summary_scope(
                    q,
                    file_ids=scope_result.file_ids,
                    reason=scope_result.reason,
                    top_score=scope_result.top_score,
                    scope_hint=scope_result.scope_hint,
                )
            if scope_result.file_ids and _is_near_full_case_scope(
                scope_result.file_ids, case_file_count
            ):
                logger.info(
                    "[CaseRouter] small_case summary covers all %s files → skip (need LLM)",
                    case_file_count,
                )
        except Exception as exc:
            logger.debug("Small case summary scope failed: %s", exc)

    try:
        from app.services.chat.case_file_catalog_cache import get_case_file_catalog_cached

        catalog = get_case_file_catalog_cached(
            db,
            case_id,
            limit=max(5, case_file_count + 2),
        )
        ref_task = _try_document_ref_scope(catalog, q)
        if ref_task is not None:
            return ref_task
        matched = _match_catalog_files_by_question(catalog, q)
        if matched and not _is_near_full_case_scope(matched, case_file_count):
            return RetrievalTask(
                search_query=q,
                file_ids=matched,
                scope_mode="resolved",
                confidence=0.78,
                rationale="small_case_filename_match",
                within_file_expand=True,
            )
    except Exception as exc:
        logger.debug("Small case catalog match failed: %s", exc)

    return None


def _router_min_confidence() -> float:
    return float(getattr(config, "CASE_ASSISTANT_ROUTER_MIN_CONFIDENCE", 0.55) or 0.55)


def _full_case_min_confidence() -> float:
    return float(
        getattr(config, "CASE_ASSISTANT_ROUTER_FULL_CASE_MIN_CONFIDENCE", 0.72) or 0.72
    )


def _llm_scope_max_files() -> int:
    return max(
        1,
        int(
            getattr(config, "CASE_ASSISTANT_ROUTER_LLM_MAX_FILES", 0) or 0
        )
        or int(getattr(config, "CASE_ASSISTANT_FILE_SUMMARY_MAX_FILES", 20) or 20),
    )


def _llm_scope_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_LLM_ROUTER_ENABLED", True))


def _llm_secondary_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_LLM_ROUTER_FALLBACK_ENABLED", True))


def _task_from_summary_scope(
    question: str,
    *,
    file_ids: List[str],
    reason: str,
    top_score: float,
    scope_hint: str,
) -> RetrievalTask:
    conf = min(0.95, max(0.65, top_score))
    if scope_hint == "resolved":
        conf = min(0.95, max(0.72, top_score))
    return RetrievalTask(
        search_query=question.strip(),
        file_ids=list(file_ids),
        scope_mode="summary_hybrid",
        confidence=conf,
        rationale=f"file_summary_{reason}",
    )


def _normalize_llm_task(
    task: RetrievalTask,
    *,
    catalog: List[CaseFileCatalogEntry],
    question: str,
) -> RetrievalTask:
    valid_ids = {e.file_id for e in catalog}
    file_ids = [x for x in task.file_ids if x in valid_ids][:_llm_scope_max_files()]
    search_query = str(task.search_query or question).strip() or question.strip()
    scope_mode = task.scope_mode
    if scope_mode not in (
        "attached",
        "resolved",
        "doc_type",
        "full_case",
        "passport",
        "summary_hybrid",
    ):
        scope_mode = "resolved" if file_ids else "full_case"
    doc_type = str(task.doc_type).strip() if task.doc_type else None
    if doc_type == "":
        doc_type = None
    return RetrievalTask(
        search_query=search_query,
        file_ids=file_ids,
        doc_type=doc_type,
        scope_mode=scope_mode,
        confidence=float(task.confidence or 0.5),
        rationale=str(task.rationale or "llm_scope"),
        within_file_expand=bool(task.within_file_expand) or bool(file_ids),
    )


def _accept_llm_task(task: RetrievalTask, *, question: str) -> Optional[RetrievalTask]:
    min_conf = _router_min_confidence()
    full_case_conf = _full_case_min_confidence()

    if task.file_ids and task.confidence >= min_conf:
        task.scope_mode = "resolved"
        task.rationale = f"llm_scope_{task.rationale or 'resolved'}"
        task.within_file_expand = True
        return task

    if task.doc_type and task.scope_mode == "doc_type" and task.confidence >= min_conf:
        task.rationale = f"llm_scope_{task.rationale or 'doc_type'}"
        return task

    if task.scope_mode == "full_case" and task.confidence >= full_case_conf:
        task.rationale = f"llm_scope_{task.rationale or 'full_case_explicit'}"
        return task

    if (
        str(task.search_query or "").strip()
        and str(task.search_query).strip() != question.strip()
        and task.confidence >= min_conf
    ):
        task.rationale = f"llm_scope_{task.rationale or 'query_rewrite_only'}"
        return task

    return None


def _llm_scope_ready(*, allow_llm_scope: bool, llm) -> bool:
    return bool(
        allow_llm_scope
        and _llm_scope_enabled()
        and llm
        and _llm_secondary_enabled()
    )


class CaseRetrievalRouter:
    """Maps natural language questions to scoped retrieval tasks."""

    def __init__(self, llm=None):
        self.llm = llm

    def route(
        self,
        *,
        question: str,
        case_id: str,
        db: Session,
        attached_file_ids: Optional[List[str]] = None,
        document_id: Optional[str] = None,
        corpus_size: int = 0,
        editor_attach_only: bool = False,
        allow_llm_scope: bool = True,
    ) -> RetrievalTask:
        q = (question or "").strip()
        if not q:
            return RetrievalTask(
                search_query="",
                scope_mode="full_case",
                confidence=0.0,
                rationale="empty_question",
            )

        attached = [str(x).strip() for x in (attached_file_ids or []) if str(x).strip()]
        if attached:
            return RetrievalTask(
                search_query=q,
                file_ids=attached,
                scope_mode="attached",
                confidence=0.98,
                rationale="attached_file_ids",
                within_file_expand=True,
            )

        if editor_attach_only:
            return RetrievalTask(
                search_query=q,
                file_ids=[],
                scope_mode="attached",
                confidence=0.99,
                rationale="editor_no_attachments",
            )

        doc_id = str(document_id).strip() if document_id else ""
        if doc_id:
            return RetrievalTask(
                search_query=q,
                file_ids=[doc_id],
                scope_mode="resolved",
                confidence=0.85,
                rationale="active_document_id",
                within_file_expand=True,
            )

        try:
            case_file_count = _count_case_files(db, case_id)
        except Exception:
            case_file_count = corpus_size or 0

        from app.services.chat.case_file_catalog_cache import get_case_file_catalog_cached

        catalog = get_case_file_catalog_cached(
            db,
            case_id,
            limit=int(
                getattr(config, "CASE_ASSISTANT_ROUTER_MAX_CATALOG_FILES", 80) or 80
            )
            if not _is_small_case(case_file_count)
            else max(5, case_file_count + 2),
        )

        # Document-number resolve runs before summary hybrid / LLM (FAST-safe).
        ref_task = _try_document_ref_scope(catalog, q)
        if ref_task is not None:
            logger.info(
                "[CaseRouter] document_ref files=%s refs_bound=1",
                len(ref_task.file_ids),
            )
            return ref_task

        llm_ready = _llm_scope_ready(allow_llm_scope=allow_llm_scope, llm=self.llm)
        llm_search_query = q

        if _is_small_case(case_file_count):
            scoped = _resolve_small_case_scope(
                db=db,
                case_id=case_id,
                question=q,
                case_file_count=case_file_count,
            )
            if scoped is not None:
                logger.info(
                    "[CaseRouter] small_case scoped mode=%s files=%s reason=%s",
                    scoped.scope_mode,
                    len(scoped.file_ids),
                    scoped.rationale,
                )
                return scoped
            # Same secretary as large cases: lite LLM picks file(s) before full corpus.
            if llm_ready:
                llm_hit, rewrite = self._try_llm_scope(
                    question=q,
                    catalog=catalog,
                    corpus_size=corpus_size or case_file_count,
                )
                if rewrite:
                    llm_search_query = rewrite
                if llm_hit is not None:
                    return llm_hit
            logger.info(
                "[CaseRouter] small_case files=%s → full_corpus chunk search",
                case_file_count,
            )
            return _small_case_task(q)

        from app.services.file_summary_index import (
            FileScopeResult,
            file_summary_index_enabled,
            resolve_file_scope,
        )

        scope_result: Optional[FileScopeResult] = None
        if file_summary_index_enabled():
            scope_result = resolve_file_scope(
                db,
                case_id=str(case_id),
                question=q,
                case_file_count=case_file_count,
            )
            if scope_result.file_ids and scope_result.scope_hint == "resolved":
                if _is_near_full_case_scope(scope_result.file_ids, case_file_count):
                    logger.info(
                        "[CaseRouter] summary_hybrid covers all %s files → llm/relaxed",
                        case_file_count,
                    )
                else:
                    logger.info(
                        "[CaseRouter] summary_hybrid files=%s top=%.2f reason=%s",
                        len(scope_result.file_ids),
                        scope_result.top_score,
                        scope_result.reason,
                    )
                    task = _task_from_summary_scope(
                        q,
                        file_ids=scope_result.file_ids,
                        reason=scope_result.reason,
                        top_score=scope_result.top_score,
                        scope_hint=scope_result.scope_hint,
                    )
                    task.within_file_expand = True
                    return task

            logger.info(
                "[CaseRouter] summary miss hint=%s reason=%s top=%.2f → llm/relaxed",
                scope_result.scope_hint,
                scope_result.reason,
                scope_result.top_score,
            )

        if llm_ready:
            llm_hit, rewrite = self._try_llm_scope(
                question=q,
                catalog=catalog,
                corpus_size=corpus_size or case_file_count,
            )
            if rewrite:
                llm_search_query = rewrite
            if llm_hit is not None:
                return llm_hit

        if scope_result is not None and scope_result.file_ids and scope_result.scope_hint == "relaxed":
            logger.info(
                "[CaseRouter] relaxed_summary files=%s reason=%s top=%.2f",
                len(scope_result.file_ids),
                scope_result.reason,
                scope_result.top_score,
            )
            task = _task_from_summary_scope(
                q,
                file_ids=scope_result.file_ids,
                reason=scope_result.reason,
                top_score=scope_result.top_score,
                scope_hint=scope_result.scope_hint,
            )
            if llm_search_query != q:
                task.search_query = llm_search_query
                task.rationale = f"{task.rationale}_llm_query_rewrite"
            return task

        if scope_result is not None and scope_result.scope_hint == "miss" and not scope_result.candidates:
            logger.info("[CaseRouter] no summary signal → full_case (index empty or unavailable)")
            return RetrievalTask(
                search_query=llm_search_query,
                scope_mode="full_case",
                confidence=0.45,
                rationale="no_summary_index_signal",
            )

        logger.info("[CaseRouter] weak scope signals → cautious full_case")
        return RetrievalTask(
            search_query=llm_search_query,
            scope_mode="full_case",
            confidence=0.4,
            rationale="weak_scope_fallback",
        )

    def _try_llm_scope(
        self,
        *,
        question: str,
        catalog: List[CaseFileCatalogEntry],
        corpus_size: int,
    ) -> tuple[Optional[RetrievalTask], Optional[str]]:
        """
        Lite LLM catalog secretary.

        Returns (accepted_task_or_None, rewritten_query_or_None).
        Rewrite is kept even when the task is rejected, so relaxed/full_case
        fallbacks can still use the improved search_query.
        """
        try:
            raw_llm = self._route_with_llm(
                question=question,
                catalog=catalog,
                corpus_size=corpus_size,
            )
            llm_task = _normalize_llm_task(raw_llm, catalog=catalog, question=question)
            rewritten = str(llm_task.search_query or "").strip()
            rewrite_out = rewritten if rewritten and rewritten != question.strip() else None
            accepted = _accept_llm_task(llm_task, question=question)
            if accepted is not None:
                logger.info(
                    "[CaseRouter] llm_scope mode=%s files=%s conf=%.2f",
                    accepted.scope_mode,
                    len(accepted.file_ids),
                    accepted.confidence,
                )
            return accepted, rewrite_out
        except Exception as e:
            logger.warning("LLM retrieval scope failed: %s", e)
            return None, None

    def _route_with_llm(
        self,
        *,
        question: str,
        catalog: List[CaseFileCatalogEntry],
        corpus_size: int,
    ) -> RetrievalTask:
        from langchain_core.messages import HumanMessage, SystemMessage

        max_files = _llm_scope_max_files()
        catalog_json = json.dumps(
            [e.model_dump() for e in catalog[:80]],
            ensure_ascii=False,
        )[:12000]

        system = f"""Ты маршрутизатор поиска по документам юридического дела.
Не отвечай на вопрос юриста. Верни только JSON:
{{
  "search_query": "краткий поисковый запрос без лишних слов",
  "file_ids": ["uuid", ...],
  "doc_type": "contract" или null,
  "scope_mode": "resolved" | "doc_type" | "full_case",
  "confidence": 0.0-1.0,
  "rationale": "кратко"
}}
Правила:
- file_ids: id из каталога (до {max_files}), если ответ скорее в конкретных документах.
- Смотри и filename, и summary: «претензия» ≠ «встречный иск» ≠ «позиция/пояснения» ≠ «договор», даже если стороны и суммы похожи.
- Если вопрос явно про претензию / встречный иск / позицию / отзыв / договор — выбирай соответствующий файл.
- doc_type: если вопрос про все документы одного типа (например все договоры) — без file_ids.
- scope_mode=full_case только если нужен обзор по всему делу, сравнение всех документов или явно неясно где искать.
- search_query: суть для полнотекстового/семантического поиска по чанкам.
- confidence: насколько уверен в выборе scope (не в ответе на вопрос).
"""
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=(
                    f"В деле файлов: {corpus_size or len(catalog)}.\n"
                    f"Каталог:\n{catalog_json}\n\n"
                    f"Вопрос юриста: {question}"
                )
            ),
        ]

        parsed: Optional[RetrievalTask] = None
        if hasattr(self.llm, "with_structured_output"):
            try:
                structured = self.llm.with_structured_output(RetrievalTask)
                parsed = structured.invoke(messages)
            except Exception:
                parsed = None

        if parsed is None:
            resp = self.llm.invoke(messages)
            text = resp.content if hasattr(resp, "content") else str(resp)
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                data = json.loads(m.group())
                parsed = RetrievalTask.model_validate(data)

        if parsed is None:
            raise ValueError("Could not parse router LLM output")

        return _normalize_llm_task(parsed, catalog=catalog, question=question)


def create_case_retrieval_router():
    """Factory with optional Yandex lite LLM for large-corpus scope resolution."""
    llm = None
    if _llm_scope_enabled():
        try:
            from app.services.llm_factory import create_llm

            model = getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "") or "yandexgpt-lite/latest"
            llm = create_llm(model=model, temperature=0.0, max_tokens=256)
        except Exception as e:
            logger.warning("Could not init router LLM: %s", e)
    return CaseRetrievalRouter(llm=llm)


def resolve_scoped_file_ids(task: RetrievalTask) -> Optional[List[str]]:
    """Return file_ids for pgvector filter, or None for full-case search."""
    if task.file_ids:
        return list(task.file_ids)
    return None


def build_metadata_filter(task: RetrievalTask) -> Optional[Dict[str, Any]]:
    """Build pgvector metadata filter from retrieval task."""
    if task.file_ids:
        ids = [str(x) for x in task.file_ids if str(x).strip()]
        if len(ids) == 1:
            return {"file_id": ids[0]}
        return {"file_id": ids}
    if task.doc_type:
        return {"doc_type": str(task.doc_type).strip()}
    return None


def merge_metadata_filters(
    base: Optional[Dict[str, Any]],
    extra: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Merge pgvector JSONB filters (AND semantics)."""
    out: Dict[str, Any] = dict(base or {})
    for key, value in dict(extra or {}).items():
        if value is None:
            continue
        out[key] = value
    return out or None
