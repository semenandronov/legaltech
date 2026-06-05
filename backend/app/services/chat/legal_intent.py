"""
Классификация правового intent для case vs global ассистентов.

Case assistant:
  norm_only      — запрос к норме (статья/акт), без привязки к материалам дела
  norm_and_case  — норма + материалы дела
  case_primary   — в первую очередь документы дела

Global assistant использует is_pure_norm_lookup_query / has_case_material_markers
для rules-роутинга matter|law|hybrid.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.config import config

CaseLegalIntent = Literal["norm_only", "norm_and_case", "case_primary"]

_CASE_MATERIAL_MARKERS: Tuple[str, ...] = (
    "в деле",
    "по делу",
    "в материал",
    "в договор",
    "в документ",
    "в переписк",
    "в иск",
    "в заявлен",
    "в протокол",
    "в акт",
    "наш договор",
    "наш иск",
    "прикреп",
    "загруж",
    "файл",
    "документ дела",
    "материал дела",
    "из дела",
    "сторон",
    "истец",
    "ответчик",
    "кредитор",
    "должник",
    "конкурсн",
    "реестр требован",
)

_LAW_NORM_MARKERS: Tuple[str, ...] = (
    "ст.",
    "статья",
    "статьи",
    "гк рф",
    "гпк",
    "апк",
    "ук рф",
    "фз",
    "закон",
    "пленум",
    "постановлен",
    "норм",
    "127-фз",
    "127 фз",
    "фз-127",
    "фз 127",
    "банкрот",
    "справочник",
    "кодекс",
)

# Общие справочные вопросы по банкротству/ФУ без привязки к материалам дела
_GENERAL_BANKRUPTCY_LAW_MARKERS: Tuple[str, ...] = (
    "оспарив",
    "финансовый управляющ",
    "финансового управляющ",
    "конкурсный управляющ",
    "период подозрительн",
    "срок оспарив",
    "сделк должник",
    "сделки должник",
    "сделок должник",
    "подозрительн сделк",
    "предпочтительн",
    "необоснованн",
    "неравноценн",
    "реестр требован",
    "наблюдени",
    "конкурсн производств",
    "реструктуризац",
    "реализац имуществ",
)

_WEAK_BANKRUPTCY_ROLE_TERMS: Tuple[str, ...] = (
    "должник",
    "кредитор",
    "конкурсн",
    "истец",
    "ответчик",
    "сторон",
    "реестр требован",
)


def has_case_material_markers(question: str) -> bool:
    ql = (question or "").lower()
    return any(m in ql for m in _CASE_MATERIAL_MARKERS)


def has_case_file_scope_markers(question: str) -> bool:
    """
    Привязка к материалам конкретного дела.
    Общие термины банкротства (должник, кредитор) без контекста дела — не считаются.
    """
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()
    strong = [m for m in _CASE_MATERIAL_MARKERS if m not in _WEAK_BANKRUPTCY_ROLE_TERMS]
    if any(m in ql for m in strong):
        return True
    if re.search(r"\b(наш|нашего|нашей|нашем|наши)\s+(договор|иск|должник|кредитор|акт|протокол)", ql):
        return True
    if re.search(r"\b(в|из|по)\s+(деле|материал|документ|файл)", ql):
        return True
    return False


def has_law_norm_markers(question: str) -> bool:
    ql = (question or "").lower()
    return any(m in ql for m in _LAW_NORM_MARKERS)


def is_norm_article_lookup(question: str) -> bool:
    """Явный запрос к статье или акту (без обязательной привязки к делу)."""
    from app.services.chat.legal_router import (
        detect_instruments_from_question,
        extract_article_number,
    )

    q = (question or "").strip()
    if not q:
        return False
    if extract_article_number(q):
        return True
    if detect_instruments_from_question(q):
        return True
    ql = q.lower()
    if re.search(r"\b127\s*[-\s]?фз\b|\bфз\s*[-\s]?127\b", ql):
        return True
    if re.search(r"\bбанкротств", ql) and has_law_norm_markers(q):
        return True
    return False


def is_pure_norm_lookup_query(question: str) -> bool:
    """Запрос только к справочнику норм (для global law-route)."""
    if is_general_reference_law_question(question):
        return True
    if not is_norm_article_lookup(question) and not has_law_norm_markers(question):
        return False
    return not has_case_file_scope_markers(question)


def is_general_reference_law_question(question: str) -> bool:
    """
    Справочный правовой вопрос без ссылки на материалы дела
    (оспаривание сделок, полномочия ФУ, сроки банкротства и т.п.).
    """
    q = (question or "").strip()
    if not q or has_case_file_scope_markers(q):
        return False
    ql = q.lower()
    if any(m in ql for m in _GENERAL_BANKRUPTCY_LAW_MARKERS):
        return True
    if re.search(r"\b127\s*[-\s]?фз\b|\bфз\s*[-\s]?127\b", ql) and not has_case_file_scope_markers(q):
        return True
    if re.search(r"\bбанкротств", ql) and re.search(
        r"(срок|период|право|полномоч|оспарив|сделк|управляющ)",
        ql,
    ):
        return True
    return False


def classify_case_legal_intent(
    question: str,
    *,
    legal_research: bool = False,
    mode: str = "",
    enable_garant: bool = True,
    task_type: str = "",
    attached_file_ids: Optional[List[str]] = None,
) -> Tuple[CaseLegalIntent, str]:
    q = (question or "").strip()
    if not q:
        return "case_primary", "empty_question"

    case_mat = has_case_file_scope_markers(q) or bool(attached_file_ids)
    law_norm = (
        is_norm_article_lookup(q)
        or is_general_reference_law_question(q)
        or (has_law_norm_markers(q) and (legal_research or mode == "garant"))
    )

    if mode == "garant" or legal_research:
        if law_norm and not case_mat:
            return "norm_only", "legal_norm_without_case_scope"
        if law_norm and case_mat:
            return "norm_and_case", "legal_norm_with_case_scope"
        if legal_research or mode == "garant":
            return "norm_and_case", "legal_research_broad"

    if not enable_garant:
        return "case_primary", "garant_disabled"

    tt = (task_type or "").strip().lower()
    if tt == "legal_reasoning" and law_norm and not case_mat:
        return "norm_only", "task_legal_reasoning_norm"

    if law_norm and not case_mat:
        return "norm_only", "incidental_law_question"
    if law_norm and case_mat:
        return "norm_and_case", "law_and_case_markers"

    return "case_primary", "default_case_documents"


def case_norm_only_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_LEGAL_NORM_ONLY_ENABLED", True))


def apply_norm_only_case_budget(budget_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Один проход: только legal corpus, без case RAG/rerank."""
    out = dict(budget_profile or {})
    out["recall_k"] = 0
    out["final_k"] = 0
    out["rerank_enabled"] = False
    out["max_retrieval_rounds"] = int(
        getattr(config, "CASE_ASSISTANT_LEGAL_NORM_MAX_RETRIEVAL_ROUNDS", 1) or 1
    )
    out["case_rag_skipped"] = True
    return out


