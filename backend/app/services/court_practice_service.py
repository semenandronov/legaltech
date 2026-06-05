"""Судебная практика: CSV ingest, hybrid retrieval, chat context."""
from __future__ import annotations

import csv
import io
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.documents import Document

from app.config import config
from app.services.court_practice_store import (
    CourtPracticeHit,
    count_chunks,
    count_documents,
    delete_all,
    delete_batch,
    fts_search,
    format_hits_as_context,
    hits_to_citation_documents,
    hybrid_search,
    insert_document_with_chunks,
    list_batches,
)
from app.services.court_practice_text import (
    chunk_act_text,
    extract_case_numbers,
    extract_metadata,
)
from app.services.gigachat_embeddings import get_gigachat_embeddings
from app.services.reranker_service import get_reranker_service
from app.services.chat.rag_passage_utils import passage_for_rerank

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Dict[str, Any]], None]

_TEXT_COLUMNS = (
    "текст документа",
    "text",
    "chunk_text",
    "content",
    "document_text",
    "body",
)
_ID_COLUMNS = ("айди документа", "document_id", "id", "doc_id")
_CASE_COLUMNS = ("номер дела", "case_number", "дело")
_COURT_COLUMNS = ("суд", "court_name", "court")
_DATE_COLUMNS = ("дата", "judgment_date", "date", "дата акта")
_TIER_COLUMNS = ("уровень суда", "court_tier", "tier")

# Экспорт из таблиц без строки заголовков: дело, вид, дата, суд, id, текст
_HEADERLESS_COLUMNS = (
    "номер дела",
    "вид акта",
    "дата",
    "суд",
    "айди документа",
    "текст документа",
)


@dataclass(frozen=True)
class CourtPracticeRetrievalResult:
    context: str
    documents: List[Document]
    hits_count: int
    meta: Dict[str, Any]


def court_practice_uploader_emails() -> set:
    explicit = (getattr(config, "COURT_PRACTICE_UPLOADER_EMAILS", None) or "").strip()
    if explicit:
        return {e.strip().lower() for e in explicit.split(",") if e.strip()}
    from app.services.legal_corpus_service import legal_corpus_uploader_emails

    return legal_corpus_uploader_emails()


def is_court_practice_uploader(user) -> bool:
    if not user or not getattr(user, "email", None):
        return False
    return user.email.strip().lower() in court_practice_uploader_emails()


def assert_giga_embeddings_available() -> None:
    emb = get_gigachat_embeddings()
    if not emb.is_available():
        raise RuntimeError(
            "Индексация судебной практики недоступна: настройте GIGACHAT_CREDENTIALS "
            "(модель EmbeddingsGigaR)."
        )


def _pick_column(row: Dict[str, str], candidates: Sequence[str]) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in candidates:
        val = lowered.get(key.lower())
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _first_csv_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _is_headerless_case_export(text: str) -> bool:
    """Первая ячейка — номер дела (экспорт Google Sheets без заголовка)."""
    first = _first_csv_line(text)
    if not first:
        return False
    head = first.lower()
    if "номер дела" in head or "case_number" in head or "текст документа" in head:
        return False
    try:
        cells = next(csv.reader([first]))
    except csv.Error:
        return False
    if not cells:
        return False
    return bool(extract_case_numbers(cells[0].strip()))


def _parse_positional_csv_rows(
    text: str, *, max_rows: Optional[int] = None
) -> List[Dict[str, str]]:
    reader = csv.reader(io.StringIO(text))
    rows: List[Dict[str, str]] = []
    ncol = len(_HEADERLESS_COLUMNS)
    for i, cells in enumerate(reader):
        if max_rows is not None and i >= max_rows:
            break
        if not cells or not any(str(c or "").strip() for c in cells):
            continue
        padded = list(cells) + [""] * max(0, ncol - len(cells))
        row = {
            _HEADERLESS_COLUMNS[j]: str(padded[j] or "")
            for j in range(ncol)
        }
        rows.append(row)
    return rows


