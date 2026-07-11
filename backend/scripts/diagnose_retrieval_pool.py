#!/usr/bin/env python3
"""Диагностика пула retrieval: article_number до/после trim и rerank."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from langchain_core.documents import Document

from app.config import config
from app.services.chat.legal_retrieval_agent import _cap_search_queries_from_plan
from app.services.chat.legal_retrieval_planner import resolve_legal_retrieval_plan
from app.services.legal_corpus_service import (
    _collect_hybrid_primary_docs,
    _dedup_extend_in_order,
    _extract_article_query_parts,
    _maybe_rerank_legal_pool,
    _run_fts_bm25_search,
    _run_lexical_search,
    _run_norm_hybrid_search,
    _trim_to_recall_cap,
    count_corpus_chunks,
)

TARGET_ARTS = ("3", "33", "213.3")

DEFAULT_QUESTION = (
    "В чем ключевое отличие признаков банкротства гражданина от признаков банкротства "
    "юридического лица при подаче заявления кредитором?"
)


def _art(d: Document) -> str:
    return str((d.metadata or {}).get("article_number") or "").strip() or "?"


def _arts_summary(docs: List[Document]) -> Dict[str, Any]:
    arts = [_art(d) for d in docs]
    c = Counter(arts)
    return {
        "n_chunks": len(docs),
        "unique_articles": len(c),
        "articles": dict(sorted(c.items(), key=lambda x: (x[0] == "?", x[0]))),
    }


def _target_hits(docs: List[Document]) -> Dict[str, bool]:
    present = {_art(d) for d in docs}
    return {t: t in present for t in TARGET_ARTS}


def _per_query_hybrid(
    queries: List[str],
    *,
    k_eff: int,
    instrument_ids: List[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for sq in queries:
        hits = _run_norm_hybrid_search(sq, k=k_eff, instrument_ids=instrument_ids or None) or []
        rows.append(
            {
                "query": sq[:160],
                "hits": len(hits),
                "target_hits": _target_hits(hits),
                "top_articles": [_art(d) for d in hits[:12]],
            }
        )
    return rows


def diagnose(question: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {"question": question, "target_articles": list(TARGET_ARTS)}

    if count_corpus_chunks() == 0:
        report["error"] = "corpus empty — запустите postgres и проиндексируйте корпус"
        return report

    plan, planner_source = resolve_legal_retrieval_plan(
        question, instrument_ids=None, legal_research=True, task_type=None
    )
    instrument_ids = list(plan.instrument_ids or [])
    hybrid_qs = _cap_search_queries_from_plan(plan, question)

    ctx_k = int(getattr(config, "LEGAL_CORPUS_CONTEXT_K", 8) or 8)
    recall_cap = int(getattr(config, "LEGAL_CORPUS_RECALL_MAX", 30) or 30)
    k_eff = max(ctx_k, 8)
    wide_cap = max(recall_cap * 4, 64, k_eff * 4)

    report["config"] = {
        "LEGAL_CORPUS_RECALL_MAX": recall_cap,
        "LEGAL_CORPUS_CONTEXT_K": ctx_k,
        "LEGAL_CORPUS_USE_RERANKER": getattr(config, "LEGAL_CORPUS_USE_RERANKER", None),
        "corpus_chunks": count_corpus_chunks(),
    }
    report["planner"] = {
        "source": planner_source,
        "topic": plan.topic,
        "search_queries": list(plan.search_queries),
        "hybrid_queries_capped": hybrid_qs,
        "instrument_ids": instrument_ids,
    }

    report["per_query_hybrid"] = _per_query_hybrid(
        hybrid_qs, k_eff=k_eff, instrument_ids=instrument_ids
    )

    primary_docs = _collect_hybrid_primary_docs(
        hybrid_qs,
        k_eff=k_eff,
        instrument_ids=instrument_ids or None,
        wide_cap=wide_cap,
    )

    parts = _extract_article_query_parts(question)
    need_supplement = bool(parts.get("article") or parts.get("code")) or not primary_docs
    bm25_docs: List[Document] = []
    lexical_docs: List[Document] = []
    if need_supplement:
        try:
            bm25_docs = _run_fts_bm25_search(
                question, limit=max(ctx_k * 3, 24), instrument_ids=instrument_ids or None
            )
        except Exception as exc:
            report["bm25_error"] = str(exc)
        try:
            lexical_docs = _run_lexical_search(
                question, limit=max(ctx_k * 3, 24), instrument_ids=instrument_ids or None
            )
        except Exception as exc:
            report["lexical_error"] = str(exc)

    combined: List[Document] = list(primary_docs)
    _dedup_extend_in_order(combined, bm25_docs, wide_cap)
    _dedup_extend_in_order(combined, lexical_docs, wide_cap)
    trimmed = _trim_to_recall_cap(combined, recall_cap)

    after_rerank = _maybe_rerank_legal_pool(
        question, trimmed, top_k=ctx_k, skip_rerank=False
    )
    without_rerank = _maybe_rerank_legal_pool(
        question, trimmed, top_k=ctx_k, skip_rerank=True
    )

    report["stages"] = {
        "hybrid_merged": {**_arts_summary(primary_docs), "target_hits": _target_hits(primary_docs)},
        "pool_before_trim": {**_arts_summary(combined), "target_hits": _target_hits(combined)},
        "pool_after_trim_recall_cap": {
            **_arts_summary(trimmed),
            "target_hits": _target_hits(trimmed),
            "recall_cap": recall_cap,
        },
        "after_rerank": {
            **_arts_summary(after_rerank),
            "target_hits": _target_hits(after_rerank),
            "top_articles_ordered": [_art(d) for d in after_rerank],
        },
        "without_rerank_top_k": {
            **_arts_summary(without_rerank),
            "target_hits": _target_hits(without_rerank),
            "top_articles_ordered": [_art(d) for d in without_rerank],
        },
    }

    # Вердикт
    before = report["stages"]["pool_after_trim_recall_cap"]["target_hits"]
    after = report["stages"]["after_rerank"]["target_hits"]
    verdict: List[str] = []
    for art in TARGET_ARTS:
        if not before.get(art) and not after.get(art):
            verdict.append(f"ст. {art}: нет ни в пуле (recall), ни после rerank → проблема HYBRID/RECALL")
        elif before.get(art) and not after.get(art):
            verdict.append(f"ст. {art}: была в пуле, пропала после rerank → проблема RERANK")
        elif not before.get(art) and after.get(art):
            verdict.append(f"ст. {art}: неожиданно появилась после rerank")
        else:
            verdict.append(f"ст. {art}: есть в пуле и в финале ✓")
    report["verdict"] = verdict

    return report


def main() -> int:
    question = DEFAULT_QUESTION
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])

    print("=" * 72)
    print("ДИАГНОСТИКА ПУЛА RETRIEVAL (до/после rerank)")
    print("=" * 72)
    print(f"Q: {question}\n")

    report = diagnose(question)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    out_path = Path(__file__).resolve().parents[1] / "tmp" / "retrieval_pool_diagnosis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nСохранено: {out_path}")

    if report.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
