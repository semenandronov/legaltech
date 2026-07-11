#!/usr/bin/env python3
"""Phase latency probe: prep / embed / retrieve / bare LLM / RAG LLM / full orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_CASE_ID = "0604cbe5-d37d-473f-aa90-d4ad7e7a26fc"
DEFAULT_DATASET = BACKEND_ROOT / "evals" / "case_shak_golden.json"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _llm_ttft_and_total(llm, messages: list) -> dict[str, Any]:
    """Measure first-chunk and full completion for a LangChain chat model."""
    t0 = time.monotonic()
    first_ms = None
    chunks: list[str] = []
    try:
        for chunk in llm.stream(messages):
            text = getattr(chunk, "content", None)
            if text is None:
                text = str(chunk)
            if isinstance(text, list):
                text = "".join(
                    (x.get("text") if isinstance(x, dict) else str(x)) for x in text
                )
            text = str(text or "")
            if text and first_ms is None:
                first_ms = _ms(t0)
            chunks.append(text)
        return {
            "ok": True,
            "ttft_ms": first_ms if first_ms is not None else _ms(t0),
            "total_ms": _ms(t0),
            "chars": len("".join(chunks)),
            "error": None,
        }
    except Exception as exc:
        # Fallback: non-streaming invoke
        try:
            t1 = time.monotonic()
            resp = llm.invoke(messages)
            content = getattr(resp, "content", "") or ""
            if isinstance(content, list):
                content = "".join(
                    (x.get("text") if isinstance(x, dict) else str(x)) for x in content
                )
            elapsed = _ms(t1)
            return {
                "ok": True,
                "ttft_ms": elapsed,
                "total_ms": elapsed,
                "chars": len(str(content)),
                "error": f"stream_failed:{type(exc).__name__}",
                "stream_error": str(exc)[:200],
            }
        except Exception as exc2:
            return {
                "ok": False,
                "ttft_ms": None,
                "total_ms": _ms(t0),
                "chars": 0,
                "error": f"{type(exc2).__name__}: {exc2}"[:300],
            }


def run_phases(*, db, user, case_id: str, question: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.chat.case_chat_request_prep import CaseChatPrepParams, prepare_case_chat_request
    from app.services.chat.orchestrator import ChatOrchestrator
    from app.services.llm_factory import create_legal_llm
    from app.services.rag_service import RAGService

    out: dict[str, Any] = {"question": question}

    # 1) Prep
    t = time.monotonic()
    prep = prepare_case_chat_request(
        db,
        CaseChatPrepParams(
            case_id=case_id,
            question=question,
            current_user=user,
            session_id=str(uuid.uuid4()),
            draft_mode=False,
            legal_research=False,
            deep_think=False,
            court_practice=False,
        ),
    )
    out["prep_ms"] = _ms(t)
    req = prep.chat_request
    bp = req.budget_profile or {}
    out["latency_path"] = (bp.get("latency_path") or {}).get("kind") if isinstance(bp, dict) else None
    out["execution_tier"] = bp.get("execution_tier") if isinstance(bp, dict) else None

    rag = RAGService()
    emb = rag.document_processor.vector_store.embeddings

    # 2) Embed query only
    t = time.monotonic()
    try:
        vec = emb.embed_query(question)
        out["embed_ms"] = _ms(t)
        out["embed_dim"] = len(vec) if vec is not None else 0
        out["embed_ok"] = True
    except Exception as exc:
        out["embed_ms"] = _ms(t)
        out["embed_ok"] = False
        out["embed_error"] = f"{type(exc).__name__}: {exc}"[:300]
        vec = None

    # 3) Retrieve only (includes its own embed inside unless we pass embedding)
    t = time.monotonic()
    try:
        docs = rag.retrieve_context(
            case_id=case_id,
            query=question,
            k=8,
            retrieval_strategy="hybrid",
            db=db,
            query_embedding=vec,
        )
        out["retrieve_ms"] = _ms(t)
        out["retrieve_docs"] = len(docs or [])
        out["retrieve_ok"] = True
    except Exception as exc:
        docs = []
        out["retrieve_ms"] = _ms(t)
        out["retrieve_docs"] = 0
        out["retrieve_ok"] = False
        out["retrieve_error"] = f"{type(exc).__name__}: {exc}"[:300]

    context, _ = rag.format_sources_for_prompt_with_docs(
        (docs or [])[:6], max_context_chars=4000
    )
    out["context_chars"] = len(context or "")

    llm = create_legal_llm(temperature=0.0, use_rate_limiting=False, max_tokens=400, streaming=True)

    # 4) Bare LLM (no RAG) — what user likely tested
    bare_messages = [
        SystemMessage(content="Ответь коротко по-русски одним предложением."),
        HumanMessage(content=question),
    ]
    bare = _llm_ttft_and_total(llm, bare_messages)
    out["bare_llm_ttft_ms"] = bare["ttft_ms"]
    out["bare_llm_total_ms"] = bare["total_ms"]
    out["bare_llm_ok"] = bare["ok"]
    out["bare_llm_chars"] = bare["chars"]
    if bare.get("error"):
        out["bare_llm_error"] = bare["error"]

    # 5) LLM with RAG context (same model, realistic prompt size)
    rag_messages = [
        SystemMessage(
            content=(
                "Ты юридический ассистент. Ответь только по фрагментам ниже. "
                "Если данных нет — скажи об этом. Коротко."
            )
        ),
        HumanMessage(content=f"Вопрос: {question}\n\nФрагменты:\n{context or '(пусто)'}"),
    ]
    rag_llm = _llm_ttft_and_total(llm, rag_messages)
    out["rag_llm_ttft_ms"] = rag_llm["ttft_ms"]
    out["rag_llm_total_ms"] = rag_llm["total_ms"]
    out["rag_llm_ok"] = rag_llm["ok"]
    out["rag_llm_chars"] = rag_llm["chars"]
    if rag_llm.get("error"):
        out["rag_llm_error"] = rag_llm["error"]

    # 6) Full orchestrator wall + first text-delta
    req.session_id = str(uuid.uuid4())
    orch = ChatOrchestrator(db=db)
    t0 = time.monotonic()
    first_token_ms = None
    async def _run_orch() -> None:
        nonlocal first_token_ms
        async for ev in orch.process_request(req):
            if first_token_ms is None and "text-delta" in ev:
                first_token_ms = _ms(t0)

    asyncio.get_event_loop().run_until_complete(_run_orch()) if False else None
    return out


async def run_phases_async(*, db, user, case_id: str, question: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.chat.case_chat_request_prep import CaseChatPrepParams, prepare_case_chat_request
    from app.services.chat.orchestrator import ChatOrchestrator
    from app.services.llm_factory import create_legal_llm
    from app.services.rag_service import RAGService

    out: dict[str, Any] = {"question": question}

    t = time.monotonic()
    prep = prepare_case_chat_request(
        db,
        CaseChatPrepParams(
            case_id=case_id,
            question=question,
            current_user=user,
            session_id=str(uuid.uuid4()),
            draft_mode=False,
            legal_research=False,
            deep_think=False,
            court_practice=False,
        ),
    )
    out["prep_ms"] = _ms(t)
    req = prep.chat_request
    bp = req.budget_profile or {}
    out["latency_path"] = (bp.get("latency_path") or {}).get("kind") if isinstance(bp, dict) else None
    out["execution_tier"] = bp.get("execution_tier") if isinstance(bp, dict) else None

    rag = RAGService()
    emb = rag.document_processor.vector_store.embeddings

    t = time.monotonic()
    try:
        vec = emb.embed_query(question)
        out["embed_ms"] = _ms(t)
        out["embed_dim"] = len(vec) if vec is not None else 0
        out["embed_ok"] = True
    except Exception as exc:
        out["embed_ms"] = _ms(t)
        out["embed_ok"] = False
        out["embed_error"] = f"{type(exc).__name__}: {exc}"[:300]
        vec = None

    t = time.monotonic()
    try:
        docs = rag.retrieve_context(
            case_id=case_id,
            query=question,
            k=8,
            retrieval_strategy="hybrid",
            db=db,
            query_embedding=vec,
        )
        out["retrieve_ms"] = _ms(t)
        out["retrieve_docs"] = len(docs or [])
        out["retrieve_ok"] = True
    except Exception as exc:
        docs = []
        out["retrieve_ms"] = _ms(t)
        out["retrieve_docs"] = 0
        out["retrieve_ok"] = False
        out["retrieve_error"] = f"{type(exc).__name__}: {exc}"[:300]

    context, _ = rag.format_sources_for_prompt_with_docs(
        (docs or [])[:6], max_context_chars=4000
    )
    out["context_chars"] = len(context or "")

    llm = create_legal_llm(temperature=0.0, use_rate_limiting=False, max_tokens=400, streaming=True)

    bare = _llm_ttft_and_total(
        llm,
        [
            SystemMessage(content="Ответь коротко по-русски одним предложением."),
            HumanMessage(content=question),
        ],
    )
    out["bare_llm_ttft_ms"] = bare["ttft_ms"]
    out["bare_llm_total_ms"] = bare["total_ms"]
    out["bare_llm_ok"] = bare["ok"]
    out["bare_llm_chars"] = bare["chars"]
    if bare.get("error"):
        out["bare_llm_error"] = bare["error"]

    rag_llm = _llm_ttft_and_total(
        llm,
        [
            SystemMessage(
                content=(
                    "Ты юридический ассистент. Ответь только по фрагментам ниже. "
                    "Если данных нет — скажи об этом. Коротко."
                )
            ),
            HumanMessage(content=f"Вопрос: {question}\n\nФрагменты:\n{context or '(пусто)'}"),
        ],
    )
    out["rag_llm_ttft_ms"] = rag_llm["ttft_ms"]
    out["rag_llm_total_ms"] = rag_llm["total_ms"]
    out["rag_llm_ok"] = rag_llm["ok"]
    out["rag_llm_chars"] = rag_llm["chars"]
    if rag_llm.get("error"):
        out["rag_llm_error"] = rag_llm["error"]

    # Full path: wall until first text-delta + total
    req.session_id = str(uuid.uuid4())
    orch = ChatOrchestrator(db=db)
    t0 = time.monotonic()
    first_token_ms = None
    async for ev in orch.process_request(req):
        if first_token_ms is None and "text-delta" in ev:
            first_token_ms = _ms(t0)
    out["full_ttft_ms"] = first_token_ms
    out["full_total_ms"] = _ms(t0)

    # Sum of isolated phases (not equal to full — different path, but shows where time goes)
    parts = [
        out.get("prep_ms") or 0,
        out.get("embed_ms") or 0,
        out.get("retrieve_ms") or 0,
        out.get("rag_llm_ttft_ms") or 0,
    ]
    out["sum_phases_to_first_token_ms"] = int(sum(parts))
    return out


def _median(vals: list[int | None]) -> int | None:
    clean = [v for v in vals if isinstance(v, int)]
    return int(statistics.median(clean)) if clean else None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--ids", default="g-02,g-03,g-04,g-05,g-06,g-14")
    parser.add_argument(
        "--out",
        default=str(BACKEND_ROOT / "evals" / "case_phase_latency.json"),
    )
    args = parser.parse_args()

    from app.models.case import Case
    from app.models.user import User
    from app.utils.database import SessionLocal

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        dataset = [x for x in dataset if x.get("id") in wanted]
    if args.limit > 0:
        dataset = dataset[: args.limit]

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == args.case_id).first()
        if not case:
            print(f"Case not found: {args.case_id}", file=sys.stderr)
            return 2
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            user = db.query(User).first()
        if not user:
            print("No user found", file=sys.stderr)
            return 2

        results: list[dict[str, Any]] = []
        for i, item in enumerate(dataset, 1):
            qid = item.get("id")
            question = item.get("question") or ""
            print(f"[{i}/{len(dataset)}] {qid}: {question[:80]}", flush=True)
            row = await run_phases_async(
                db=db, user=user, case_id=args.case_id, question=question
            )
            row["id"] = qid
            results.append(row)
            print(
                f"  prep={row.get('prep_ms')} embed={row.get('embed_ms')} "
                f"retrieve={row.get('retrieve_ms')} bare_ttft={row.get('bare_llm_ttft_ms')} "
                f"rag_ttft={row.get('rag_llm_ttft_ms')} full_ttft={row.get('full_ttft_ms')} "
                f"full_total={row.get('full_total_ms')}",
                flush=True,
            )

        summary = {
            "n": len(results),
            "prep_ms_p50": _median([r.get("prep_ms") for r in results]),
            "embed_ms_p50": _median([r.get("embed_ms") for r in results]),
            "retrieve_ms_p50": _median([r.get("retrieve_ms") for r in results]),
            "bare_llm_ttft_ms_p50": _median([r.get("bare_llm_ttft_ms") for r in results]),
            "rag_llm_ttft_ms_p50": _median([r.get("rag_llm_ttft_ms") for r in results]),
            "full_ttft_ms_p50": _median([r.get("full_ttft_ms") for r in results]),
            "full_total_ms_p50": _median([r.get("full_total_ms") for r in results]),
            "sum_phases_p50": _median([r.get("sum_phases_to_first_token_ms") for r in results]),
        }
        payload = {"summary": summary, "results": results}
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n=== SUMMARY (p50) ===", flush=True)
        for k, v in summary.items():
            print(f"  {k}: {v}", flush=True)
        print(f"\nWrote {args.out}", flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