def _parse_csv_rows(content: bytes, *, max_rows: Optional[int] = None) -> List[Dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    if _is_headerless_case_export(text):
        return _parse_positional_csv_rows(text, max_rows=max_rows)

    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict[str, str]] = []
    for i, row in enumerate(reader):
        if max_rows is not None and i >= max_rows:
            break
        if not row:
            continue
        if not any(str(v or "").strip() for v in row.values()):
            continue
        rows.append({str(k): str(v or "") for k, v in row.items() if k is not None})
    return rows


def index_csv_bytes(
    content: bytes,
    *,
    created_by_user_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    max_rows: Optional[int] = None,
    progress_cb: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Индексирует CSV: одна строка = один судебный акт (или документ).
    """
    assert_giga_embeddings_available()
    rows = _parse_csv_rows(content, max_rows=max_rows)
    if not rows:
        raise ValueError("CSV пуст или не содержит данных")

    bid = batch_id or str(uuid.uuid4())
    embeddings = get_gigachat_embeddings()
    total_docs = 0
    total_chunks = 0
    errors: List[Dict[str, str]] = []

    for idx, row in enumerate(rows, start=1):
        try:
            text = _pick_column(row, _TEXT_COLUMNS)
            if not text:
                errors.append({"row": str(idx), "detail": "нет текста документа"})
                continue
            source_id = _pick_column(row, _ID_COLUMNS) or f"row-{idx}"
            meta = extract_metadata(
                text,
                case_number=_pick_column(row, _CASE_COLUMNS) or None,
                court_name=_pick_column(row, _COURT_COLUMNS) or None,
                judgment_date=_pick_column(row, _DATE_COLUMNS) or None,
                court_tier=_pick_column(row, _TIER_COLUMNS) or None,
            )
            prepared = chunk_act_text(text)
            if not prepared:
                errors.append({"row": str(idx), "detail": "не удалось нарезать текст"})
                continue
            texts = [p.chunk_text for p in prepared]
            vectors = embeddings.embed_documents(texts)
            chunk_payload = [
                (p.chunk_index, p.chunk_text, vec)
                for p, vec in zip(prepared, vectors)
            ]
            _, n_chunks = insert_document_with_chunks(
                source_row_id=source_id,
                case_number=meta.case_number,
                cad_case_number=meta.cad_case_number,
                court_name=meta.court_name,
                court_tier=meta.court_tier,
                judgment_date=meta.judgment_date,
                act_kind=meta.act_kind,
                raw_text=text,
                batch_id=bid,
                created_by_user_id=created_by_user_id,
                chunks=chunk_payload,
            )
            total_docs += 1
            total_chunks += n_chunks
            if progress_cb:
                progress_cb(
                    {
                        "event": "row_indexed",
                        "row_index": idx,
                        "total_rows": len(rows),
                        "case_number": meta.case_number,
                        "chunks": n_chunks,
                    }
                )
        except Exception as exc:
            logger.warning("court practice row %s failed: %s", idx, exc)
            errors.append({"row": str(idx), "detail": str(exc)})

    result = {
        "batch_id": bid,
        "documents_indexed": total_docs,
        "chunks_indexed": total_chunks,
        "errors": errors,
        "chunk_count_total": count_chunks(),
        "document_count_total": count_documents(),
    }
    if progress_cb:
        progress_cb({"event": "completed", **result})
    return result


def retrieve_court_practice(
    query: str,
    *,
    final_k: Optional[int] = None,
    use_reranker: Optional[bool] = None,
    search_queries: Optional[List[str]] = None,
    trace_source: str = "retrieve",
    trace_case_id: Optional[str] = None,
) -> CourtPracticeRetrievalResult:
    q = (query or "").strip()
    if not q:
        return CourtPracticeRetrievalResult(context="", documents=[], hits_count=0, meta={})

    if count_chunks() == 0:
        return CourtPracticeRetrievalResult(
            context="",
            documents=[],
            hits_count=0,
            meta={"reason": "empty_index"},
        )

    fk = final_k or int(getattr(config, "COURT_PRACTICE_FINAL_K", 7) or 7)
    rerank_on = (
        use_reranker
        if use_reranker is not None
        else bool(getattr(config, "COURT_PRACTICE_USE_RERANKER", True))
    )
    pipeline_meta: Dict[str, Any] = {
        "final_k": fk,
        "rerank": rerank_on,
        "search_queries": list(search_queries or []),
    }

    from app.services.observability.court_practice_langfuse_tracing import (
        court_practice_detailed_tracing_enabled,
        court_practice_pipeline_trace,
        court_practice_span,
        summarize_documents,
        summarize_hits,
    )

    with court_practice_pipeline_trace(
        query=q,
        search_queries=search_queries,
        final_k=fk,
        use_reranker=rerank_on,
        source=trace_source,
        case_id=trace_case_id,
    ) as pipeline_out:
        t_pipeline = time.monotonic()

        with court_practice_span("embed_query", input_payload={"query": q[:800]}) as embed_out:
            t0 = time.monotonic()
            embeddings = get_gigachat_embeddings()
            query_vec = embeddings.embed_query(q)
            embed_out["latency_ms"] = int((time.monotonic() - t0) * 1000)
            embed_out["embedding_dim"] = len(query_vec or [])

        with court_practice_span("hybrid_search", input_payload={"query": q[:800]}) as hybrid_out:
            t0 = time.monotonic()
            hits = hybrid_search(q, query_vec)
            hybrid_out.update(summarize_hits(hits))
            hybrid_out["latency_ms"] = int((time.monotonic() - t0) * 1000)

        # FTS-only multi-query supplement: widen lexical recall without extra embedding calls.
        extra = [s.strip() for s in (search_queries or []) if isinstance(s, str) and s.strip()]
        extra = [s for s in extra if s.lower() != q.lower()]
        if extra:
            per_q_k = max(4, min(18, int(getattr(config, "COURT_PRACTICE_FTS_SUPPLEMENT_K", 10) or 10)))
            max_q = max(1, min(10, int(getattr(config, "COURT_PRACTICE_QUERY_PLANNER_MAX_QUERIES", 6) or 6)))
            with court_practice_span(
                "fts_supplement",
                input_payload={"queries": extra[:max_q], "per_query_k": per_q_k},
            ) as fts_out:
                t0 = time.monotonic()
                merged_by_id: Dict[str, CourtPracticeHit] = {h.chunk_id: h for h in hits}
                before_n = len(merged_by_id)
                per_query_stats: List[Dict[str, Any]] = []
                for sq in extra[:max_q]:
                    added = 0
                    try:
                        for h in fts_search(sq, per_q_k):
                            if h.chunk_id in merged_by_id:
                                continue
                            merged_by_id[h.chunk_id] = h
                            added += 1
                    except Exception as ex:
                        logger.debug("court_practice fts supplement failed (%s): %s", sq[:80], ex)
                        per_query_stats.append({"query": sq[:120], "error": str(ex)[:200]})
                        continue
                    per_query_stats.append({"query": sq[:120], "new_chunks": added})
                hits = sorted(merged_by_id.values(), key=lambda h: h.score, reverse=True)
                fts_out["latency_ms"] = int((time.monotonic() - t0) * 1000)
                fts_out["queries_run"] = len(per_query_stats)
                fts_out["chunks_before"] = before_n
                fts_out["chunks_after"] = len(merged_by_id)
                fts_out["new_chunks"] = len(merged_by_id) - before_n
                fts_out["per_query"] = per_query_stats
                fts_out.update(summarize_hits(hits))

        if rerank_on and hits:
            rerank_pool_k = int(getattr(config, "COURT_PRACTICE_RERANK_POOL_K", 12) or 12)
            rerank_pool_k = max(1, min(rerank_pool_k, len(hits)))
            rerank_max_chars = int(getattr(config, "COURT_PRACTICE_RERANK_MAX_CHARS", 2400) or 2400)

            with court_practice_span(
                "rerank",
                input_payload={
                    "query": q[:800],
                    "pool_k": rerank_pool_k,
                    "top_k": fk,
                    "max_chars": rerank_max_chars,
                },
                metadata={"pre_rerank_hits": len(hits)},
            ) as rerank_out:
                t0 = time.monotonic()
                rerank_hits = hits[:rerank_pool_k]
                reranker = get_reranker_service()

                docs: List[Document] = []
                for h in rerank_hits:
                    tmp_doc = Document(
                        page_content=h.chunk_text,
                        metadata={"source_file": h.case_number or ""},
                    )
                    docs.append(
                        Document(
                            page_content=passage_for_rerank(tmp_doc, rerank_max_chars),
                            metadata={"chunk_id": h.chunk_id},
                        )
                    )

                reranked = reranker.rerank(q, docs, top_k=fk)
                hit_by_chunk = {h.chunk_id: h for h in hits}
                new_hits = []
                for doc, score in reranked:
                    cid = (doc.metadata or {}).get("chunk_id")
                    base = hit_by_chunk.get(cid)
                    if base:
                        new_hits.append(
                            CourtPracticeHit(
                                chunk_id=base.chunk_id,
                                document_id=base.document_id,
                                case_number=base.case_number,
                                court_name=base.court_name,
                                court_tier=base.court_tier,
                                judgment_date=base.judgment_date,
                                chunk_index=base.chunk_index,
                                chunk_text=base.chunk_text,
                                score=float(score),
                                dense_rank=base.dense_rank,
                                sparse_rank=base.sparse_rank,
                            )
                        )
                hits = new_hits[:fk]
                rerank_out["latency_ms"] = int((time.monotonic() - t0) * 1000)
                rerank_out.update(summarize_hits(hits))
        else:
            hits = hits[:fk]

        with court_practice_span(
            "finalize",
            input_payload={"final_k": fk},
        ) as fin_out:
            context = format_hits_as_context(hits)
            serialized = hits_to_citation_documents(hits)
            documents = [
                Document(page_content=item["page_content"], metadata=item["metadata"])
                for item in serialized
            ]
            fin_out.update(summarize_hits(hits))
            fin_out.update(summarize_documents(documents))

        pipeline_out["total_latency_ms"] = int((time.monotonic() - t_pipeline) * 1000)
        pipeline_out.update(summarize_hits(hits))
        pipeline_out.update(summarize_documents(documents))

    if court_practice_detailed_tracing_enabled():
        logger.info(
            "[CourtPracticeRetrieval] trace ok q=%s hits=%d cases=%s total_ms=%s",
            q[:60],
            len(hits),
            pipeline_out.get("unique_cases"),
            pipeline_out.get("total_latency_ms"),
        )

    return CourtPracticeRetrievalResult(
        context=context,
        documents=documents,
        hits_count=len(hits),
        meta={
            "final_k": fk,
            "rerank": rerank_on,
            "rerank_pool_k": int(getattr(config, "COURT_PRACTICE_RERANK_POOL_K", 12) or 12)
            if rerank_on
            else None,
            "rerank_max_chars": int(getattr(config, "COURT_PRACTICE_RERANK_MAX_CHARS", 2400) or 2400)
            if rerank_on
            else None,
            **{k: v for k, v in pipeline_meta.items() if v is not None},
            **(
                {"trace_total_ms": pipeline_out.get("total_latency_ms")}
                if court_practice_detailed_tracing_enabled()
                else {}
            ),
        },
    )


def get_status() -> Dict[str, Any]:
    return {
        "chunk_count": count_chunks(),
        "document_count": count_documents(),
        "batches": list_batches(),
    }


def remove_batch(batch_id: str):
    return delete_batch(batch_id)


def remove_all():
    return delete_all()
