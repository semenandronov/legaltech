#!/usr/bin/env python3
"""Детальные замеры пайплайна справочника: planner → retrieval stages → LLM."""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.chat.legal_query_plan import plan_coverage, plan_is_sufficient
from app.services.chat.legal_retrieval_agent import (
    _cap_search_queries_from_plan,
    _expand_with_norm_graph,
    _fetch_graph_cluster_for_plan,
    _fetch_norm_tree_for_plan,
    _fetch_required_articles_fast,
    _format_context_with_budget,
    _gap_fill_missing_articles,
    _iterative_followup_bounded,
    _maybe_plenum_supplement,
    _rank_documents_for_plan,
    _skip_rerank_on_fast_path,
    _wall_ms,
    run_legal_corpus_retrieval,
)
from app.services.chat.legal_retrieval_planner import resolve_legal_retrieval_plan
from app.services.legal_corpus_service import (
    _collect_hybrid_primary_docs,
    _dedup_extend_in_order,
    _extract_article_query_parts,
    _maybe_rerank_legal_pool,
    _run_fts_bm25_search,
    _run_lexical_search,
    _trim_to_recall_cap,
    count_corpus_chunks,
)
from app.services.llm_factory import create_llm, user_facing_llm_reasoning_kwargs

GARANT_SYSTEM = """# РОЛЬ
Ты — практикующий юрист по российскому праву (режим «СПРАВОЧНИК»).

# ОБЯЗАТЕЛЬНЫЕ ОГРАНИЧЕНИЯ
- Используй только материалы из блока «СПРАВОЧНЫЙ ПРАВОВОЙ КОНТЕКСТ». Не опирайся на внешние знания.
- Не выдумывай нормы и формулировки.
- Если данных недостаточно, напиши: «Недостаточно данных в предоставленных материалах» и укажи, каких статей не хватает.
- Каждый существенный тезис подтверждай ссылкой на статью/пункт из контекста.

# СТИЛЬ
Официально-деловой, конкретный, на русском."""


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def profile_retrieve_legal_corpus_documents(
    query: str,
    *,
    k: int,
    instrument_ids: List[str],
    search_queries: List[str],
    skip_rerank: bool,
) -> Tuple[List[Document], Dict[str, Any]]:
    """Повторяет retrieve_legal_corpus_documents с разбивкой по этапам."""
    timing: Dict[str, Any] = {"hybrid_queries": [], "skip_rerank": skip_rerank}
    recall_cap = int(getattr(config, "LEGAL_CORPUS_RECALL_MAX", 30) or 30)
    effective_final = max(1, k)
    k_eff = max(effective_final, 8)
    wide_cap = max(recall_cap * 4, 64, k_eff * 4)

    raw_qs: List[str] = []
    if not search_queries:
        raw_qs.append(query)
    raw_qs.extend([s for s in search_queries if (s or "").strip()])
    unique_queries: List[str] = []
    seen_ql = set()
    for sq in raw_qs:
        t = (sq or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen_ql:
            continue
        seen_ql.add(low)
        unique_queries.append(t)
    if not unique_queries:
        unique_queries = [(query or "").strip() or " "]
    timing["unique_queries_n"] = len(unique_queries)

    t0 = time.monotonic()
    primary_docs = _collect_hybrid_primary_docs(
        unique_queries,
        k_eff=k_eff,
        instrument_ids=instrument_ids,
        wide_cap=wide_cap,
    )
    timing["hybrid_total_ms"] = _ms(t0)
    timing["hybrid_parallel"] = bool(getattr(config, "LEGAL_CORPUS_HYBRID_PARALLEL", True))
    timing["hybrid_queries"] = [
        {"query": sq[:120], "pool_after": len(primary_docs)} for sq in unique_queries
    ]

    parts = _extract_article_query_parts(query)
    has_article_intent = bool(parts.get("article") or parts.get("code"))
    need_supplement = has_article_intent or not primary_docs
    timing["need_supplement"] = need_supplement

    bm25_docs: List[Document] = []
    lexical_docs: List[Document] = []
    if need_supplement:
        t0 = time.monotonic()
        try:
            bm25_docs = _run_fts_bm25_search(
                query, limit=max(effective_final * 3, 24), instrument_ids=instrument_ids
            )
        except Exception as exc:
            timing["bm25_error"] = str(exc)
        timing["bm25_ms"] = _ms(t0)

        t0 = time.monotonic()
        try:
            lexical_docs = _run_lexical_search(
                query, limit=max(effective_final * 3, 24), instrument_ids=instrument_ids
            )
        except Exception as exc:
            timing["lexical_error"] = str(exc)
        timing["lexical_ms"] = _ms(t0)

    combined: List[Document] = list(primary_docs)
    _dedup_extend_in_order(combined, bm25_docs, wide_cap)
    _dedup_extend_in_order(combined, lexical_docs, wide_cap)
    timing["pool_before_trim"] = len(combined)

    if not combined:
        timing["total_ms"] = int(timing.get("hybrid_total_ms") or 0)
        return [], timing

    t0 = time.monotonic()
    trimmed = _trim_to_recall_cap(combined, recall_cap)
    timing["trim_ms"] = _ms(t0)
    timing["pool_after_trim"] = len(trimmed)

    t0 = time.monotonic()
    out = _maybe_rerank_legal_pool(query, trimmed, top_k=effective_final, skip_rerank=skip_rerank)
    timing["rerank_ms"] = _ms(t0)
    timing["final_docs"] = len(out)
    timing["total_ms"] = (
        int(timing.get("hybrid_total_ms") or 0)
        + int(timing.get("bm25_ms") or 0)
        + int(timing.get("lexical_ms") or 0)
        + int(timing.get("trim_ms") or 0)
        + int(timing.get("rerank_ms") or 0)
    )
    return out, timing


def profile_agent_stages(question: str) -> Dict[str, Any]:
    """Пошаговый профиль run_legal_corpus_retrieval (без дублирования LLM)."""
    report: Dict[str, Any] = {"question": question}
    t_total = time.monotonic()

    ctx_k = int(getattr(config, "LEGAL_CORPUS_CONTEXT_K", 8) or 8)
    max_c = int(getattr(config, "LEGAL_CORPUS_MAX_CONTEXT_CHARS", 14000) or 14000)
    deadline = time.monotonic() + (_wall_ms() / 1000.0)

    t0 = time.monotonic()
    plan, planner_source = resolve_legal_retrieval_plan(
        question, instrument_ids=None, legal_research=True, task_type=None
    )
    report["planner"] = {
        "ms": _ms(t0),
        "source": planner_source,
        "topic": plan.topic,
        "required_articles": list(plan.required_articles),
        "search_queries": list(plan.search_queries),
        "instrument_ids": list(plan.instrument_ids or []),
    }

    instrument_ids = list(plan.instrument_ids or [])
    docs: List[Document] = []
    used_fast = False
    used_norm_tree = False
    stages: Dict[str, Any] = {}

    if plan.required_articles and instrument_ids and time.monotonic() < deadline:
        t0 = time.monotonic()
        tree_docs, tree_sufficient = _fetch_norm_tree_for_plan(plan, reference_date=None)
        stages["norm_tree"] = {
            "ms": _ms(t0),
            "docs": len(tree_docs),
            "sufficient": tree_sufficient,
        }
        if tree_docs:
            docs = tree_docs
            used_norm_tree = True
            if tree_sufficient:
                used_fast = True

    if (
        plan.required_articles
        and instrument_ids
        and not plan_is_sufficient(docs, plan)
        and time.monotonic() < deadline
    ):
        t0 = time.monotonic()
        cluster_lim = int(getattr(config, "LEGAL_NORM_GRAPH_CLUSTER_LIMIT", 20) or 20)
        cluster_docs = _fetch_graph_cluster_for_plan(plan, reference_date=None, limit=cluster_lim)
        stages["graph_cluster"] = {"ms": _ms(t0), "docs": len(cluster_docs)}
        if cluster_docs:
            from app.services.chat.legal_retrieval_agent import _merge_documents

            docs = _merge_documents(docs, cluster_docs)

    if not used_norm_tree and plan.required_articles and instrument_ids and time.monotonic() < deadline:
        t0 = time.monotonic()
        fast_docs, used_fast = _fetch_required_articles_fast(plan, question, k=ctx_k)
        stages["fast_path_fts"] = {"ms": _ms(t0), "docs": len(fast_docs), "used_fast": used_fast}
        docs = fast_docs

    hybrid_timing: Dict[str, Any] = {}
    if not plan_is_sufficient(docs, plan) and time.monotonic() < deadline:
        hybrid_qs = _cap_search_queries_from_plan(plan, question)
        skip_rerank = _skip_rerank_on_fast_path(used_fast, docs, plan)
        t0 = time.monotonic()
        hits, hybrid_timing = profile_retrieve_legal_corpus_documents(
            question,
            k=ctx_k,
            instrument_ids=instrument_ids,
            search_queries=hybrid_qs,
            skip_rerank=skip_rerank,
        )
        stages["hybrid_retrieve"] = {"ms": _ms(t0), **hybrid_timing}
        from app.services.chat.legal_retrieval_agent import _merge_documents

        docs = _merge_documents(docs, hits or [])
    else:
        stages["hybrid_retrieve"] = {"skipped": True, "reason": "plan_sufficient"}

    cov = plan_coverage(docs, plan)
    if cov.get("missing") and time.monotonic() < deadline:
        before = len(docs)
        t0 = time.monotonic()
        docs = _gap_fill_missing_articles(docs, plan, question, k=ctx_k, wall_deadline=deadline)
        stages["gap_fill"] = {"ms": _ms(t0), "docs_added": len(docs) - before}

    t0 = time.monotonic()
    docs = _maybe_plenum_supplement(docs, question, plan, k=ctx_k)
    stages["plenum"] = {"ms": _ms(t0), "docs": len(docs)}

    t0 = time.monotonic()
    docs = _rank_documents_for_plan(docs, plan)
    stages["rank"] = {"ms": _ms(t0)}

    sufficient = plan_is_sufficient(docs, plan)
    if not sufficient and time.monotonic() < deadline:
        k_follow = max(2, min(ctx_k, int(getattr(config, "GLOBAL_LEGAL_ITERATIVE_K_PER_QUERY", 6) or 6)))
        missing = list(cov.get("missing") or [])
        t0 = time.monotonic()
        extra = _iterative_followup_bounded(
            question,
            docs,
            instrument_ids,
            k_each=k_follow,
            wall_deadline=deadline,
            missing_articles=missing,
        )
        stages["iterative_det"] = {"ms": _ms(t0), "docs_added": len(extra)}
        if extra:
            from app.services.chat.legal_retrieval_agent import _merge_documents

            docs = _merge_documents(docs, extra)
            sufficient = plan_is_sufficient(docs, plan)

        if not sufficient and time.monotonic() < deadline:
            t0 = time.monotonic()
            extra_llm = _iterative_followup_bounded(
                question,
                docs,
                instrument_ids,
                k_each=k_follow,
                wall_deadline=deadline,
                missing_articles=None,
            )
            stages["iterative_llm"] = {"ms": _ms(t0), "docs_added": len(extra_llm)}
            if extra_llm:
                from app.services.chat.legal_retrieval_agent import _merge_documents

                docs = _merge_documents(docs, extra_llm)

    if docs and time.monotonic() < deadline:
        expand_lim = int(getattr(config, "LEGAL_NORM_GRAPH_EXPAND_LIMIT", 8) or 8)
        before = len(docs)
        t0 = time.monotonic()
        docs = _expand_with_norm_graph(docs, reference_date=None, limit=expand_lim)
        stages["graph_expand"] = {"ms": _ms(t0), "docs_added": len(docs) - before}

    t0 = time.monotonic()
    context, included = _format_context_with_budget(docs, max_chars=max_c, coverage_note="")
    stages["format_context"] = {
        "ms": _ms(t0),
        "doc_count": len(included),
        "context_chars": len(context),
    }

    report["stages"] = stages
    report["coverage"] = plan_coverage(docs, plan)
    report["sufficient"] = plan_is_sufficient(docs, plan)
    report["instrumental_profile_ms"] = _ms(t_total)
    return report


def main() -> int:
    question = (
        "Какой минимальный размер совокупных требований установлен для возбуждения дела о банкротстве "
        "юридического лица (с учетом актуальных изменений в законе) и каков минимальный период просрочки?"
    )
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])

    print("=" * 72)
    print("СПРАВОЧНИК — детальный профиль пайплайна")
    print("=" * 72)
    print(f"Q: {question}\n")

    cfg = {
        "LEGAL_CORPUS_RECALL_MAX": getattr(config, "LEGAL_CORPUS_RECALL_MAX", None),
        "LEGAL_CORPUS_USE_RERANKER": getattr(config, "LEGAL_CORPUS_USE_RERANKER", None),
        "LEGAL_CORPUS_RERANK_TIER": getattr(config, "LEGAL_CORPUS_RERANK_TIER", None),
        "LEGAL_CORPUS_HYBRID_PARALLEL": getattr(config, "LEGAL_CORPUS_HYBRID_PARALLEL", None),
        "CASE_ASSISTANT_RERANK_LIGHT_MODEL": getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MODEL", None),
        "LEGAL_CORPUS_MAX_HYBRID_QUERIES": getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", None),
        "LEGAL_CORPUS_RETRIEVAL_WALL_MS": getattr(config, "LEGAL_CORPUS_RETRIEVAL_WALL_MS", None),
        "GLOBAL_LEGAL_ITERATIVE_RETRIEVAL_ENABLED": getattr(
            config, "GLOBAL_LEGAL_ITERATIVE_RETRIEVAL_ENABLED", None
        ),
        "RERANKER_MODEL_NAME": getattr(config, "RERANKER_MODEL_NAME", None),
        "corpus_chunks": count_corpus_chunks(),
    }
    print("CONFIG:", json.dumps(cfg, ensure_ascii=False, indent=2))

    print("\n--- Этап 1: пошаговый профиль retrieval ---")
    profile = profile_agent_stages(question)
    print(json.dumps(profile, ensure_ascii=False, indent=2))

    print("\n--- Этап 2: run_legal_corpus_retrieval (эталон) ---")
    t0 = time.monotonic()
    retrieval = run_legal_corpus_retrieval(question, legal_research=True)
    retrieval_ms = _ms(t0)
    meta = retrieval.meta or {}
    print(
        json.dumps(
            {
                "retrieval_ms": retrieval_ms,
                "planner_ms": meta.get("planner_ms"),
                "wall_ms": meta.get("wall_ms"),
                "docs": len(retrieval.documents),
                "context_chars": len(retrieval.context or ""),
                "used_fast_path": meta.get("used_fast_path"),
                "hybrid_queries_used": meta.get("hybrid_queries_used"),
                "skip_rerank": meta.get("skip_rerank"),
                "iterative_added": meta.get("iterative_added"),
                "graph_cluster_docs": meta.get("graph_cluster_docs"),
                "graph_expanded": meta.get("graph_expanded"),
                "required_articles": meta.get("required_articles"),
                "sufficient": meta.get("sufficient"),
                "articles_covered": meta.get("articles_covered"),
                "articles_missing": meta.get("articles_missing"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    answer = ""
    llm_ms = 0
    if not (retrieval.context or "").strip():
        answer = "Недостаточно данных: справочник не вернул контекст."
        print("\n--- Этап 3: LLM пропущен (пустой контекст) ---")
    else:
        print("\n--- Этап 3: LLM (garant) ---")
        llm = create_llm(
            temperature=0.1,
            max_tokens=4000,
            **user_facing_llm_reasoning_kwargs(mode="garant"),
        )
        user = (
            f"=== СПРАВОЧНЫЙ ПРАВОВОЙ КОНТЕКСТ (DATA ONLY) ===\n"
            f"<context>\n{retrieval.context}\n</context>\n\n"
            f"Вопрос пользователя:\n{question}"
        )
        t0 = time.monotonic()
        resp = llm.invoke([SystemMessage(content=GARANT_SYSTEM), HumanMessage(content=user)])
        llm_ms = _ms(t0)
        answer = getattr(resp, "content", None) or str(resp)
        print(f"llm_ms={llm_ms}")

    total_ms = retrieval_ms + llm_ms
    print("\n--- СВОДКА ---")
    summary = {
        "retrieval_ms": retrieval_ms,
        "llm_ms": llm_ms,
        "total_ms": total_ms,
        "planner_ms": meta.get("planner_ms"),
        "instrumental_profile_ms": profile.get("instrumental_profile_ms"),
    }
    # Извлечь ключевые подэтапы hybrid
    hybrid = (profile.get("stages") or {}).get("hybrid_retrieve") or {}
    if hybrid.get("hybrid_total_ms") is not None:
        summary["hybrid_total_ms"] = hybrid.get("hybrid_total_ms")
        summary["rerank_ms"] = hybrid.get("rerank_ms")
        summary["bm25_ms"] = hybrid.get("bm25_ms")
        summary["lexical_ms"] = hybrid.get("lexical_ms")
    for key in ("norm_tree", "graph_cluster", "fast_path_fts", "gap_fill", "iterative_det", "iterative_llm", "graph_expand"):
        st = (profile.get("stages") or {}).get(key)
        if isinstance(st, dict) and "ms" in st:
            summary[f"{key}_ms"] = st["ms"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print(f"\n--- ОТВЕТ (первые 2000 символов) ---\n{(answer or '')[:2000]}")

    out_path = Path(__file__).resolve().parents[1] / "tmp" / "spravochnik_pipeline_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "question": question,
                "config": cfg,
                "profile": profile,
                "retrieval_meta": meta,
                "summary": summary,
                "answer_preview": (answer or "")[:4000],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
