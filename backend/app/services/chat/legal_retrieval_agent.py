"""
Budgeted legal corpus retrieval (agentic RAG):

  plan (deterministic) → per-article FTS → hybrid → gap-fill → plenum → iterative
  → coverage / sufficiency → context assembly.

Единая точка для case garant и global assistant.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chat.rag_passage_utils import legal_corpus_max_fragment_chars, truncate_passage_body
from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    build_hybrid_queries_from_plan,
    coverage_target_articles,
    doc_metadata_matches_article,
    effective_search_queries,
    is_repeal_only_snippet,
    plan_coverage,
    plan_is_sufficient,
    structured_lookup_articles,
)
from app.services.chat.legal_retrieval_planner import resolve_legal_retrieval_plan

logger = logging.getLogger(__name__)


@dataclass
class LegalRetrievalResult:
    context: str
    documents: List[Document]
    instrument_ids: List[str]
    route_rationale: str
    used_fast_path: bool = False
    coverage_note: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _wall_ms() -> int:
    return max(5000, int(getattr(config, "LEGAL_CORPUS_RETRIEVAL_WALL_MS", 30000) or 30000))


def _max_hybrid_queries(plan: LegalRetrievalPlan) -> int:
    base = max(1, min(8, int(getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", 3) or 3)))
    # facts дают отдельные проходы hybrid — расширяем cap, но не выше 8
    fact_bonus = min(len(plan.facts or []), 3)
    query_count = len(plan.search_queries or []) + fact_bonus
    return max(base, min(query_count, 8))


def _filter_instrument_ids(ids: Optional[List[str]]) -> List[str]:
    return [x for x in (ids or []) if x and str(x).strip().lower() != "unknown"]


def _agentic_plan_enabled() -> bool:
    return bool(getattr(config, "LEGAL_CORPUS_AGENTIC_PLAN_ENABLED", True))


def _format_context_with_budget(
    docs: List[Document],
    *,
    max_chars: int,
    coverage_note: str = "",
) -> Tuple[str, List[Document]]:
    parts: List[str] = []
    included: List[Document] = []
    used = 0
    if coverage_note:
        note_block = f"[Примечание к справочнику]\n{coverage_note}"
        parts.append(note_block)
        used += len(note_block)

    for i, d in enumerate(docs, start=1):
        meta = d.metadata or {}
        fn = meta.get("source_filename", "файл")
        body = truncate_passage_body((d.page_content or "").strip(), legal_corpus_max_fragment_chars())
        block = f"[Справочник — фрагмент {i}, источник: {fn}]\n{body}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        included.append(d)
        used += len(block)
    sep = "\n\n---\n\n" if coverage_note else "\n\n---\n\n"
    return sep.join(parts), included


def article_lookup_fast(
    question: str,
    article: str,
    instrument_ids: List[str],
    *,
    k: int = 8,
) -> List[Document]:
    """FTS/lexical по статье — без hybrid multi-query."""
    if not article or not instrument_ids:
        return []
    from app.services.legal_corpus_service import _run_fts_bm25_search, _run_lexical_search

    fts_q = f"статья {article} {question}".strip()
    limit = max(k * 3, 24)
    docs = _run_fts_bm25_search(fts_q, limit=limit, instrument_ids=instrument_ids)
    if len(docs) < 2:
        docs = _run_lexical_search(fts_q, limit=limit, instrument_ids=instrument_ids)
    return docs[: max(k, 8)] if docs else []


def _doc_mentions_article(doc: Document, article: str) -> bool:
    if doc_metadata_matches_article(doc, article):
        return True
    if not article:
        return False
    import re

    txt = ((doc.page_content or "") + " " + str((doc.metadata or {}).get("section_title") or "")).lower()
    return bool(re.search(rf"(?:ст\.?|статья)\s*{re.escape(article.lower())}\b", txt))


def _merge_documents(existing: List[Document], new_docs: Sequence[Document]) -> List[Document]:
    seen = {(d.page_content or "")[:200] for d in existing}
    out = list(existing)
    for d in new_docs:
        key = (d.page_content or "")[:200]
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _rank_documents_for_plan(
    docs: List[Document],
    plan: LegalRetrievalPlan,
    *,
    question: str = "",
) -> List[Document]:
    """Поднять содержательные фрагменты; закрепить слоты coverage_target_articles в начале."""
    from app.services.legal_instruments import instrument_priority_weight

    targets = set(coverage_target_articles(plan, question))

    def score(doc: Document) -> float:
        text = (doc.page_content or "").strip()
        md = doc.metadata or {}
        s = float(md.get("rerank_score") or md.get("score") or 0.0)
        s += instrument_priority_weight(str(md.get("instrument_id") or "") or None) * 0.35
        art = str(md.get("article_number") or "").strip()
        if art and art in targets:
            s += 5.0
        if md.get("graph_expanded"):
            s += 0.15
        if plan.topic == "article_lookup" and plan.user_articles:
            for art_u in plan.user_articles:
                if _doc_mentions_article(doc, art_u):
                    s += 2.0
                    if is_repeal_only_snippet(text, article=art_u):
                        s -= 3.0
                    elif len(text) >= 400:
                        s += 1.5
        if len(text) >= 600:
            s += 0.5
        return s

    ranked = sorted(docs, key=score, reverse=True)
    if not targets:
        return ranked

    pinned: List[Document] = []
    rest: List[Document] = []
    seen_target: set[str] = set()
    for d in ranked:
        art = str((d.metadata or {}).get("article_number") or "").strip()
        if art and art in targets and art not in seen_target:
            pinned.append(d)
            seen_target.add(art)
        else:
            rest.append(d)
    return pinned + rest


def _parse_reference_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _filter_docs_by_reference_date(
    docs: List[Document],
    reference_date: Optional[date],
) -> List[Document]:
    if reference_date is None or not docs:
        return docs
    from app.services.legal_instruments import instrument_validity
    from app.services.legal_norm_graph import is_norm_valid_on_date

    filtered: List[Document] = []
    for doc in docs:
        md = doc.metadata or {}
        vf = _parse_reference_date(md.get("valid_from"))
        vt = _parse_reference_date(md.get("valid_to"))
        if vf is None and vt is None:
            iid = md.get("instrument_id")
            vf, vt = instrument_validity(str(iid) if iid else None)
        if is_norm_valid_on_date(valid_from=vf, valid_to=vt, reference_date=reference_date):
            filtered.append(doc)
    return filtered


def _expand_with_norm_graph(
    docs: List[Document],
    *,
    reference_date: Optional[date],
    limit: int,
) -> List[Document]:
    if not docs or not bool(getattr(config, "LEGAL_NORM_GRAPH_EXPAND_ENABLED", True)):
        return docs
    from app.services.legal_norm_graph import (
        EDGE_TYPES_FORWARD,
        expand_norm_neighbor_edges_multihop,
        fetch_documents_by_norm_keys,
    )

    keys: List[str] = []
    for d in docs:
        k = str((d.metadata or {}).get("norm_node_key") or "").strip()
        if k:
            keys.append(k)
    if not keys:
        return docs

    max_hops = int(getattr(config, "LEGAL_NORM_GRAPH_MAX_HOPS", 2) or 2)
    total_limit = max(limit, int(getattr(config, "LEGAL_NORM_GRAPH_TOTAL_EXPAND_LIMIT", 24) or 24))
    neighbor_edges = expand_norm_neighbor_edges_multihop(
        keys[:8],
        max_hops=max_hops,
        limit_per_hop=limit,
        total_limit=total_limit,
        reference_date=reference_date,
    )
    if not neighbor_edges:
        return docs

    full_article_keys = {
        nk
        for nk, edge_type in neighbor_edges
        if edge_type in EDGE_TYPES_FORWARD and "::clause::" not in nk
    }
    neighbor_keys = [nk for nk, _ in neighbor_edges]
    extra = fetch_documents_by_norm_keys(
        neighbor_keys,
        reference_date=reference_date,
        full_article_for_keys=full_article_keys,
    )
    if extra:
        for d in extra:
            md = dict(d.metadata or {})
            md["graph_expanded"] = True
            d.metadata = md
    return _merge_documents(docs, extra) if extra else docs


def _fetch_graph_cluster_for_plan(
    plan: LegalRetrievalPlan,
    *,
    reference_date: Optional[date],
    limit: int,
) -> List[Document]:
    """
    Graph-first: явные статьи пользователя → узлы графа → многошаговый обход → тексты норм.
    """
    articles = structured_lookup_articles(plan)
    if not articles or not plan.instrument_ids:
        return []
    if not bool(getattr(config, "LEGAL_NORM_GRAPH_CLUSTER_ENABLED", True)):
        return []

    from app.services.legal_norm_lookup import NormLookupRequest, fetch_norm_documents
    from app.services.legal_norm_graph import (
        EDGE_TYPES_FORWARD,
        expand_norm_neighbor_edges_multihop,
        fetch_documents_by_norm_keys,
    )

    seed_requests: List[NormLookupRequest] = []
    for iid in plan.instrument_ids:
        for art in articles:
            cref = plan.user_clause_ref if len(articles) == 1 else None
            seed_requests.append(
                NormLookupRequest(
                    instrument_id=iid,
                    article_number=art,
                    clause_ref=cref or None,
                )
            )

    seed_docs = fetch_norm_documents(seed_requests, reference_date=reference_date)
    seed_keys: List[str] = []
    for d in seed_docs:
        k = str((d.metadata or {}).get("norm_node_key") or "").strip()
        if k:
            seed_keys.append(k)

    if not seed_keys:
        return seed_docs[:limit] if seed_docs else []

    max_hops = int(getattr(config, "LEGAL_NORM_GRAPH_MAX_HOPS", 2) or 2)
    cluster_cap = max(limit, int(getattr(config, "LEGAL_NORM_GRAPH_CLUSTER_LIMIT", 20) or 20))
    neighbor_edges = expand_norm_neighbor_edges_multihop(
        seed_keys,
        max_hops=max_hops,
        total_limit=cluster_cap,
        reference_date=reference_date,
    )
    full_article_keys = {
        nk
        for nk, edge_type in neighbor_edges
        if edge_type in EDGE_TYPES_FORWARD and "::clause::" not in nk
    }
    neighbor_keys = [nk for nk, _ in neighbor_edges]
    cluster_docs = list(seed_docs)
    if neighbor_keys:
        extra = fetch_documents_by_norm_keys(
            neighbor_keys,
            reference_date=reference_date,
            full_article_for_keys=full_article_keys,
        )
        for d in extra:
            md = dict(d.metadata or {})
            md["graph_cluster"] = True
            d.metadata = md
        cluster_docs = _merge_documents(cluster_docs, extra)

    return cluster_docs[:cluster_cap]


def _fetch_norm_tree_for_plan(
    plan: LegalRetrievalPlan,
    *,
    reference_date: Optional[date],
) -> Tuple[List[Document], bool]:
    """Structured lookup по дереву норм (article_lookup)."""
    from app.services.legal_norm_lookup import fetch_norm_documents_for_plan, should_prefer_norm_tree

    if not should_prefer_norm_tree(plan):
        return [], False
    docs = fetch_norm_documents_for_plan(plan, reference_date=reference_date)
    if not docs:
        return [], False
    sufficient = plan_is_sufficient(docs, plan)
    return docs, sufficient


def _fetch_required_articles_fast(
    plan: LegalRetrievalPlan,
    question: str,
    *,
    k: int,
) -> Tuple[List[Document], bool]:
    """Batch FTS по явным статьям пользователя."""
    articles = structured_lookup_articles(plan)
    if not articles or not plan.instrument_ids:
        return [], False
    from app.services.legal_corpus_service import batch_articles_fts_lookup

    merged = batch_articles_fts_lookup(
        articles[:6],
        question,
        plan.instrument_ids,
        k_per_article=k,
    )
    used_fast = bool(merged) and plan_is_sufficient(merged, plan)
    return merged, used_fast


def _gap_fill_missing_articles(
    docs: List[Document],
    plan: LegalRetrievalPlan,
    question: str,
    *,
    k: int,
    wall_deadline: float,
) -> List[Document]:
    if time.monotonic() >= wall_deadline:
        return docs
    cov = plan_coverage(docs, plan, question=question)
    missing = [a for a in (cov.get("missing") or []) if a in coverage_target_articles(plan, question)]
    if not missing or not plan.instrument_ids:
        return docs
    from app.services.legal_corpus_service import batch_articles_fts_lookup

    extra = batch_articles_fts_lookup(
        missing[:4],
        f"127-ФЗ {question}",
        plan.instrument_ids,
        k_per_article=k,
    )
    return _merge_documents(docs, extra) if extra else docs


def _cap_search_queries_from_plan(plan: LegalRetrievalPlan, question: str) -> List[str]:
    cap = _max_hybrid_queries(plan)
    base = build_hybrid_queries_from_plan(plan, question)
    out: List[str] = []
    seen: set[str] = set()
    for sq in base:
        t = (sq or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= cap:
            break
    return out or base[:1]


def _maybe_plenum_supplement(
    docs: List[Document],
    question: str,
    plan: LegalRetrievalPlan,
    *,
    k: int,
) -> List[Document]:
    instrument_ids = plan.instrument_ids
    if "fz-127" not in instrument_ids or "plenum-63" not in instrument_ids:
        return docs
    needs_plenum = plan.topic in ("challenge_transactions", "limitation_challenge") or any(
        a.startswith("61") for a in plan.required_articles
    )
    if not needs_plenum:
        return docs
    has_plenum = any(
        str((d.metadata or {}).get("instrument_id", "")).lower() == "plenum-63"
        or "пленум" in str((d.metadata or {}).get("source_filename", "")).lower()
        for d in docs
    )
    if has_plenum:
        return docs
    art = next((a for a in plan.required_articles if a.startswith("61")), "61.2")
    plenum_q = f"пленум 63 статья {art} оспаривание сделки {question}".strip()
    extra = article_lookup_fast(plenum_q, art, ["plenum-63"], k=max(2, min(4, k)))
    return _merge_documents(docs, extra or [])


def _iterative_followup_bounded(
    question: str,
    docs: List[Document],
    instrument_ids: List[str],
    *,
    k_each: int,
    wall_deadline: float,
    missing_articles: Optional[List[str]] = None,
) -> List[Document]:
    if not bool(getattr(config, "GLOBAL_LEGAL_ITERATIVE_RETRIEVAL_ENABLED", True)):
        return []
    if time.monotonic() >= wall_deadline:
        return []

    # Детерминированный добор по непокрытым статьям (приоритет над LLM)
    if missing_articles and instrument_ids:
        out: List[Document] = []
        for art in missing_articles[:3]:
            if time.monotonic() >= wall_deadline:
                break
            out.extend(
                article_lookup_fast(
                    f"статья {art} 127-ФЗ полный текст",
                    art,
                    instrument_ids,
                    k=k_each,
                )
            )
        if out:
            return out

    if not docs:
        return []

    from app.services.chat.global_langgraph_service import (
        _legal_digest_for_iterative_planner,
        _plan_law_followup_retrieval,
    )
    from app.services.legal_corpus_service import retrieve_legal_corpus_documents

    digest_hits = []
    for d in docs[:8]:
        meta = d.metadata or {}
        digest_hits.append(
            {
                "source_type": "legal_corpus",
                "file_name": str(meta.get("source_filename", "Справочник")),
                "text": (d.page_content or "").strip(),
                "score": float(meta.get("rerank_score") or meta.get("score") or 0.0),
            }
        )
    digest = _legal_digest_for_iterative_planner(digest_hits)
    satisfied, followup_queries, rationale = _plan_law_followup_retrieval(
        user_query=question,
        digest=digest,
    )
    logger.info(
        "[LegalRetrievalAgent] iterative LLM: satisfied=%s followups=%d rationale=%s",
        satisfied,
        len(followup_queries or []),
        (rationale or "")[:100],
    )
    if satisfied or not followup_queries:
        return []

    max_q = min(2, int(getattr(config, "GLOBAL_LEGAL_ITERATIVE_MAX_QUERIES", 3) or 3))
    queries = [q.strip() for q in followup_queries[:max_q] if q and q.strip()]
    combined: List[Document] = []
    for sq in queries:
        if time.monotonic() >= wall_deadline:
            break
        try:
            hits = retrieve_legal_corpus_documents(
                sq,
                k=k_each,
                instrument_ids=instrument_ids or None,
                search_queries=[sq],
                max_search_queries=1,
            )
        except TypeError:
            hits = retrieve_legal_corpus_documents(
                sq,
                k=k_each,
                instrument_ids=instrument_ids or None,
                search_queries=[sq],
            )
        combined.extend(hits or [])

    seen = {(d.page_content or "")[:200] for d in docs}
    new_docs: List[Document] = []
    for d in combined:
        key = (d.page_content or "")[:200]
        if key not in seen:
            seen.add(key)
            new_docs.append(d)
    return new_docs


def _build_coverage_note(
    plan: LegalRetrievalPlan,
    cov: Dict[str, Any],
    *,
    sufficient: bool,
) -> str:
    if sufficient and not cov.get("repeal_only"):
        return ""
    parts: List[str] = []
    missing = cov.get("missing") or []
    repeal_only = cov.get("repeal_only") or []

    if repeal_only and plan.topic == "article_lookup":
        arts = ", ".join(repeal_only)
        parts.append(
            f"В справочнике для ст. {arts} найдены в основном отметки об утрате силы или отсылки; "
            "действующий полный текст статьи может отсутствовать в индексе. Уточните редакцию закона."
        )
    if missing:
        parts.append(
            f"Не найдены (или неполны) фрагменты по ст.: {', '.join(missing)}. "
            "Ответ опирается на имеющиеся источники; при необходимости уточните номер статьи и акт."
        )
    if not parts:
        parts.append(
            "Найдены частичные фрагменты норм; для уверенного ответа уточните акт, статью или формулировку."
        )
    return " ".join(parts)


# Back-compat for tests
def _heuristic_sufficient(
    docs: List[Document],
    *,
    article: Optional[str],
    min_chars: int = 400,
) -> bool:
    if not docs:
        return False
    total = sum(len((d.page_content or "")) for d in docs)
    if total < min_chars:
        return False
    if article:
        hits = sum(1 for d in docs if _doc_mentions_article(d, article))
        return hits >= 1 and total >= min_chars
    return total >= min_chars * 2


def _cap_search_queries(
    question: str,
    route_queries: List[str],
    *,
    max_queries: int,
) -> List[str]:
    raw: List[str] = [(question or "").strip()]
    raw.extend(route_queries or [])
    out: List[str] = []
    seen: set[str] = set()
    for sq in raw:
        t = (sq or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= max_queries:
            break
    return out or [(question or "").strip() or " "]


def _skip_rerank_on_fast_path(used_fast: bool, docs: List[Document], plan: LegalRetrievalPlan) -> bool:
    if not used_fast:
        return False
    if not bool(getattr(config, "LEGAL_CORPUS_SKIP_RERANK_ON_FAST_PATH", True)):
        return False
    return plan_is_sufficient(docs, plan)


def run_legal_corpus_retrieval(
    question: str,
    *,
    k: Optional[int] = None,
    max_chars: Optional[int] = None,
    legal_research: bool = False,
    task_type: Optional[str] = None,
    allow_query_interpreter_first_pass: Optional[bool] = None,
    include_iterative: bool = True,
    instrument_ids: Optional[List[str]] = None,
    reference_date: Optional[Any] = None,
) -> LegalRetrievalResult:
    """
    Единая точка retrieval по GLOBAL_LEGAL_CORPUS с бюджетами и stop-criteria.
    """
    from app.services.legal_corpus_service import retrieve_legal_corpus_documents

    q = (question or "").strip()
    if not q:
        return LegalRetrievalResult("", [], [], "")

    ctx_k = int(k if k is not None else (getattr(config, "LEGAL_CORPUS_CONTEXT_K", 8) or 8))
    max_c = int(
        max_chars
        if max_chars is not None
        else (getattr(config, "LEGAL_CORPUS_MAX_CONTEXT_CHARS", 14000) or 14000)
    )
    t0 = time.monotonic()
    ref_date = _parse_reference_date(reference_date)

    pre_ids = _filter_instrument_ids(instrument_ids)
    plan, planner_source = resolve_legal_retrieval_plan(
        q,
        instrument_ids=pre_ids,
        legal_research=legal_research,
        task_type=task_type,
    )
    # Бюджет retrieval — после планировщика (LLM не должен съедать wall_ms поиска).
    deadline = time.monotonic() + (_wall_ms() / 1000.0)
    instrument_ids_final = plan.instrument_ids or pre_ids

    meta: Dict[str, Any] = {
        "topic": plan.topic,
        "required_articles": list(plan.required_articles),
        "user_articles": list(plan.user_articles),
        "facts": list(plan.facts),
        "planner_source": planner_source,
        "planner_ms": int((time.monotonic() - t0) * 1000),
        "hybrid_queries_used": 0,
        "used_fast_path": False,
        "iterative_added": 0,
        "gap_fill_rounds": 0,
        "reference_date": ref_date.isoformat() if ref_date else None,
        "user_clause_ref": plan.user_clause_ref or None,
    }

    docs: List[Document] = []
    used_fast = False
    used_norm_tree = False

    if _agentic_plan_enabled():
        user_arts = structured_lookup_articles(plan)
        # --- 0) Norm tree (structured metadata lookup для article_lookup) ---
        if user_arts and instrument_ids_final and time.monotonic() < deadline:
            tree_docs, tree_sufficient = _fetch_norm_tree_for_plan(plan, reference_date=ref_date)
            if tree_docs:
                docs = tree_docs
                used_norm_tree = True
                meta["used_norm_tree"] = True
                logger.info(
                    "[LegalRetrievalAgent] norm_tree topic=%s articles=%s clause=%s n=%d sufficient=%s",
                    plan.topic,
                    plan.user_articles or plan.required_articles,
                    plan.user_clause_ref or "*",
                    len(docs),
                    tree_sufficient,
                )
                if tree_sufficient:
                    used_fast = True
                    meta["used_fast_path"] = True

        # --- 0b) Graph cluster: явные статьи → паутина норм (до FTS/hybrid) ---
        if (
            user_arts
            and instrument_ids_final
            and not plan_is_sufficient(docs, plan)
            and time.monotonic() < deadline
        ):
            cluster_lim = int(getattr(config, "LEGAL_NORM_GRAPH_CLUSTER_LIMIT", 20) or 20)
            cluster_docs = _fetch_graph_cluster_for_plan(
                plan,
                reference_date=ref_date,
                limit=cluster_lim,
            )
            if cluster_docs:
                docs = _merge_documents(docs, cluster_docs)
                meta["graph_cluster_docs"] = len(cluster_docs)
                logger.info(
                    "[LegalRetrievalAgent] graph_cluster articles=%s n=%d",
                    user_arts,
                    len(cluster_docs),
                )

        # --- 1) Per-article FTS fast path (fallback если дерево пусто / недостаточно) ---
        if not used_norm_tree and user_arts and instrument_ids_final and time.monotonic() < deadline:
            fast_docs, used_fast = _fetch_required_articles_fast(plan, q, k=ctx_k)
            docs = fast_docs
            if used_fast:
                meta["used_fast_path"] = True
                logger.info(
                    "[LegalRetrievalAgent] plan fast_path topic=%s articles=%s n=%d",
                    plan.topic,
                    plan.required_articles,
                    len(docs),
                )

        # --- 2) Hybrid по запросам плана (пропускаем, если fast path / norm tree уже покрыл план) ---
        if not plan_is_sufficient(docs, plan) and time.monotonic() < deadline:
            hybrid_qs = _cap_search_queries_from_plan(plan, q)
            meta["hybrid_queries_used"] = len(hybrid_qs)
            skip_rerank = _skip_rerank_on_fast_path(used_fast, docs, plan)

            # LLM planner уже сформировал search_queries; interpreter — только при чисто детерминированном плане
            if planner_source != "deterministic":
                first_pass_interp = False
            elif allow_query_interpreter_first_pass is not None:
                first_pass_interp = bool(allow_query_interpreter_first_pass)
            else:
                first_pass_interp = bool(
                    getattr(config, "LEGAL_CORPUS_QUERY_INTERPRETER_ON_FIRST_PASS", False)
                )
            if (
                first_pass_interp
                and bool(getattr(config, "GLOBAL_LEGAL_QUERY_INTERPRETER_ENABLED", True))
                and time.monotonic() < deadline
            ):
                try:
                    from app.services.chat.global_langgraph_service import _generate_semantic_search_queries

                    sem = _generate_semantic_search_queries(q)
                    seen = {x.lower() for x in hybrid_qs}
                    for sq in sem:
                        sq = sq.strip()
                        if sq and sq.lower() not in seen and len(hybrid_qs) < _max_hybrid_queries(plan):
                            seen.add(sq.lower())
                            hybrid_qs.append(sq)
                    meta["semantic_queries"] = len(sem)
                except Exception as ex:
                    logger.warning("[LegalRetrievalAgent] query_interpreter skipped: %s", ex)

            try:
                hits = retrieve_legal_corpus_documents(
                    q,
                    k=ctx_k,
                    instrument_ids=instrument_ids_final or None,
                    search_queries=hybrid_qs,
                    max_search_queries=len(hybrid_qs),
                    skip_rerank=skip_rerank,
                    include_original_query=False,
                )
            except TypeError:
                hits = retrieve_legal_corpus_documents(
                    q,
                    k=ctx_k,
                    instrument_ids=instrument_ids_final or None,
                    search_queries=hybrid_qs,
                    skip_rerank=skip_rerank,
                    include_original_query=False,
                )
            docs = _merge_documents(docs, hits or [])
        elif used_fast and plan_is_sufficient(docs, plan):
            meta["skip_rerank"] = True
            logger.info(
                "[LegalRetrievalAgent] hybrid skipped: fast_path sufficient topic=%s articles=%s",
                plan.topic,
                plan.required_articles,
            )

        # --- 3) Gap-fill по непокрытым статьям ---
        cov = plan_coverage(docs, plan, question=question)
        if cov.get("missing") and time.monotonic() < deadline:
            before = len(docs)
            docs = _gap_fill_missing_articles(docs, plan, q, k=ctx_k, wall_deadline=deadline)
            if len(docs) > before:
                meta["gap_fill_rounds"] = int(meta.get("gap_fill_rounds") or 0) + 1

        docs = _maybe_plenum_supplement(docs, q, plan, k=ctx_k)
        docs = _rank_documents_for_plan(docs, plan, question=question)

    else:
        # Legacy path (flag off)
        from app.services.chat.legal_router import extract_article_number, resolve_legal_corpus_route

        route = resolve_legal_corpus_route(q, legal_research=legal_research, task_type=task_type)
        instrument_ids_final = _filter_instrument_ids(route.instrument_ids)
        article = extract_article_number(q)
        meta["article"] = article
        if article and instrument_ids_final:
            fast_docs = article_lookup_fast(q, article, instrument_ids_final, k=ctx_k)
            if _heuristic_sufficient(fast_docs, article=article):
                docs = fast_docs
                used_fast = True
                meta["used_fast_path"] = True
        if not docs and time.monotonic() < deadline:
            hybrid_qs = _cap_search_queries(q, route.queries, max_queries=_max_hybrid_queries(plan))
            meta["hybrid_queries_used"] = len(hybrid_qs)
            docs = retrieve_legal_corpus_documents(
                q,
                k=ctx_k,
                instrument_ids=instrument_ids_final or None,
                search_queries=hybrid_qs,
            )

    cov = plan_coverage(docs, plan, question=question) if _agentic_plan_enabled() else {}
    sufficient = plan_is_sufficient(docs, plan) if _agentic_plan_enabled() else _heuristic_sufficient(
        docs, article=meta.get("article")
    )

    # --- 4) Iterative: сначала детерминированный добор, потом LLM planner ---
    if include_iterative and not sufficient and time.monotonic() < deadline:
        k_follow = max(
            2,
            min(ctx_k, int(getattr(config, "GLOBAL_LEGAL_ITERATIVE_K_PER_QUERY", 6) or 6)),
        )
        missing = list(cov.get("missing") or []) if cov else []
        extra = _iterative_followup_bounded(
            q,
            docs,
            instrument_ids_final,
            k_each=k_follow,
            wall_deadline=deadline,
            missing_articles=missing,
        )
        if extra:
            docs = _merge_documents(docs, extra)
            meta["iterative_added"] = len(extra)
            cov = plan_coverage(docs, plan, question=question)
            sufficient = plan_is_sufficient(docs, plan)

        if not sufficient and time.monotonic() < deadline:
            extra_llm = _iterative_followup_bounded(
                q,
                docs,
                instrument_ids_final,
                k_each=k_follow,
                wall_deadline=deadline,
                missing_articles=None,
            )
            if extra_llm:
                docs = _merge_documents(docs, extra_llm)
                meta["iterative_added"] = int(meta.get("iterative_added") or 0) + len(extra_llm)
                cov = plan_coverage(docs, plan, question=question)
                sufficient = plan_is_sufficient(docs, plan)

    meta["coverage"] = cov
    meta["articles_covered"] = list(cov.get("covered") or [])
    meta["articles_missing"] = list(cov.get("missing") or [])

    if not docs:
        return LegalRetrievalResult(
            "",
            [],
            instrument_ids_final,
            plan.rationale,
            used_fast_path=used_fast,
            coverage_note="",
            meta=meta,
        )

    coverage_note = _build_coverage_note(plan, cov, sufficient=sufficient) if _agentic_plan_enabled() else ""

    docs = _filter_docs_by_reference_date(docs, ref_date)
    if docs and time.monotonic() < deadline:
        expand_lim = int(getattr(config, "LEGAL_NORM_GRAPH_EXPAND_LIMIT", 8) or 8)
        expanded = _expand_with_norm_graph(docs, reference_date=ref_date, limit=expand_lim)
        if len(expanded) > len(docs):
            meta["graph_expanded"] = len(expanded) - len(docs)
            docs = expanded

    docs = _rank_documents_for_plan(docs, plan, question=question)
    context, included = _format_context_with_budget(
        docs,
        max_chars=max_c,
        coverage_note=coverage_note,
    )
    meta["wall_ms"] = int((time.monotonic() - t0) * 1000)
    meta["sufficient"] = sufficient
    meta["doc_count"] = len(included)

    return LegalRetrievalResult(
        context=context,
        documents=included,
        instrument_ids=instrument_ids_final,
        route_rationale=plan.rationale,
        used_fast_path=used_fast,
        coverage_note=coverage_note,
        meta=meta,
    )
