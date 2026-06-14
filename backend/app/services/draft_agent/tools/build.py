"""Draft agent tools: RAG, legal corpus, calculator, document writer."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, List, Optional

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_agent.document_output import produce_draft_html
from app.services.draft_agent.review import review_draft_html
from app.services.draft_agent.schemas import (
    DraftCalculatorInput,
    DraftCaseSearchInput,
    DraftCourtPracticeSearchInput,
    DraftLegalSearchInput,
    DraftWriteDocumentInput,
)
from app.services.draft_agent.session import DraftAgentSession
from app.services.draft_agent.tools._emit import emit_tool_completed, emit_tool_started
from app.services.draft_agent.writer import persist_draft_document
from app.services.draft_pipeline.financial_calculator import compute_verified_financials
from app.services.draft_pipeline.schemas import ExtractedFacts, FinancialLineItem, PenaltyTerms
from app.services.legal_corpus_service import retrieve_legal_corpus_documents
from app.services.rag_service import RAGService
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)

TOOL_CASE_SEARCH = "draft_case_search"
TOOL_LEGAL_SEARCH = "draft_legal_search"
TOOL_COURT_PRACTICE = "draft_court_practice_search"
TOOL_CALCULATOR = "draft_calculator"
TOOL_WRITE_DOCUMENT = "draft_write_document"

MAX_SNIPPET = 900
_TOOL_TIMEOUT = float(getattr(config, "DRAFT_AGENT_TOOL_TIMEOUT_SEC", 120) or 120)


async def _with_timeout(coro, *, label: str):
    try:
        return await asyncio.wait_for(coro, timeout=_TOOL_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} превысил лимит {_TOOL_TIMEOUT:.0f} с") from exc


def build_draft_agent_tools(
    session: DraftAgentSession,
    *,
    db: Session,
    on_tool_completed: Optional[Callable[[], None]] = None,
) -> List[Any]:
    """Factory: all tools bound to case/session context."""
    ctx = session.ctx
    skips_legal = session.template.skips_legal_tools

    @tool(TOOL_CASE_SEARCH, args_schema=DraftCaseSearchInput)
    async def draft_case_search(
        query: str,
        k: int = 8,
        file_ids: Optional[List[str]] = None,
    ) -> dict:
        """Поиск фактов, цитат, сумм и дат в документах дела (RAG)."""
        payload = DraftCaseSearchInput(query=query, k=k, file_ids=file_ids)
        scope = payload.file_ids if payload.file_ids else list(ctx.file_ids or [])
        k_eff = max(3, min(20, int(payload.k)))
        emit_tool_started(TOOL_CASE_SEARCH, {"query": payload.query[:160], "k": k_eff})

        worker_db = SessionLocal()
        try:

            def _search():
                rag = RAGService()
                return rag.retrieve_context(
                    case_id=ctx.case_id,
                    query=payload.query,
                    k=k_eff,
                    retrieval_strategy="multi_query",
                    db=worker_db,
                    use_hybrid=True,
                    file_ids=scope or None,
                )

            docs = await _with_timeout(asyncio.to_thread(_search), label=TOOL_CASE_SEARCH)
            hits = []
            for doc in docs:
                meta = doc.metadata or {}
                text = (doc.page_content or "").strip()
                if not text:
                    continue
                if len(text) > MAX_SNIPPET:
                    text = text[:MAX_SNIPPET] + "…"
                hits.append(
                    {
                        "file_name": str(meta.get("source_file") or meta.get("source") or "Документ"),
                        "file_id": meta.get("file_id") or meta.get("doc_id"),
                        "page": meta.get("source_page") if meta.get("source_page") is not None else meta.get("page"),
                        "snippet": text,
                    }
                )
            result = {
                "status": "success" if hits else "empty",
                "query": payload.query,
                "hit_count": len(hits),
                "hits": hits,
            }
            emit_tool_completed(
                TOOL_CASE_SEARCH,
                success=bool(hits),
                output_summary=f"{len(hits)} фрагментов по запросу «{payload.query[:80]}»",
            )
            if on_tool_completed:
                on_tool_completed()
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_CASE_SEARCH, success=False, output_summary=str(exc)[:500])
            raise
        finally:
            worker_db.close()

    @tool(TOOL_LEGAL_SEARCH, args_schema=DraftLegalSearchInput)
    async def draft_legal_search(query: str, k: int = 6) -> dict:
        """Поиск норм права в правовом справочнике (кодексы, законы). Только без готового шаблона."""
        if skips_legal:
            return {
                "status": "skipped",
                "message": "Режим шаблона: правовой справочник не нужен — нормы уже в шаблоне.",
            }
        payload = DraftLegalSearchInput(query=query, k=k)
        k_eff = max(2, min(12, int(payload.k)))
        emit_tool_started(TOOL_LEGAL_SEARCH, {"query": payload.query[:160], "k": k_eff})

        try:

            def _search():
                return retrieve_legal_corpus_documents(payload.query, k=k_eff, final_k=k_eff)

            docs = await _with_timeout(asyncio.to_thread(_search), label=TOOL_LEGAL_SEARCH)
            hits = []
            for doc in docs:
                meta = doc.metadata or {}
                text = (doc.page_content or "").strip()
                if not text:
                    continue
                if len(text) > MAX_SNIPPET:
                    text = text[:MAX_SNIPPET] + "…"
                hits.append(
                    {
                        "source": str(meta.get("source_filename") or meta.get("title") or "норма"),
                        "instrument_id": meta.get("instrument_id"),
                        "section": meta.get("section_title"),
                        "snippet": text,
                    }
                )
            result = {
                "status": "success" if hits else "empty",
                "query": payload.query,
                "hit_count": len(hits),
                "hits": hits,
            }
            emit_tool_completed(
                TOOL_LEGAL_SEARCH,
                success=bool(hits),
                output_summary=f"{len(hits)} норм по запросу «{payload.query[:80]}»",
            )
            if on_tool_completed:
                on_tool_completed()
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_LEGAL_SEARCH, success=False, output_summary=str(exc)[:500])
            raise

    @tool(TOOL_COURT_PRACTICE, args_schema=DraftCourtPracticeSearchInput)
    async def draft_court_practice_search(query: str, k: int = 6) -> dict:
        """Поиск судебной практики: позиции судов по похожим спорам. Только без готового шаблона."""
        if skips_legal:
            return {
                "status": "skipped",
                "message": "Режим шаблона: судебная практика не нужна — используй заполнение полей.",
            }
        payload = DraftCourtPracticeSearchInput(query=query, k=k)
        k_eff = max(2, min(12, int(payload.k)))
        emit_tool_started(TOOL_COURT_PRACTICE, {"query": payload.query[:160], "k": k_eff})

        try:

            def _search():
                from app.services.chat.court_practice_planner import plan_court_practice_search_queries
                from app.services.court_practice_service import retrieve_court_practice

                search_queries, _ = plan_court_practice_search_queries(payload.query)
                retrieval = retrieve_court_practice(
                    payload.query,
                    final_k=k_eff,
                    search_queries=search_queries,
                    trace_source="draft_agent",
                    trace_case_id=ctx.case_id,
                )
                return retrieval

            retrieval = await _with_timeout(asyncio.to_thread(_search), label=TOOL_COURT_PRACTICE)
            hits = []
            for doc in retrieval.documents or []:
                meta = doc.metadata or {}
                text = (doc.page_content or "").strip()
                if not text:
                    continue
                if len(text) > MAX_SNIPPET:
                    text = text[:MAX_SNIPPET] + "…"
                hits.append(
                    {
                        "case_number": meta.get("case_number") or meta.get("номер дела"),
                        "court": meta.get("court_name") or meta.get("суд") or meta.get("court"),
                        "judgment_date": meta.get("judgment_date") or meta.get("дата"),
                        "snippet": text,
                    }
                )
            result = {
                "status": "success" if hits else "empty",
                "query": payload.query,
                "hit_count": len(hits),
                "hits": hits,
                "meta": retrieval.meta if hasattr(retrieval, "meta") else {},
            }
            emit_tool_completed(
                TOOL_COURT_PRACTICE,
                success=bool(hits),
                output_summary=f"{len(hits)} актов по запросу «{payload.query[:80]}»",
            )
            if on_tool_completed:
                on_tool_completed()
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_COURT_PRACTICE, success=False, output_summary=str(exc)[:500])
            raise

    @tool(TOOL_CALCULATOR, args_schema=DraftCalculatorInput)
    async def draft_calculator(
        principal_amount: str,
        event_date: str,
        payment_term_business_days: int,
        penalty_rate_percent_per_day: float,
        penalty_end_date: Optional[str] = None,
        partial_payments: Optional[list] = None,
        reason: str = "",
    ) -> dict:
        """Расчёт неустойки и итога иска (детерминированный калькулятор, без LLM-математики)."""
        payload = DraftCalculatorInput(
            principal_amount=principal_amount,
            event_date=event_date,
            payment_term_business_days=payment_term_business_days,
            penalty_rate_percent_per_day=penalty_rate_percent_per_day,
            penalty_end_date=penalty_end_date,
            partial_payments=partial_payments,
            reason=reason,
        )
        emit_tool_started(TOOL_CALCULATOR, {"reason": (payload.reason or "расчёт")[:120]})

        try:
            partials: List[FinancialLineItem] = []
            for p in payload.partial_payments or []:
                if hasattr(p, "model_dump"):
                    d = p.model_dump()
                elif isinstance(p, dict):
                    d = p
                else:
                    continue
                partials.append(
                    FinancialLineItem(
                        amount=str(d.get("amount") or ""),
                        date=d.get("date"),
                        note=d.get("note"),
                    )
                )

            facts = ExtractedFacts(
                document_type="расчёт",
                penalty_terms=PenaltyTerms(
                    act_date=payload.event_date,
                    contract_date=payload.event_date,
                    payment_term_value=payload.payment_term_business_days,
                    payment_term_unit="business_days",
                    penalty_rate_percent_per_day=str(payload.penalty_rate_percent_per_day),
                    principal_amount=payload.principal_amount,
                    penalty_end_date=payload.penalty_end_date,
                    partial_payments=partials,
                ),
                amounts={"основной долг": payload.principal_amount},
            )
            verified = compute_verified_financials(facts)
            if not verified:
                result = {
                    "status": "insufficient_data",
                    "message": "Недостаточно данных для расчёта. Проверьте даты, срок оплаты и ставку.",
                }
                emit_tool_completed(TOOL_CALCULATOR, success=False, output_summary=result["message"])
                return result

            result = {
                "status": "success",
                "payment_deadline": verified.payment_deadline,
                "penalty_start_date": verified.penalty_start_date,
                "penalty_end_date": verified.penalty_end_date,
                "penalty_days": verified.penalty_days,
                "principal_outstanding": verified.principal_outstanding,
                "penalty_amount": verified.penalty_amount,
                "total_claim": verified.total_claim,
                "computation_trace": verified.computation_trace,
            }
            emit_tool_completed(
                TOOL_CALCULATOR,
                success=True,
                output_summary=f"Итог: {verified.total_claim} (неустойка {verified.penalty_amount})",
            )
            if on_tool_completed:
                on_tool_completed()
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_CALCULATOR, success=False, output_summary=str(exc)[:500])
            raise

    @tool(TOOL_WRITE_DOCUMENT, args_schema=DraftWriteDocumentInput)
    async def draft_write_document(
        document_instruction: str,
        document_title: Optional[str] = None,
    ) -> dict:
        """Создаёт черновик: заполнение шаблона или полный текст с нуля."""
        payload = DraftWriteDocumentInput(
            document_instruction=document_instruction,
            document_title=document_title,
        )
        emit_tool_started(
            TOOL_WRITE_DOCUMENT,
            {
                "title": (payload.document_title or "")[:80],
                "mode": session.template.mode,
                "template": session.template.template_label or session.template.template_key,
            },
        )

        try:
            title, html, fill_meta = await _with_timeout(
                asyncio.to_thread(
                    lambda: produce_draft_html(
                        db,
                        session=session,
                        document_instruction=payload.document_instruction,
                        document_title=payload.document_title,
                    )
                ),
                label=TOOL_WRITE_DOCUMENT,
            )

            lint = review_draft_html(html)
            if not lint["passed"]:
                msg = "; ".join(lint.get("issues") or [])
                logger.warning("[draft_agent.tools] review issues (non-blocking): %s", msg)

            doc = await _with_timeout(
                asyncio.to_thread(
                    lambda: persist_draft_document(
                        db,
                        case_id=ctx.case_id,
                        user_id=ctx.user_id,
                        title=title,
                        content=html,
                    )
                ),
                label=TOOL_WRITE_DOCUMENT,
            )
            editor_path = f"/cases/{ctx.case_id}/editor/{doc['id']}"
            fill_mode = fill_meta.get("fill_mode", "scratch")
            summary = f"Документ «{doc['title']}» создан"
            if fill_mode == "catalog_fill":
                filled = fill_meta.get("fields_filled")
                total = fill_meta.get("fields_total")
                summary = f"Шаблон заполнен ({filled}/{total} полей): «{doc['title']}»"
            elif fill_mode == "template_guide":
                summary = f"Документ по шаблону «{session.template.template_label or 'образец'}»: «{doc['title']}»"

            result = {
                "status": "completed",
                "document_id": doc["id"],
                "title": doc["title"],
                "preview": doc.get("preview", "")[:500],
                "editor_path": editor_path,
                "fill_mode": fill_mode,
                "template_label": session.template.template_label,
                "review": {
                    "passed": lint["passed"],
                    "gap_count": lint.get("gap_count", 0),
                    "warnings": lint.get("warnings") or [],
                },
                "fill_stats": fill_meta,
            }
            artifact = {
                "type": "document",
                "id": doc["id"],
                "title": doc["title"],
                "path": editor_path,
                "preview": doc.get("preview", "")[:300],
            }
            emit_tool_completed(
                TOOL_WRITE_DOCUMENT,
                success=True,
                output_summary=summary,
                artifact=artifact,
            )
            if on_tool_completed:
                on_tool_completed()
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_WRITE_DOCUMENT, success=False, output_summary=str(exc)[:500])
            raise

    return [
        draft_case_search,
        draft_legal_search,
        draft_court_practice_search,
        draft_calculator,
        draft_write_document,
    ]
