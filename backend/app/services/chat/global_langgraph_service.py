"""LangGraph orchestrator for global assistant (multi-source RAG)."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import config
from app.services import legal_corpus_service as lcs
from app.services.llm_factory import create_legal_llm
from app.services.langchain_agents.store_integration import get_store_instance
from app.services.langchain_agents.store_integration import reset_store_instance
from app.utils.async_checkpointer_wrapper import wrap_postgres_saver_if_needed
from app.utils.checkpointer_setup import get_checkpointer_instance
from app.utils.checkpointer_setup import reset_checkpointer_instance
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    trace_contract_event,
    normalize_observability_metadata,
    get_langchain_callbacks,
)

logger = logging.getLogger(__name__)

RouteDecision = Literal["matter", "law", "hybrid", "clarify"]
SufficiencyStatus = Literal["enough", "need_hybrid", "need_clarify", "no_answer"]


def _is_transient_db_connection_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "ssl connection has been closed unexpectedly",
        "consuming input failed",
        "connection not open",
        "server closed the connection unexpectedly",
        "connection is closed",
        "connection reset by peer",
    )
    return any(m in text for m in markers)

_LAW_MARKERS = (
    "ст.", "статья", "гк рф", "гпк", "апк", "ук рф", "упк", "коап",
    "фз", "закон", "пленум", "постановление", "норма", "правомер",
    "оспор", "недействитель", "исковая давность", "подсудност",
)


class GlobalAssistantGraphState(TypedDict, total=False):
    user_id: str
    user_query: str
    chat_history: List[Dict[str, str]]
    draft_mode: bool
    use_legal_corpus: bool
    matter_contexts: List[Dict[str, Any]]

    route_decision: RouteDecision
    route_confidence: float
    route_reason: str
    phase_logs: List[str]

    matter_hits: List[Dict[str, Any]]
    law_hits: List[Dict[str, Any]]
    merged_hits: List[Dict[str, Any]]
    sufficiency_status: SufficiencyStatus
    answer_status: str

    citations: List[Dict[str, Any]]
    draft_answer: str
    response: str
    no_answer_reason: str
    draft_plan: Dict[str, Any]
    draft_plan_id: str
    draft_approved: bool
    draft_modifications: str
    model_reasoning: str
    answer_system_prompt: str
    answer_user_prompt: str
    effective_query: str
    conversation_summary: str
    memory_context: str


@dataclass
class GlobalAssistantGraphResult:
    response: str
    citations: List[Dict[str, Any]]
    route_decision: RouteDecision
    route_confidence: float
    sufficiency_status: SufficiencyStatus
    answer_status: str
    phase_logs: List[str]
    draft_plan: Optional[Dict[str, Any]]
    draft_plan_id: Optional[str]
    model_reasoning: Optional[str]
    answer_system_prompt: Optional[str]
    answer_user_prompt: Optional[str]


def _keywords(text: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Zа-яА-Я0-9]{3,}", (text or "").lower())
    return [t for t in tokens if len(t) >= 3]


def _score_overlap(text: str, query: str) -> float:
    qk = set(_keywords(query))
    if not qk:
        return 0.0
    tk = set(_keywords(text))
    if not tk:
        return 0.0
    common = len(qk.intersection(tk))
    return common / max(1, len(qk))


def _extract_article_number(query: str) -> Optional[str]:
    q = (query or "").lower()
    m = re.search(r"(?:ст\.?|статья)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)", q)
    if m:
        return m.group(1)
    if re.fullmatch(r"\s*[0-9]{1,5}(?:\.[0-9]{1,3})?\s*", q):
        return q.strip()
    return None


def _extract_code_marker(query: str) -> Optional[str]:
    q = (query or "").lower()
    for marker in ("гк", "гпк", "апк", "ук", "упк", "коап"):
        if marker in q:
            return marker
    return None


def _recent_history_text(chat_history: List[Dict[str, str]], max_turns: int = 6, max_chars: int = 2000) -> str:
    items = chat_history[-max_turns:] if chat_history else []
    lines: List[str] = []
    for m in items:
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            prefix = "Ассистент"
        else:
            prefix = "Пользователь"
        lines.append(f"{prefix}: {content}")
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def _build_effective_query(user_query: str, chat_history: List[Dict[str, str]]) -> str:
    """
    LangGraph short-term memory best practice:
    use a compact, recency-biased query for routing/retrieval.
    """
    q = (user_query or "").strip()
    history = _recent_history_text(chat_history, max_turns=4, max_chars=900)
    if not history:
        return q
    return f"{history}\nТекущий запрос: {q}"


def _summarize_chat_history(
    chat_history: List[Dict[str, str]],
    previous_summary: str = "",
    keep_last: int = 6,
) -> str:
    if not chat_history or len(chat_history) <= 12:
        return (previous_summary or "").strip()
    old_part = chat_history[:-keep_last]
    chunks: List[str] = []
    for m in old_part:
        role = "Пользователь" if (m.get("role") or "").lower() == "user" else "Ассистент"
        content = (m.get("content") or "").strip()
        if content:
            chunks.append(f"{role}: {content}")
    if not chunks:
        return (previous_summary or "").strip()
    llm = create_legal_llm(use_rate_limiting=False, temperature=0.0, max_tokens=700)
    callbacks = get_langchain_callbacks(tags=["assistant", "global_assistant", "history_summary"])
    prompt = (
        "Суммаризируй юридически значимый контекст диалога кратко и фактически. "
        "Выдели: цель, ключевые факты, ограничения, договоренности. "
        "Не добавляй новую информацию.\n\n"
        f"Предыдущая сводка:\n{previous_summary or '[нет]'}\n\n"
        f"Сообщения для сводки:\n{chr(10).join(chunks)[:12000]}"
    )
    try:
        raw = llm.invoke(
            [HumanMessage(content=prompt)],
            config={"callbacks": callbacks} if callbacks else None,
        )
        content = raw.content if hasattr(raw, "content") else str(raw)
        return (content or previous_summary or "").strip()[:4000]
    except Exception:
        return (previous_summary or "").strip()


def _safe_item_value(item: Any) -> Any:
    if hasattr(item, "value"):
        return item.value
    return item


def _normalize_memory_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return (
            str(value.get("fact") or value.get("text") or value.get("summary") or "").strip()
            or json.dumps(value, ensure_ascii=False)
        )
    return str(value).strip()


def _search_memory_facts(
    store: Any,
    user_id: str,
    query: str,
    k: int = 5,
) -> List[str]:
    """
    Best-effort semantic retrieval with graceful fallback:
    1) store.search(namespace, query=..., limit/top_k=...)
    2) fallback to lexical overlap over known keys (if only get available)
    """
    if not store or not user_id:
        return []
    namespace = ("memory_facts", user_id)
    hits: List[str] = []

    # Preferred: semantic search API (different store impls use different param names).
    if hasattr(store, "search"):
        search_variants = [
            {"query": query, "limit": k},
            {"query": query, "top_k": k},
            {"query": query, "k": k},
        ]
        for kwargs in search_variants:
            try:
                result = store.search(namespace, **kwargs)
                if result:
                    for item in result:
                        text = _normalize_memory_text(_safe_item_value(item))
                        if text:
                            hits.append(text)
                    if hits:
                        return hits[:k]
            except TypeError:
                continue
            except Exception:
                break

    # Fallback: known key scan with lexical scoring.
    if hasattr(store, "get"):
        candidates: List[str] = []
        for i in range(1, 61):
            key = f"fact_{i:03d}"
            try:
                item = store.get(namespace, key)
            except Exception:
                item = None
            if not item:
                continue
            text = _normalize_memory_text(_safe_item_value(item))
            if text:
                candidates.append(text)
        scored = sorted(
            candidates,
            key=lambda t: _score_overlap(t, query),
            reverse=True,
        )
        return [x for x in scored if _score_overlap(x, query) > 0][:k]
    return []


def _primary_matter_key(state: GlobalAssistantGraphState) -> str:
    for ctx in state.get("matter_contexts") or []:
        case_id = (ctx or {}).get("case_id")
        if case_id:
            return str(case_id)
    return "global"


def _extract_confirmed_facts_for_memory(state: GlobalAssistantGraphState) -> List[str]:
    """
    Write-policy:
    - only compact, source-grounded facts
    - no speculative reasoning or assistant free-form generation
    """
    facts: List[str] = []
    query = (state.get("user_query") or "").strip()
    if query:
        # Keep explicit user constraints/preferences from current turn.
        q_lower = query.lower()
        if any(x in q_lower for x in ("только", "обязательно", "нельзя", "необходимо", "срок", "подсудност", "статья")):
            facts.append(f"Ограничения/приоритеты пользователя: {query[:500]}")

    # Source-grounded snippets only from retrieved hits (already citation-based).
    for h in (state.get("merged_hits") or [])[:8]:
        source_name = str(h.get("file_name") or "Источник")
        text = (h.get("text") or "").strip()
        if not text:
            continue
        # extract article-like references if present
        art = re.search(r"(?:ст\.?|статья)\s*[0-9]{1,5}(?:\.[0-9]{1,3})?", text.lower())
        if art:
            facts.append(f"Подтверждено источником «{source_name}»: {art.group(0)}.")
        # add one compact grounded sentence fragment
        sentence = re.split(r"(?<=[\.\!\?])\s+", text)[0].strip()
        if sentence and len(sentence) > 20:
            facts.append(f"Факт из «{source_name}»: {sentence[:420]}")

    # De-dup and cap.
    out: List[str] = []
    seen = set()
    for f in facts:
        key = f.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
        if len(out) >= 8:
            break
    return out


def _route_by_rules(query: str, has_matter: bool, legal_enabled: bool) -> Optional[RouteDecision]:
    q = (query or "").lower()
    has_law_signal = any(m in q for m in _LAW_MARKERS)
    has_matter_signal = any(x in q for x in ("в договор", "в документ", "в материалах", "в переписк", "в деле"))
    if has_law_signal and has_matter:
        return "hybrid"
    if has_law_signal and legal_enabled:
        return "law"
    if has_matter_signal and has_matter:
        return "matter"
    return None


def _llm_route(query: str, has_matter: bool, legal_enabled: bool) -> tuple[RouteDecision, float, str]:
    llm = create_legal_llm(use_rate_limiting=False, temperature=0.0, max_tokens=300)
    callbacks = get_langchain_callbacks(tags=["assistant", "global_assistant", "router"])
    prompt = (
        "Определи, какие источники нужны для ответа. Варианты route: matter|law|hybrid|clarify. "
        "Верни только JSON: {\"route\":...,\"confidence\":0..1,\"reason\":\"...\"}. "
        f"has_matter={str(has_matter).lower()}, legal_enabled={str(legal_enabled).lower()}.\n"
        f"query: {query}"
    )
    try:
        raw = llm.invoke(
            [HumanMessage(content=prompt)],
            config={"callbacks": callbacks} if callbacks else None,
        )
        content = raw.content if hasattr(raw, "content") else str(raw)
        data = json.loads(content.strip())
        route = str(data.get("route", "hybrid")).lower()
        if route not in {"matter", "law", "hybrid", "clarify"}:
            route = "hybrid"
        conf = float(data.get("confidence", 0.6))
        reason = str(data.get("reason", "llm_route"))
        return route, max(0.0, min(1.0, conf)), reason
    except Exception:
        return "hybrid", 0.55, "llm_fallback"


def _collect_law_hits(query: str, k: int = 8) -> List[Dict[str, Any]]:
    docs: List[Document] = lcs.retrieve_legal_corpus_documents(query, k=k)
    article_no = _extract_article_number(query)
    code_marker = _extract_code_marker(query)
    out: List[Dict[str, Any]] = []
    for d in docs:
        meta = d.metadata or {}
        txt = (d.page_content or "").strip()
        filename = str(meta.get("source_filename", "Справочник"))
        txt_lower = txt.lower()
        filename_lower = filename.lower()
        score = _score_overlap(txt, query)
        if article_no and re.search(rf"(?:ст\.?|статья)\s*{re.escape(article_no)}\b", txt_lower):
            score += 0.5
        if code_marker and code_marker in filename_lower:
            score += 0.35
        # Penalize "similar but wrong" code references for strict legal queries.
        if code_marker and code_marker not in filename_lower and any(x in filename_lower for x in ("гк", "гпк", "апк", "ук", "упк", "коап")):
            score -= 0.25
        out.append(
            {
                "source_type": "legal_corpus",
                "source_id": meta.get("corpus_file_id") or "",
                "file_name": filename,
                "text": txt,
                "score": score,
                "char_start": meta.get("char_start"),
                "char_end": meta.get("char_end"),
                "page": meta.get("source_page"),
            }
        )
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return out[: max(8, k)]


def _collect_matter_hits(query: str, contexts: List[Dict[str, Any]], k: int = 8) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in contexts or []:
        txt = (c.get("text") or "").strip()
        if not txt:
            continue
        out.append(
            {
                "source_type": "document",
                "source_id": c.get("file_id") or "",
                "file_name": c.get("filename") or "Документ",
                "text": txt[:3000],
                "score": _score_overlap(txt, query),
                "case_id": c.get("case_id"),
            }
        )
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return out[:k]


def _build_draft_plan_payload(
    *,
    query: str,
    route: RouteDecision,
    merged_hits: List[Dict[str, Any]],
    draft_modifications: str = "",
) -> Dict[str, Any]:
    sources_count = len(merged_hits)
    legal_hits = sum(1 for h in merged_hits if h.get("source_type") == "legal_corpus")
    doc_hits = max(0, sources_count - legal_hits)
    query_len = len((query or "").strip())
    steps: List[Dict[str, str]] = [
        {"description": "Проверить входные требования и выделить обязательные разделы документа.", "agent_name": "planner"},
        {"description": "Собрать релевантные факты из контекста и приложенных файлов.", "agent_name": "matter_retriever"},
    ]
    if legal_hits > 0:
        steps.append(
            {"description": "Проверить правовые основания по кодексам и зафиксировать нормы для ссылок.", "agent_name": "legal_retriever"}
        )
    steps.extend(
        [
            {"description": "Сформировать структуру черновика и подготовить текст разделов.", "agent_name": "draft_writer"},
            {"description": "Провести финальную сверку формулировок и источников.", "agent_name": "quality_check"},
        ]
    )
    reasoning = (
        f"План сформирован для route={route}. Найдено источников: {sources_count} "
        f"(контекст/файлы: {doc_hits}, кодексы: {legal_hits})."
    )
    if draft_modifications:
        reasoning += f" Учтены правки пользователя: {draft_modifications[:300]}"
    questions_for_lawyer: List[str] = []
    needs_clarification = (
        query_len < 40
        or sources_count < 2
        or (route in {"law", "hybrid"} and legal_hits == 0)
    )
    if needs_clarification:
        if legal_hits == 0 and route in {"law", "hybrid"}:
            questions_for_lawyer.append("Какие конкретные нормы/статьи кодекса нужно обязательно учесть в документе?")
        if query_len < 40:
            questions_for_lawyer.append("Уточните целевой тип документа и ожидаемый результат (что именно должно быть на выходе).")
        if sources_count < 2:
            questions_for_lawyer.append("Есть ли дополнительные материалы/файлы, которые обязательно нужно включить в основание черновика?")
        questions_for_lawyer.append("Подтвердите обязательную структуру/шаблон документа (если есть внутренний стандарт).")
    return {
        "reasoning": reasoning,
        "task_understanding": (
            f"Я понимаю задачу так: нужно подготовить юридический черновик по запросу «{query[:220]}», "
            f"используя только подтвержденные источники (контекст/файлы/кодексы)."
        ),
        "goals": [
            {"description": f"Подготовить юридический черновик по запросу: {query[:280]}"},
            {"description": "Сохранить опору на контекст дела, файлы и нормы права."},
        ],
        "steps": steps,
        "questions_for_lawyer": questions_for_lawyer,
    }


def _extract_model_reasoning(raw: Any) -> str:
    """
    Extract provider-native reasoning captured by ChatYandexOpenAI
    in AIMessage.additional_kwargs (reasoning_content/reasoning/thinking).
    """
    try:
        msg = raw if hasattr(raw, "additional_kwargs") else None
        if msg is None:
            return ""
        ak = getattr(msg, "additional_kwargs", None) or {}
        if not isinstance(ak, dict):
            return ""
        for key in ("reasoning_content", "reasoning", "thinking"):
            val = ak.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    except Exception:
        return ""


def _build_graph():
    graph = StateGraph(GlobalAssistantGraphState)

    def ingress_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        logs = list(state.get("phase_logs") or [])
        logs.append("ingress")
        return {**state, "phase_logs": logs}

    def mode_gate_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        logs = list(state.get("phase_logs") or [])
        logs.append("mode_gate_draft" if state.get("draft_mode") else "mode_gate_chat")
        summary = _summarize_chat_history(
            state.get("chat_history") or [],
            previous_summary=state.get("conversation_summary", "") or "",
        )
        effective_query = _build_effective_query(
            state.get("user_query", ""),
            state.get("chat_history") or [],
        )
        return {
            **state,
            "conversation_summary": summary,
            "effective_query": effective_query,
            "phase_logs": logs,
        }

    def load_memory_node(state: GlobalAssistantGraphState, runtime_config: Optional[Dict[str, Any]] = None) -> GlobalAssistantGraphState:
        logs = list(state.get("phase_logs") or [])
        logs.append("load_memory")
        memory_lines: List[str] = []
        try:
            store = (runtime_config or {}).get("store") if isinstance(runtime_config, dict) else None
            user_id = (state.get("user_id") or "").strip()
            if store and user_id and hasattr(store, "get"):
                profile_item = store.get(("memory", user_id), "user_profile")
                if profile_item:
                    val = profile_item.value if hasattr(profile_item, "value") else profile_item
                    memory_lines.append(f"Профиль пользователя: {json.dumps(val, ensure_ascii=False)[:1200]}")
                summary_item = store.get(("memory", user_id), "global_assistant_summary")
                if summary_item:
                    sval = summary_item.value if hasattr(summary_item, "value") else summary_item
                    if isinstance(sval, dict):
                        text = str(sval.get("summary", "")).strip()
                    else:
                        text = str(sval).strip()
                    if text:
                        memory_lines.append(f"Долгосрочная сводка: {text[:1500]}")
                # Semantic top-k gating over long-term fact memory.
                memory_query = (
                    state.get("effective_query")
                    or state.get("user_query")
                    or ""
                )
                top_k = int(getattr(globals().get("config"), "GLOBAL_MEMORY_TOP_K", 5) or 5)
                fact_hits = _search_memory_facts(store, user_id, memory_query, k=max(1, min(10, top_k)))
                if fact_hits:
                    joined = "\n".join(f"- {x}" for x in fact_hits[:max(1, min(10, top_k))])
                    memory_lines.append(f"Релевантные факты памяти (top-k):\n{joined}")
                matter_key = _primary_matter_key(state)
                matter_summary_item = store.get(("matter", user_id, matter_key), "summary")
                if matter_summary_item:
                    mval = matter_summary_item.value if hasattr(matter_summary_item, "value") else matter_summary_item
                    mtxt = str((mval or {}).get("summary", "") if isinstance(mval, dict) else mval).strip()
                    if mtxt:
                        memory_lines.append(f"Контекст дела ({matter_key}): {mtxt[:1500]}")
        except Exception as ex:
            logger.debug("Global memory load skipped: %s", ex)
        return {**state, "memory_context": "\n".join(memory_lines).strip(), "phase_logs": logs}

    def route_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        query = state.get("effective_query") or state.get("user_query", "")
        has_matter = bool(state.get("matter_contexts"))
        legal_enabled = bool(state.get("use_legal_corpus"))
        logs = list(state.get("phase_logs") or [])
        logs.append("route")

        rules_route = _route_by_rules(query, has_matter=has_matter, legal_enabled=legal_enabled)
        if rules_route:
            route, conf, reason = rules_route, 0.92, "rules"
        else:
            route, conf, reason = _llm_route(query, has_matter=has_matter, legal_enabled=legal_enabled)

        if route == "law" and not legal_enabled:
            route, reason = "hybrid", "law_disabled_fallback"
        if route == "matter" and not has_matter:
            route, reason = "hybrid", "matter_empty_fallback"
        if conf < 0.70 and route in {"matter", "law"}:
            route, reason = "hybrid", "low_confidence_fallback"

        return {
            **state,
            "route_decision": route,
            "route_confidence": conf,
            "route_reason": reason,
            "phase_logs": logs,
        }

    def retrieve_matter_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        hits = _collect_matter_hits(state.get("effective_query") or state.get("user_query", ""), state.get("matter_contexts") or [], k=8)
        logs = list(state.get("phase_logs") or [])
        logs.append(f"retrieve_matter:{len(hits)}")
        return {**state, "matter_hits": hits, "phase_logs": logs}

    def retrieve_law_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        # IMPORTANT: Legal article search must rely on the current user query only.
        # Using effective_query (history + current question) can capture old article numbers.
        query = state.get("user_query", "")
        hits = _collect_law_hits(query, k=8) if state.get("use_legal_corpus") else []
        # Article-aware fallback: if explicit article query and no hits, retry with wider recall.
        if state.get("use_legal_corpus") and not hits and _extract_article_number(query):
            hits = _collect_law_hits(query, k=24)
        logs = list(state.get("phase_logs") or [])
        logs.append(f"retrieve_law:{len(hits)}")
        return {**state, "law_hits": hits, "phase_logs": logs}

    def merge_rerank_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        merged = list(state.get("matter_hits") or []) + list(state.get("law_hits") or [])
        merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        merged = merged[:10]
        logs = list(state.get("phase_logs") or [])
        logs.append(f"merge:{len(merged)}")
        return {**state, "merged_hits": merged, "phase_logs": logs}

    def sufficiency_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        route = state.get("route_decision", "hybrid")
        matter_hits = state.get("matter_hits") or []
        law_hits = state.get("law_hits") or []
        status: SufficiencyStatus = "enough"
        reason = ""

        if route == "clarify":
            status, reason = "need_clarify", "router_clarify"
        elif route == "matter":
            if not matter_hits:
                status, reason = "need_clarify", "matter_empty"
        elif route == "law":
            if not law_hits:
                status, reason = "no_answer", "law_empty"
        elif route == "hybrid":
            if not law_hits:
                status, reason = "no_answer", "hybrid_law_missing"
            elif not matter_hits and state.get("matter_contexts"):
                status, reason = "need_clarify", "hybrid_matter_missing"

        logs = list(state.get("phase_logs") or [])
        logs.append(f"sufficiency:{status}")
        return {**state, "sufficiency_status": status, "no_answer_reason": reason, "phase_logs": logs}

    def answer_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        if state.get("sufficiency_status") != "enough":
            return state

        route = state.get("route_decision", "hybrid")
        is_draft = bool(state.get("draft_mode"))
        draft_approved = bool(state.get("draft_approved"))
        merged_hits = state.get("merged_hits") or []
        query = state.get("user_query", "")

        citations: List[Dict[str, Any]] = []
        context_blocks: List[str] = []
        for idx, h in enumerate(merged_hits, start=1):
            quote_anchor = (h.get("text") or "")[:1400]
            citations.append(
                {
                    "source_id": h.get("source_id") or f"src_{idx}",
                    "file_name": h.get("file_name", "Источник"),
                    "page": h.get("page"),
                    "quote": quote_anchor,  # backward compatibility for existing frontend
                    "quote_anchor": quote_anchor,
                    "source_type": h.get("source_type", "document"),
                    "char_start": h.get("char_start"),
                    "char_end": h.get("char_end"),
                    "case_id": h.get("case_id"),
                }
            )
            context_blocks.append(
                f"[{idx}] ({h.get('source_type')}) {h.get('file_name')}\n{(h.get('text') or '')[:1500]}"
            )

        # Draft parity gate: first send plan, only generate draft after explicit approval.
        if is_draft and not draft_approved:
            plan_payload = _build_draft_plan_payload(
                query=query,
                route=route,
                merged_hits=merged_hits,
                draft_modifications=state.get("draft_modifications", "") or "",
            )
            logs = list(state.get("phase_logs") or [])
            logs.append("draft_plan_ready")
            return {
                **state,
                "response": "",
                "citations": citations,
                "answer_status": "plan_ready",
                "draft_plan": plan_payload,
                "draft_plan_id": str(uuid.uuid4()),
                "phase_logs": logs,
            }

        if is_draft:
            system = (
                "Ты — юридический drafting-ассистент.\n"
                "Составь полный проект документа строго на основании предоставленных источников:\n"
                "- legal_corpus;\n"
                "- материалы пользователя (контекст/файлы).\n"
                "Правила:\n"
                "1) Используй только подтвержденные данные из источников.\n"
                "2) Не выдумывай факты, реквизиты, даты, ссылки, нормы и судебную практику.\n"
                "3) Если данных недостаточно, явно указывай: [НУЖНО УТОЧНЕНИЕ].\n"
                "4) Не используй внешние знания и память.\n"
                "5) Соблюдай юридическую точность, официально-деловой стиль и логичную структуру документа.\n"
                "Формат ответа:\n"
                "- Верни готовый проект документа.\n"
                "- Сохраняй строгую юридическую форму и корректную терминологию.\n"
                "- Все неполные/неподтвержденные места помечай [НУЖНО УТОЧНЕНИЕ].\n"
                "Проверка перед выдачей:\n"
                "- Есть ли утверждения без подтверждения в источниках? Удали или замени на [НУЖНО УТОЧНЕНИЕ].\n"
                "- Есть ли вымышленные реквизиты/даты/ссылки? Удали."
            )
            if state.get("draft_modifications"):
                system += (
                    " Обязательно учти пожелания пользователя к плану/структуре: "
                    f"{state.get('draft_modifications')}"
                )
        else:
            system = (
                "Ты — юридический ассистент. Отвечай только на основании предоставленных источников в контексте.\n\n"
                "Правила:\n"
                "1) Используй только материалы из блока «Источники»/контекста. Не используй внешние знания.\n"
                "2) Каждое существенное утверждение подтверждай ссылкой [N] сразу после того фрагмента текста, который этим источником обоснован (предложение или законченная мысль из нескольких предложений). Не копи все [N] только в конец абзаца.\n"
                "3) Если информации недостаточно, прямо напиши: «Недостаточно данных в предоставленных материалах».\n"
                "4) Не выдумывай факты, даты, реквизиты, нормы и судебную практику.\n"
                "5) Пиши кратко, юридически точно, структурированно (Markdown).\n\n"
                "Формат ответа:\n"
                "- Сначала прямой ответ на вопрос.\n"
                "- Затем краткое обоснование по источникам.\n"
                "- Ссылки [N] по ходу текста у соответствующих тезисов, без сваливания в конец раздела.\n\n"
                "Проверка перед выдачей:\n"
                "- Есть ли в ответе утверждения без [N]? Если да — исправь.\n"
                "- Есть ли выводы, которых нет в источниках? Если да — убери."
            )
        if route in {"law", "hybrid"}:
            system += " Правовые выводы только из фрагментов legal_corpus."

        user_msg = (
            f"Долгосрочная память пользователя:\n{state.get('memory_context') or '[нет]'}\n\n"
            f"Сводка прошлых сообщений:\n{state.get('conversation_summary') or '[нет]'}\n\n"
            f"История диалога (последние сообщения):\n{_recent_history_text(state.get('chat_history') or [], max_turns=8, max_chars=2800) or '[нет]'}\n\n"
            f"Текущий вопрос:\n{query}\n\n"
            f"Источники:\n{chr(10).join(context_blocks)}\n\n"
            "Верни ответ на русском."
        )
        logs = list(state.get("phase_logs") or [])
        logs.append("answer_prompt_ready")
        return {
            **state,
            "response": "",
            "citations": citations,
            "answer_status": "ready_to_generate",
            "answer_system_prompt": system,
            "answer_user_prompt": user_msg,
            "phase_logs": logs,
        }

    def guardrails_node(state: GlobalAssistantGraphState) -> GlobalAssistantGraphState:
        status = state.get("sufficiency_status", "need_clarify")
        route = state.get("route_decision", "hybrid")
        response = state.get("response", "")
        citations = list(state.get("citations") or [])
        logs = list(state.get("phase_logs") or [])
        logs.append("guardrails")

        if state.get("answer_status") == "plan_ready":
            return {**state, "phase_logs": logs}
        if state.get("answer_status") == "ready_to_generate":
            return {**state, "phase_logs": logs}

        if status == "need_clarify":
            return {
                **state,
                "answer_status": "clarify",
                "response": "Нужны уточнения для надежного ответа по вашим источникам. Уточните вопрос или добавьте релевантные документы.",
                "citations": [],
                "phase_logs": logs,
            }
        if status == "no_answer":
            return {
                **state,
                "answer_status": "no_answer",
                "response": "В загруженных источниках недостаточно правового основания для ответа. Уточните запрос или добавьте релевантный нормативный материал.",
                "citations": [],
                "phase_logs": logs,
            }

        # strict legal check
        if route in {"law", "hybrid"} and not any(c.get("source_type") == "legal_corpus" for c in citations):
            return {
                **state,
                "answer_status": "no_answer",
                "response": "В загруженных правовых источниках не найдено достаточного основания для ответа.",
                "citations": [],
                "phase_logs": logs,
            }

        # Ensure inline refs exist if citations exist
        if citations and not re.search(r"\[\d+\]", response or ""):
            refs = " ".join(f"[{i}]" for i in range(1, len(citations) + 1))
            response = f"{response}\n\n{refs}"

        return {**state, "response": response, "answer_status": state.get("answer_status") or "ok", "phase_logs": logs}

    def finalize_node(state: GlobalAssistantGraphState, runtime_config: Optional[Dict[str, Any]] = None) -> GlobalAssistantGraphState:
        logs = list(state.get("phase_logs") or [])
        logs.append("finalize")
        try:
            store = (runtime_config or {}).get("store") if isinstance(runtime_config, dict) else None
            user_id = (state.get("user_id") or "").strip()
            if store and user_id and hasattr(store, "put"):
                payload = {
                    "summary": (state.get("conversation_summary") or "").strip()[:4000],
                    "updated_by_query": (state.get("user_query") or "").strip()[:500],
                }
                store.put(("memory", user_id), "global_assistant_summary", payload)
                matter_key = _primary_matter_key(state)
                store.put(
                    ("matter", user_id, matter_key),
                    "summary",
                    {
                        "summary": (state.get("conversation_summary") or "").strip()[:4000],
                        "query": (state.get("user_query") or "")[:300],
                    },
                )
                # Write-policy: only confirmed, compact facts.
                facts = _extract_confirmed_facts_for_memory(state)
                for fact in facts:
                    fact_key = f"fact_{abs(hash(fact)) % 10_000_000:07d}"
                    store.put(
                        ("memory_facts", user_id),
                        fact_key,
                        {
                            "fact": fact,
                            "source": "global_assistant",
                            "query": (state.get("user_query") or "")[:300],
                        },
                    )
                    store.put(
                        ("matter_facts", user_id, matter_key),
                        fact_key,
                        {
                            "fact": fact,
                            "source": "global_assistant",
                            "query": (state.get("user_query") or "")[:300],
                        },
                    )
        except Exception as ex:
            logger.debug("Global memory persist skipped: %s", ex)
        return {**state, "phase_logs": logs}

    def route_after_mode(state: GlobalAssistantGraphState) -> str:
        route = state.get("route_decision", "hybrid")
        if route == "matter":
            return "matter"
        if route == "law":
            return "law"
        if route == "clarify":
            return "clarify"
        return "hybrid"

    graph.add_node("ingress", ingress_node)
    graph.add_node("mode_gate", mode_gate_node)
    graph.add_node("load_memory", load_memory_node)
    graph.add_node("route", route_node)
    graph.add_node("retrieve_matter", retrieve_matter_node)
    graph.add_node("retrieve_law", retrieve_law_node)
    graph.add_node("merge_rerank", merge_rerank_node)
    graph.add_node("sufficiency", sufficiency_node)
    graph.add_node("answer", answer_node)
    graph.add_node("guardrails", guardrails_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "ingress")
    graph.add_edge("ingress", "mode_gate")
    graph.add_edge("mode_gate", "load_memory")
    graph.add_edge("load_memory", "route")
    graph.add_conditional_edges(
        "route",
        route_after_mode,
        {
            "matter": "retrieve_matter",
            "law": "retrieve_law",
            "hybrid": "retrieve_matter",
            "clarify": "merge_rerank",
        },
    )
    graph.add_edge("retrieve_matter", "retrieve_law")
    graph.add_edge("retrieve_law", "merge_rerank")
    graph.add_edge("merge_rerank", "sufficiency")
    graph.add_edge("sufficiency", "answer")
    graph.add_edge("answer", "guardrails")
    graph.add_edge("guardrails", "finalize")
    graph.add_edge("finalize", END)
    return graph


class GlobalAssistantLangGraphService:
    """Runs multi-source global assistant graph."""

    _graph = None

    @classmethod
    def _reset_graph_runtime(cls) -> None:
        """Reset cached graph and DB-backed runtime components."""
        try:
            reset_checkpointer_instance()
        except Exception:
            pass
        try:
            reset_store_instance()
        except Exception:
            pass
        cls._graph = None

    @classmethod
    def _get_graph(cls):
        if cls._graph is None:
            graph = _build_graph()
            compile_kwargs: Dict[str, Any] = {}
            store = get_store_instance()
            if store is not None:
                compile_kwargs["store"] = store
            checkpointer = get_checkpointer_instance()
            if checkpointer is not None:
                checkpointer = wrap_postgres_saver_if_needed(checkpointer)
                cls._graph = graph.compile(checkpointer=checkpointer, **compile_kwargs)
            else:
                cls._graph = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)
        return cls._graph

    async def run(
        self,
        *,
        user_query: str,
        chat_history: List[Dict[str, str]],
        draft_mode: bool,
        draft_approved: bool = False,
        draft_modifications: str = "",
        draft_plan: Optional[Dict[str, Any]] = None,
        use_legal_corpus: bool,
        matter_contexts: List[Dict[str, Any]],
        user_id: str = "",
        thread_id: str = "",
        mode: Optional[str] = None,
    ) -> GlobalAssistantGraphResult:
        graph = self._get_graph()
        initial: GlobalAssistantGraphState = {
            "user_id": user_id or "",
            "user_query": user_query,
            "chat_history": chat_history,
            "draft_mode": draft_mode,
            "draft_approved": bool(draft_approved),
            "draft_modifications": draft_modifications or "",
            "draft_plan": draft_plan or {},
            "use_legal_corpus": bool(use_legal_corpus or getattr(config, "LEGAL_CORPUS_FORCE_ENABLED", True)),
            "matter_contexts": matter_contexts,
            "phase_logs": [],
            "matter_hits": [],
            "law_hits": [],
            "merged_hits": [],
            "citations": [],
            "route_decision": "hybrid",
            "route_confidence": 0.0,
            "route_reason": "",
            "sufficiency_status": "need_clarify",
            "answer_status": "init",
            "response": "",
            "mode": mode or "",
        }
        invoke_config: Dict[str, Any] = {"recursion_limit": 25}
        if thread_id:
            invoke_config["configurable"] = {"thread_id": thread_id}
        callbacks = get_langchain_callbacks(
            session_id=thread_id or None,
            user_id=user_id or None,
            tags=["assistant", "global_assistant", "langgraph"],
        )
        if callbacks:
            invoke_config["callbacks"] = callbacks
        trace_contract_event(
            get_active_trace_context(),
            name="request_routed",
            metadata=normalize_observability_metadata(
                {
                    "assistant_type": "global_assistant",
                    "mode": mode or "",
                    "execution_path": "global_langgraph",
                },
                step_name="global_graph_invoke",
                status="running",
            ),
            input_payload={"user_query": user_query},
        )
        try:
            result: GlobalAssistantGraphState = await __import__("asyncio").to_thread(
                graph.invoke, initial, invoke_config
            )
        except Exception as exc:
            if not _is_transient_db_connection_error(exc):
                raise
            logger.warning("Global graph transient DB error, recreating runtime and retrying once: %s", exc)
            self._reset_graph_runtime()
            graph = self._get_graph()
            result = await __import__("asyncio").to_thread(graph.invoke, initial, invoke_config)
        phase_logs = result.get("phase_logs") or []
        for idx, phase in enumerate(phase_logs, start=1):
            trace_contract_event(
                get_active_trace_context(),
                name="llm_generation",
                metadata=normalize_observability_metadata(
                    {
                        "assistant_type": "global_assistant",
                        "execution_path": "global_langgraph",
                        "phase": phase,
                        "phase_index": idx,
                    },
                    step_name=f"graph_phase:{phase}",
                    status="success",
                ),
            )
        return GlobalAssistantGraphResult(
            response=result.get("response") or "",
            citations=result.get("citations") or [],
            route_decision=result.get("route_decision", "hybrid"),
            route_confidence=float(result.get("route_confidence", 0.0)),
            sufficiency_status=result.get("sufficiency_status", "need_clarify"),
            answer_status=result.get("answer_status", "unknown"),
            phase_logs=phase_logs,
            draft_plan=result.get("draft_plan"),
            draft_plan_id=result.get("draft_plan_id"),
            model_reasoning=result.get("model_reasoning"),
            answer_system_prompt=result.get("answer_system_prompt"),
            answer_user_prompt=result.get("answer_user_prompt"),
        )
