#!/usr/bin/env python3
"""Golden eval for case SHAK documents: latency + must_include quality."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
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


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    # unify money: 2 700 000 / 2700000 / 2.700.000
    s = re.sub(r"(\d)[\s.\u00a0](?=\d{3}\b)", r"\1", s)
    # decimal comma used in RU legal text: 0,1% → 0.1%
    s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    return s


def _token_in_answer(token: str, ans_norm: str) -> bool:
    t = _norm(str(token))
    if not t:
        return True
    if t in ans_norm:
        return True
    # Light morphology: must stem as word prefix («эксплуатац» ⊂ «эксплуатировались»).
    if len(t) >= 5:
        stem = t[: max(5, min(8, len(t)))]
        return bool(re.search(rf"(?<![a-zа-яё0-9]){re.escape(stem)}", ans_norm))
    return False


def _parse_sse(events: list[str]) -> dict[str, Any]:
    text_parts: list[str] = []
    content_sync = ""
    citations: list = []
    session_id = ""
    for raw in events:
        if not raw.startswith("data: "):
            continue
        try:
            payload = json.loads(raw.replace("data: ", "", 1).strip())
        except json.JSONDecodeError:
            continue
        t = payload.get("type")
        if t in ("text-delta", "text_delta"):
            text_parts.append(
                str(
                    payload.get("textDelta")
                    or payload.get("text_delta")
                    or payload.get("content")
                    or payload.get("text")
                    or ""
                )
            )
        elif t == "content_sync":
            content_sync = str(payload.get("content") or payload.get("text") or "")
        elif t == "citations":
            citations = list(payload.get("citations") or [])
        elif t == "session":
            session_id = str(payload.get("sessionId") or payload.get("session_id") or "")
    streamed = "".join(text_parts).strip()
    response = (content_sync or streamed).strip()
    return {
        "response": response,
        "streamed_chars": len(streamed),
        "content_sync": bool(content_sync.strip()),
        "citations": citations,
        "session_id": session_id,
    }


def _citation_summaries(citations: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, c in enumerate(citations or [], 1):
        if not isinstance(c, dict):
            continue
        file_name = (
            c.get("file_name")
            or c.get("source_file")
            or c.get("filename")
            or c.get("title")
            or ""
        )
        quote = str(c.get("quote") or c.get("snippet") or c.get("text") or "")
        out.append(
            {
                "n": i,
                "file_name": str(file_name)[:160],
                "page": c.get("page") or c.get("page_start"),
                "source_type": c.get("source_type"),
                "quote_preview": quote[:180],
            }
        )
    return out


def _citation_usage(answer: str, n_citations: int) -> dict[str, Any]:
    markers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer or "")})
    used = [m for m in markers if 1 <= m <= max(1, n_citations)]
    unused = [i for i in range(1, n_citations + 1) if i not in used]
    dangling = [m for m in markers if n_citations and m > n_citations]
    return {
        "markers_in_answer": markers,
        "cited_in_text": used,
        "unused_sources": unused,
        "dangling_markers": dangling,
        "all_sources_used_in_text": bool(n_citations) and not unused,
        "has_citation_markers": bool(markers),
    }


_NOT_FOUND_RE = re.compile(
    r"(не указан|не найден|не содерж|в представленных фрагментах|в предоставленных фрагментах|"
    r"отсутствует|не удалось найти|нет сведений)",
    re.IGNORECASE,
)


def _looks_not_found(answer: str) -> bool:
    return bool(_NOT_FOUND_RE.search(answer or ""))


def _score_answer(item: dict[str, Any], answer: str) -> dict[str, Any]:
    ans = _norm(answer)
    must = item.get("must_include") or []
    must_any = item.get("must_include_any") or []
    must_not = item.get("must_not_include") or []

    hits = []
    misses = []
    for token in must:
        ok = _token_in_answer(str(token), ans)
        (hits if ok else misses).append(token)

    any_ok = True
    if must_any:
        any_ok = any(_token_in_answer(str(t), ans) for t in must_any)

    forbidden_hits = [t for t in must_not if _token_in_answer(str(t), ans)]

    if must:
        cover = len(hits) / max(1, len(must))
    elif must_any:
        cover = 1.0 if any_ok else 0.0
    else:
        cover = 1.0 if ans else 0.0

    passed = cover >= 0.67 and any_ok and not forbidden_hits and bool(ans)
    return {
        "passed": passed,
        "cover": round(cover, 3),
        "hits": hits,
        "misses": misses,
        "any_ok": any_ok,
        "forbidden_hits": forbidden_hits,
    }


async def run_one(
    *,
    db,
    user,
    case_id: str,
    question: str,
    session_id: str,
) -> dict[str, Any]:
    from app.services.chat.case_chat_request_prep import CaseChatPrepParams, prepare_case_chat_request
    from app.services.chat.orchestrator import ChatOrchestrator

    t0 = time.monotonic()
    prep = prepare_case_chat_request(
        db,
        CaseChatPrepParams(
            case_id=case_id,
            question=question,
            current_user=user,
            session_id=session_id,
            draft_mode=False,
            legal_research=False,
            deep_think=False,
            court_practice=False,
        ),
    )
    prep_ms = int((time.monotonic() - t0) * 1000)
    req = prep.chat_request
    req.session_id = session_id
    bp = req.budget_profile or {}
    latency_path = (bp.get("latency_path") or {}) if isinstance(bp, dict) else {}

    orchestrator = ChatOrchestrator(db=db)
    events: list[str] = []
    t1 = time.monotonic()
    first_token_ms = None
    async for ev in orchestrator.process_request(req):
        if first_token_ms is None and (
            '"type": "text-delta"' in ev
            or '"type":"text-delta"' in ev
            or '"type": "text_delta"' in ev
            or '"type":"text_delta"' in ev
        ):
            first_token_ms = int((time.monotonic() - t0) * 1000)
        events.append(ev)
    total_ms = int((time.monotonic() - t0) * 1000)
    gen_ms = int((time.monotonic() - t1) * 1000)
    parsed = _parse_sse(events)
    cites = list(parsed.get("citations") or [])
    return {
        "prep_ms": prep_ms,
        "gen_ms": gen_ms,
        "ttft_ms": first_token_ms,
        "total_ms": total_ms,
        "latency_path": latency_path.get("kind"),
        "latency_reason": latency_path.get("reason"),
        "execution_tier": bp.get("execution_tier"),
        "structured_plane": req.structured_data_plane,
        "router_resolver": (req.structured_data_router_meta or {}).get("resolver"),
        "response": parsed["response"],
        "content_sync": parsed.get("content_sync"),
        "streamed_chars": parsed.get("streamed_chars"),
        "citations": len(cites),
        "citation_sources": _citation_summaries(cites),
        "citation_usage": _citation_usage(parsed["response"], len(cites)),
        "looks_not_found": _looks_not_found(parsed["response"]),
        "session_id": parsed.get("session_id") or session_id,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="comma-separated question ids")
    parser.add_argument(
        "--out",
        default=str(BACKEND_ROOT / "evals" / "case_shak_golden_results.json"),
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
    results: list[dict[str, Any]] = []
    try:
        case = db.query(Case).filter(Case.id == args.case_id).first()
        if not case:
            print(f"ERROR: case {args.case_id} not found")
            return 1
        user = db.query(User).filter(User.id == case.user_id).first()
        if not user:
            print("ERROR: case owner not found")
            return 1

        session_id = str(uuid.uuid4())
        print(f"case={args.case_id} user={user.email} n={len(dataset)} session={session_id}\n")

        for i, item in enumerate(dataset, 1):
            qid = item["id"]
            q = item["question"]
            print(f"[{i}/{len(dataset)}] {qid} {q[:70]}...")
            try:
                run = await run_one(
                    db=db,
                    user=user,
                    case_id=args.case_id,
                    question=q,
                    session_id=session_id,
                )
                if run.get("session_id"):
                    session_id = run["session_id"]
                score = _score_answer(item, run.get("response") or "")
                answer = run.get("response") or ""
                row = {
                    "id": qid,
                    "difficulty": item.get("difficulty"),
                    "question": q,
                    "passed": score["passed"],
                    "cover": score["cover"],
                    "misses": score["misses"],
                    "hits": score.get("hits") or [],
                    "total_ms": run["total_ms"],
                    "prep_ms": run["prep_ms"],
                    "ttft_ms": run["ttft_ms"],
                    "latency_path": run["latency_path"],
                    "execution_tier": run["execution_tier"],
                    "router_resolver": run["router_resolver"],
                    "citations": run["citations"],
                    "citation_sources": run.get("citation_sources") or [],
                    "citation_usage": run.get("citation_usage") or {},
                    "looks_not_found": bool(run.get("looks_not_found")),
                    "false_not_found": bool(
                        run.get("looks_not_found") and not score["passed"]
                    ),
                    "content_sync": bool(run.get("content_sync")),
                    "sla_ok": run["total_ms"] <= int(item.get("max_total_ms") or 30000),
                    "answer_preview": answer[:280],
                    "answer": answer,
                    "expect_latency_path": item.get("expect_latency_path"),
                    "path_ok": (
                        run.get("latency_path") == item.get("expect_latency_path")
                        if item.get("expect_latency_path")
                        else True
                    ),
                }
            except Exception as exc:
                row = {
                    "id": qid,
                    "difficulty": item.get("difficulty"),
                    "question": q,
                    "passed": False,
                    "cover": 0.0,
                    "misses": item.get("must_include") or [],
                    "total_ms": None,
                    "prep_ms": None,
                    "ttft_ms": None,
                    "latency_path": None,
                    "execution_tier": None,
                    "router_resolver": None,
                    "citations": 0,
                    "sla_ok": False,
                    "answer_preview": f"ERROR: {exc}",
                    "expect_latency_path": item.get("expect_latency_path"),
                    "path_ok": False,
                    "error": str(exc)[:400],
                }
                print(f"  ERROR: {exc}")
            results.append(row)
            print(
                f"  pass={row['passed']} cover={row['cover']} "
                f"total={row['total_ms']}ms prep={row['prep_ms']}ms "
                f"path={row['latency_path']} tier={row['execution_tier']} "
                f"cites={row['citations']}"
            )

        totals = [r["total_ms"] for r in results if isinstance(r.get("total_ms"), int)]
        preps = [r["prep_ms"] for r in results if isinstance(r.get("prep_ms"), int)]
        passed_n = sum(1 for r in results if r.get("passed"))
        path_ok_n = sum(1 for r in results if r.get("path_ok"))
        sla_ok_n = sum(1 for r in results if r.get("sla_ok"))
        with_cites = sum(1 for r in results if int(r.get("citations") or 0) > 0)
        cites_used = sum(
            1
            for r in results
            if (r.get("citation_usage") or {}).get("has_citation_markers")
        )
        false_nf = sum(1 for r in results if r.get("false_not_found"))
        summary = {
            "case_id": args.case_id,
            "n": len(results),
            "passed": passed_n,
            "pass_rate": round(passed_n / max(1, len(results)), 3),
            "path_ok": path_ok_n,
            "path_ok_rate": round(path_ok_n / max(1, len(results)), 3),
            "sla_ok": sla_ok_n,
            "sla_ok_rate": round(sla_ok_n / max(1, len(results)), 3),
            "with_citations": with_cites,
            "answers_with_citation_markers": cites_used,
            "false_not_found": false_nf,
            "total_ms_p50": int(statistics.median(totals)) if totals else None,
            "total_ms_avg": int(statistics.mean(totals)) if totals else None,
            "total_ms_max": max(totals) if totals else None,
            "ttft_ms_p50": int(
                statistics.median(
                    [r["ttft_ms"] for r in results if isinstance(r.get("ttft_ms"), int)]
                )
            )
            if any(isinstance(r.get("ttft_ms"), int) for r in results)
            else None,
            "prep_ms_p50": int(statistics.median(preps)) if preps else None,
            "prep_ms_avg": int(statistics.mean(preps)) if preps else None,
            "by_difficulty": {},
        }
        for diff in sorted({r.get("difficulty") or "?" for r in results}):
            subset = [r for r in results if (r.get("difficulty") or "?") == diff]
            st = [r["total_ms"] for r in subset if isinstance(r.get("total_ms"), int)]
            summary["by_difficulty"][diff] = {
                "n": len(subset),
                "passed": sum(1 for r in subset if r.get("passed")),
                "total_ms_p50": int(statistics.median(st)) if st else None,
            }

        out = {"summary": summary, "results": results}
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n" + "=" * 72)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\nWrote {args.out}")
        return 0 if passed_n == len(results) else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
