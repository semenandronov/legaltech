"""Layer 2: parallel isolated per-file extraction."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_pipeline.case_retrieval import fetch_file_text_for_extraction, get_rag_service
from app.services.draft_pipeline.extraction_schemas import (
    extraction_prompt_for_schema,
    schema_name_for_role,
)
from app.services.draft_pipeline.json_utils import parse_llm_json_object
from app.services.draft_pipeline.schemas import (
    DocumentExtractionRecord,
    DocumentTriageResult,
    DraftTaskPlan,
    TriagedFile,
)
from app.services.draft_pipeline.worker_db import worker_db_session
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def _search_query_for_file(tf: TriagedFile, task_plan: DraftTaskPlan) -> str:
    for sq in task_plan.sub_queries or []:
        if sq.role == tf.role:
            return sq.search_query
    return f"{tf.filename} {tf.role} {tf.doc_type}"


def _extract_one_file(
    *,
    case_id: str,
    tf: TriagedFile,
    search_query: str,
    db: Optional[Session],
) -> DocumentExtractionRecord:
    rag = get_rag_service()
    with worker_db_session(db) as worker_db:
        text = fetch_file_text_for_extraction(
            rag_service=rag,
            case_id=case_id,
            file_id=tf.file_id,
            search_query=search_query,
            db=worker_db,
        )
    schema_name = schema_name_for_role(tf.role)
    if not text.strip():
        return DocumentExtractionRecord(
            file_id=tf.file_id,
            filename=tf.filename,
            role=tf.role,
            doc_type=tf.doc_type,
            schema_name=schema_name,
            confidence="missing",
        )

    schema_prompt = extraction_prompt_for_schema(schema_name)
    user_block = f"ФАЙЛ: {tf.filename}\nРОЛЬ: {tf.role}\n\nТЕКСТ:\n{text[:10000]}"

    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        resp = llm.invoke(
            [HumanMessage(content=f"{schema_prompt}\n\n{user_block}\n\nВерни только JSON.")]
        )
        raw = resp.content if hasattr(resp, "content") else str(resp)
        parsed = parse_llm_json_object(raw) or {}
        conf = "high" if parsed else "partial"
        return DocumentExtractionRecord(
            file_id=tf.file_id,
            filename=tf.filename,
            role=tf.role,
            doc_type=tf.doc_type,
            schema_name=schema_name,
            payload=parsed,
            confidence=conf,  # type: ignore[arg-type]
        )
    except Exception as exc:
        logger.warning("[draft_pipeline.extract] file=%s failed: %s", tf.file_id, exc)
        return DocumentExtractionRecord(
            file_id=tf.file_id,
            filename=tf.filename,
            role=tf.role,
            doc_type=tf.doc_type,
            schema_name=schema_name,
            confidence="missing",
        )


def run_parallel_extraction(
    *,
    db: Session,
    case_id: str,
    task_plan: DraftTaskPlan,
    triage: DocumentTriageResult,
) -> List[DocumentExtractionRecord]:
    """Map: one isolated LLM extraction per triaged file."""
    targets: List[TriagedFile] = list(triage.core_files) + list(triage.sidebar_files)
    if not targets:
        return []

    max_workers = min(len(targets), max(1, int(getattr(config, "DRAFT_EXTRACT_MAX_PARALLEL", 4) or 4)))
    results: List[DocumentExtractionRecord] = []

    def _job(tf: TriagedFile) -> DocumentExtractionRecord:
        q = _search_query_for_file(tf, task_plan)
        return _extract_one_file(case_id=case_id, tf=tf, search_query=q, db=db)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_job, tf): tf.file_id for tf in targets}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                fid = futures[fut]
                logger.error("[draft_pipeline.extract] parallel error file=%s: %s", fid, exc)

    logger.info("[draft_pipeline.extract] records=%s files=%s", len(results), len(targets))
    return results