def case_rag_should_run(state: Dict[str, Any]) -> bool:
    """Case-file RAG is skipped for norm-only and court-practice-only instrument turns."""
    if bool(state.get("enable_court_practice")) and not bool(state.get("enable_garant")):
        return False
    if not case_norm_only_enabled():
        return True
    intent = str(state.get("legal_intent") or "")
    if intent == "norm_only":
        return False
    bp = state.get("budget_profile") or {}
    if isinstance(bp, dict) and bp.get("case_rag_skipped"):
        return False
    return True


def court_practice_graded_sufficient(state: Dict[str, Any]) -> bool:
    """Court practice corpus is enough — skip case RAG rewrite loops."""
    if not bool(state.get("enable_court_practice")):
        return False
    ctx = (state.get("court_practice_context") or "").strip()
    if len(ctx) < 200:
        return False
    docs = state.get("court_practice_documents") or []
    if isinstance(docs, list) and docs:
        return True
    return len(ctx) >= 800


def legal_corpus_graded_sufficient(state: Dict[str, Any]) -> bool:
    """Достаточно ли справочника норм, чтобы не крутить case retrieval loop."""
    garant = (state.get("garant_context") or "").strip()
    if not garant:
        return False

    meta: Dict[str, Any] = {}
    lr = state.get("legal_route")
    if isinstance(lr, dict) and isinstance(lr.get("meta"), dict):
        meta = lr["meta"]
    elif isinstance(state.get("legal_retrieval_meta"), dict):
        meta = state["legal_retrieval_meta"]

    missing = meta.get("articles_missing")
    if isinstance(missing, list) and missing and meta.get("topic") == "article_lookup":
        return False
    if meta.get("sufficient") is True:
        return True
    if meta.get("used_fast_path") and len(garant) >= 300 and not missing:
        return True
    doc_count = int(meta.get("doc_count") or 0)
    if doc_count >= 2 and len(garant) >= 500:
        return True
    return False


def norm_only_retrieval_task_stub(question: str) -> Dict[str, Any]:
    return {
        "scope_mode": "legal_norm_only",
        "search_query": (question or "").strip(),
        "file_ids": [],
        "doc_type": None,
        "confidence": 1.0,
        "rationale": "legal_intent_norm_only",
    }
