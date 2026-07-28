"""
Rewrite a lawyer's tabular column prompt into a multi-channel retrieval plan.

Produces:
- ``semantic_query`` — primary short query for dense / hybrid embeddings
- ``search_queries`` — 1–4 alternate queries in **document language** (same
  language as the column question: RU for production DD, EN when the column
  is English). Abbreviations and analyst jargon are expanded to phrasing that
  actually appears in contracts.
- ``lexical_terms`` — key concepts / synonyms for independent literal recall
- ``exact_query`` — optional clause anchor (e.g. ``1.4``) for boundary-exact recall
- ``exact_literals`` — amounts / quoted tokens for literal boost

Extraction still uses the full ``column.prompt``. Rewrite runs once per column
(see ``TabularColumnRunContext``).

Backward compatibility: ``search_query`` is an alias of ``semantic_query``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Literal, Optional, Sequence, Tuple

from pydantic import AliasChoices, BaseModel, Field, field_validator

from app.config import config
from app.services.clause_anchor import normalize_clause_number, primary_exact_anchor
from app.services.retrieval_channels import (
    dedupe_terms_by_stem,
    extract_exact_literals,
    extract_lexical_terms,
    is_interrogative_query,
)

logger = logging.getLogger(__name__)

RewriteMethod = Literal["llm", "heuristic", "passthrough", "disabled", "fallback"]

_MAX_SEARCH_QUERY_CHARS = 180
_MAX_SEARCH_QUERY_WORDS = 16
_HEURISTIC_MAX_WORDS = 10
_MAX_LEXICAL_TERMS = 14
_MAX_SEARCH_QUERIES = 4

# Imperative / delivery phrasing that hurts lexical + dense retrieval (RU + EN).
_INSTRUCTION_VERBS = (
    r"найди(?:те)?|найти|отыщи(?:те)?|поискай(?:те)?|"
    r"пришли(?:те)?|отправь(?:те)?|выпиши(?:те)?|выведи(?:те)?|"
    r"укажи(?:те)?|извлеки(?:те)?|определи(?:те)?|сформулируй(?:те)?|"
    r"покажи(?:те)?|дай(?:те)?|верни(?:те)?|предоставь(?:те)?|"
    r"процитируй(?:те)?|прочитай(?:те)?|посмотри(?:те)?|"
    r"find|extract|return|provide|show|give|quote|read|look\s+up|retrieve"
)

_LEADING_INSTRUCTION_RE = re.compile(
    rf"^(?:(?:и|а|или|and|or|please)\s+)?(?:{_INSTRUCTION_VERBS})\b[\s,.:;\-–—]*",
    re.IGNORECASE,
)
_LEADING_IN_DOC_RE = re.compile(
    r"^(?:в\s+(?:этом\s+)?документе|по\s+документу|из\s+документа|"
    r"в\s+тексте(?:\s+документа)?|в\s+договоре|"
    r"in\s+(?:this\s+)?(?:document|agreement|contract)|from\s+the\s+(?:document|agreement))\b"
    r"[\s,.:;\-–—]*",
    re.IGNORECASE,
)
_TRAILING_DELIVERY_RE = re.compile(
    rf"(?:[\s,.;:]+(?:и\s+|and\s+)?)?(?:{_INSTRUCTION_VERBS})\b.*$",
    re.IGNORECASE,
)
_STOPWORD_ONLY_RE = re.compile(
    r"^(?:и|а|или|в|на|по|из|для|о|об|про|его|её|их|мне|нам|"
    r"and|or|the|a|an|of|to|in|on|for|with)$",
    re.IGNORECASE,
)
_FILLER_PHRASES_RE = re.compile(
    r"\b(?:"
    r"пожалуйста|полностью|целиком|дословно|"
    r"и\s+пришли\s+мне\s+его\s+полностью|"
    r"и\s+пришли\s+полностью|"
    r"мне\s+его\s+полностью|"
    r"его\s+полностью|"
    r"раздел\s+документа|"
    r"please|verbatim|exactly|concise(?:ly)?|"
    r"you\s+are\s+reviewing\s+a\s+.+?\.|"
    r"deal\s+point\s*:|"
    r"question\s+field\s*:|"
    r"answer\s+with\s+the\s+exact\s+deal\s+point\s+value.+|"
    r"used\s+in\s+\w+\s+annotations?.+|"
    r"be\s+concise\.?"
    r")\b",
    re.IGNORECASE,
)
_EXAMPLE_PAREN_RE = re.compile(r"\(e\.g\.[^)]*\)", re.IGNORECASE)
_TRAILING_EXAMPLE_FRAGMENT_RE = re.compile(
    r"(?:^|[\s,;])(?:e\.g\.|eg\.|например)\b.*$",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")
_QUOTE_TRIM_RE = re.compile(r'^[\s"«»„“”\'`]+|[\s"«»„“”\'`]+$')
_CLAUSE_NUMBER_ONLY_RE = re.compile(r"^\d+(?:\.\d+)+$")
_NULLISH_QUERY_VALUES = frozenset({"null", "none", "n/a", "nil", "-", "undefined"})
_ACRONYM_RE = re.compile(r"\b[A-ZА-Я]{2,6}\b")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_LETTER_RE = re.compile(r"[А-Яа-яЁё]")


def _is_nullish_query(value: Any) -> bool:
    """True for empty / JSON-null-as-string placeholders from weak structured LLMs."""
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in _NULLISH_QUERY_VALUES


def _predominantly_latin(text: str) -> bool:
    latin = len(_LATIN_LETTER_RE.findall(text or ""))
    cyr = len(_CYRILLIC_LETTER_RE.findall(text or ""))
    total = latin + cyr
    if total < 3:
        return False
    return (latin / total) >= 0.6


def _has_acronym_token(text: str) -> bool:
    return bool(_ACRONYM_RE.search(text or ""))


def sanitize_search_query(text: str) -> str:
    """Deterministic cleanup: strip delivery language, collapse whitespace, cap length."""
    q = _QUOTE_TRIM_RE.sub("", (text or "").strip())
    if not q:
        return ""

    q = _EXAMPLE_PAREN_RE.sub(" ", q)
    for _ in range(3):
        nxt = _LEADING_INSTRUCTION_RE.sub("", q)
        nxt = _LEADING_IN_DOC_RE.sub("", nxt)
        nxt = _TRAILING_DELIVERY_RE.sub("", nxt)
        nxt = _FILLER_PHRASES_RE.sub(" ", nxt)
        nxt = _TRAILING_EXAMPLE_FRAGMENT_RE.sub(" ", nxt)
        nxt = _WHITESPACE_RE.sub(" ", nxt).strip(" \t\r\n,.;:!?-–—)(")
        if nxt == q:
            break
        q = nxt

    q = _QUOTE_TRIM_RE.sub("", q)
    q = _WHITESPACE_RE.sub(" ", q).strip(" \t\r\n,.;:!?-–—)(")
    # Drop format-example leftovers that are not topical retrieval queries.
    lower = q.lower()
    if any(
        bad in lower
        for bad in (
            "yes/no",
            "all cash, each",
            "each covenant",
            "n/a",
        )
    ) and len(q.split()) <= 8:
        return ""
    if _STOPWORD_ONLY_RE.match(q):
        return ""
    if len(q) > _MAX_SEARCH_QUERY_CHARS:
        q = q[:_MAX_SEARCH_QUERY_CHARS].rsplit(" ", 1)[0].strip()

    words = q.split()
    if len(words) > _MAX_SEARCH_QUERY_WORDS:
        q = " ".join(words[:_MAX_SEARCH_QUERY_WORDS])
    if _STOPWORD_ONLY_RE.match(q):
        return ""
    return q


def _normalize_query_list(value: Any, *, limit: int = _MAX_SEARCH_QUERIES) -> List[str]:
    if value is None or _is_nullish_query(value):
        return []
    raw_items: List[str] = []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(x) for x in value]
    else:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if _is_nullish_query(item):
            continue
        cleaned = sanitize_search_query(str(item))
        if not cleaned:
            continue
        key = cleaned.lower().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


class TabularSearchQueryLLMOutput(BaseModel):
    """Structured multi-channel rewrite for hybrid / lexical / exact retrieval."""

    semantic_query: str = Field(
        default="",
        description=(
            "Required non-empty short query for dense/hybrid in the SAME language "
            "as the lawyer question (RU or EN). Never null or empty."
        ),
        validation_alias=AliasChoices("semantic_query", "search_query"),
    )
    search_queries: List[str] = Field(
        default_factory=list,
        description=(
            "2–4 short alternate retrieval queries in document language. "
            "Expand abbreviations and analyst jargon to full contractual phrasing."
        ),
    )
    lexical_terms: List[str] = Field(
        default_factory=list,
        description=(
            "Key concepts and close synonyms for literal/keyword recall "
            "(document language). Never empty when the question contains content words."
        ),
    )
    exact_query: Optional[str] = Field(
        default=None,
        description="Clause number for boundary-exact recall (e.g. 1.4), or omit if none",
    )
    exact_literals: List[str] = Field(
        default_factory=list,
        description="Optional amounts / quoted names for literal boost",
    )
    rationale: str = Field(
        default="",
        description="One short reason (debug only)",
    )

    @field_validator("semantic_query", mode="before")
    @classmethod
    def _normalize_semantic_query(cls, value: Any) -> str:
        if _is_nullish_query(value):
            return ""
        return str(value).strip()

    @field_validator("rationale", mode="before")
    @classmethod
    def _normalize_rationale(cls, value: Any) -> str:
        if _is_nullish_query(value):
            return ""
        return str(value).strip()

    @field_validator("exact_query", mode="before")
    @classmethod
    def _normalize_exact_query(cls, value: Any) -> Optional[str]:
        if _is_nullish_query(value):
            return None
        text = str(value).strip()
        anchored = primary_exact_anchor(text) or normalize_clause_number(text)
        if anchored and _CLAUSE_NUMBER_ONLY_RE.match(anchored):
            return anchored
        return None

    @field_validator("lexical_terms", "exact_literals", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> List[str]:
        if value is None or _is_nullish_query(value):
            return []
        if isinstance(value, str):
            parts = re.split(r"[,;|/]+", value)
            return [p.strip() for p in parts if p and str(p).strip()]
        if isinstance(value, (list, tuple, set)):
            out: List[str] = []
            for item in value:
                if _is_nullish_query(item):
                    continue
                text = str(item).strip()
                if text:
                    out.append(text)
            return out
        return []

    @field_validator("search_queries", mode="before")
    @classmethod
    def _normalize_search_queries(cls, value: Any) -> List[str]:
        return _normalize_query_list(value, limit=_MAX_SEARCH_QUERIES)


@dataclass(frozen=True)
class TabularSearchQueryRewriteResult:
    """Outcome of preparing column retrieval queries."""

    search_query: str
    source_query: str
    method: RewriteMethod
    rationale: str = ""
    exact_query: Optional[str] = None
    lexical_terms: Tuple[str, ...] = ()
    exact_literals: Tuple[str, ...] = ()
    search_queries: Tuple[str, ...] = ()

    @property
    def semantic_query(self) -> str:
        return self.search_query


def tabular_search_query_rewrite_enabled() -> bool:
    return bool(getattr(config, "TABULAR_SEARCH_QUERY_REWRITE_ENABLED", True))


def column_source_query(column: Any) -> str:
    """Lawyer-facing text for the column (prompt preferred over label)."""
    prompt = str(getattr(column, "prompt", None) or "").strip()
    if prompt:
        return prompt
    return str(getattr(column, "column_label", None) or "").strip()


def heuristic_exact_query(
    source_query: str,
    *,
    column_label: str = "",
) -> Optional[str]:
    """Extract a clause-number exact anchor from prompt/label when present."""
    return primary_exact_anchor(source_query) or primary_exact_anchor(column_label)


def _looks_like_instruction(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _LEADING_INSTRUCTION_RE.match(t):
        return True
    lower = t.lower()
    return any(
        marker in lower
        for marker in (
            "пришли",
            "найди",
            "извлеки",
            "полностью",
            "пожалуйста",
            "пришлите",
            "укажите",
            "процитируй",
            "о чем",
            "о чём",
            "про что",
            "please",
            "extract",
            "find the",
            "look up",
            "you are reviewing",
        )
    )


def _word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w])


def heuristic_search_query(
    source_query: str,
    *,
    column_type: str = "text",
    column_label: str = "",
) -> str:
    """
    Non-LLM rewrite: strip instruction phrasing; fall back to label if needed.

    For interrogatives / yes_no, prefer content terms over the full question form.
    """
    cleaned = sanitize_search_query(source_query)
    label = sanitize_search_query(column_label)
    ct = (column_type or "text").strip().lower()

    if ct == "yes_no" or is_interrogative_query(source_query) or is_interrogative_query(cleaned):
        terms = extract_lexical_terms(cleaned, label, limit=_MAX_LEXICAL_TERMS)
        if terms:
            return _maybe_append_type_hint(" ".join(terms[:8]), column_type)

    if cleaned and not _looks_like_instruction(cleaned) and not _STOPWORD_ONLY_RE.match(cleaned):
        return _maybe_append_type_hint(cleaned, column_type)

    if label and not _looks_like_instruction(label):
        return _maybe_append_type_hint(label, column_type)

    if cleaned:
        return _maybe_append_type_hint(cleaned, column_type)
    return _maybe_append_type_hint(label, column_type)


def heuristic_lexical_terms(
    source_query: str,
    *,
    column_label: str = "",
    semantic_query: str = "",
) -> Tuple[str, ...]:
    return extract_lexical_terms(
        source_query,
        column_label,
        semantic_query,
        limit=_MAX_LEXICAL_TERMS,
    )


def _merge_term_lists(*groups: Sequence[str], limit: int = _MAX_LEXICAL_TERMS) -> Tuple[str, ...]:
    raw: List[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or ():
            term = str(item or "").strip()
            if not term:
                continue
            key = term.lower().replace("ё", "е")
            if key in seen:
                continue
            seen.add(key)
            raw.append(term)
    return dedupe_terms_by_stem(raw, limit=limit)


def _merge_search_queries(
    primary: str,
    *groups: Sequence[str],
    limit: int = _MAX_SEARCH_QUERIES,
) -> Tuple[str, ...]:
    return tuple(
        _normalize_query_list(
            [primary, *[q for group in groups for q in (group or ())]],
            limit=limit,
        )
    )


def _maybe_append_type_hint(query: str, column_type: str) -> str:
    """Light type cue only when the query itself does not already imply it."""
    q = (query or "").strip()
    if not q:
        return q
    ct = (column_type or "text").strip().lower()
    lower = q.lower()
    if ct == "date" and "дат" not in lower and "date" not in lower:
        suffix = "date" if _predominantly_latin(q) else "дата"
        return sanitize_search_query(f"{q} {suffix}")
    if ct == "currency" and not any(
        x in lower
        for x in ("сумм", "цен", "стоим", "руб", "amount", "price", "consideration", "cash")
    ):
        suffix = "amount" if _predominantly_latin(q) else "сумма"
        return sanitize_search_query(f"{q} {suffix}")
    return q


def _should_skip_llm(
    source_query: str,
    heuristic: str,
    *,
    column_type: str = "text",
) -> bool:
    """
    Skip LLM only for already-compact topical queries in the document language.

    Never skip:
    - interrogatives / yes_no
    - Latin/analyst labels (need expansion into contractual phrasing)
    - acronym-heavy shorthand
    """
    ct = (column_type or "text").strip().lower()
    if ct == "yes_no":
        return False
    if is_interrogative_query(source_query):
        return False
    if not heuristic:
        return False
    if _looks_like_instruction(source_query):
        return False
    if _predominantly_latin(source_query) or _predominantly_latin(heuristic):
        return False
    if _has_acronym_token(source_query) or _has_acronym_token(heuristic):
        return False
    if _word_count(source_query) > _HEURISTIC_MAX_WORDS:
        return False
    if _word_count(heuristic) > _HEURISTIC_MAX_WORDS:
        return False
    return True


def _create_rewrite_llm():
    from app.services.llm_factory import create_llm

    model = (
        str(getattr(config, "TABULAR_SEARCH_QUERY_REWRITE_MODEL", "") or "").strip()
        or str(getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "") or "").strip()
        or "yandexgpt-lite/latest"
    )
    max_tokens = max(
        160,
        int(getattr(config, "TABULAR_SEARCH_QUERY_REWRITE_MAX_TOKENS", 360) or 360),
    )
    return create_llm(model=model, temperature=0.0, max_tokens=max_tokens)


def _llm_rewrite_search_query(
    *,
    source_query: str,
    column_label: str,
    column_type: str,
) -> Optional[TabularSearchQueryLLMOutput]:
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _create_rewrite_llm()
    system = """Ты готовишь поисковый ПЛАН для retrieval по юридическим документам (договоры DD).
Каналы: dense (semantic), multi-query, lexical (ключевые слова), exact (номер пункта).
Не отвечай на вопрос юриста. Верни только JSON.

ЯЗЫК (критично):
- Пиши semantic_query, search_queries и lexical_terms на ЯЗЫКЕ ВОПРОСА ЮРИСТА.
- Русский вопрос → русский юридический язык договора (как в тексте РФ-договора).
- English question → English contractual phrasing (as written in merger agreements / contracts).
- Не переводи EN→RU и не переводи RU→EN.

ЦЕЛЬ:
- Переформулируй аналитический ярлык / сленг / аббревиатуру в формулировки, которые РЕАЛЬНО встречаются в тексте договора.
- Дай НЕСКОЛЬКО коротких поисковых фраз (search_queries), а не одну.
- Если в названии колонки есть аббревиатура или жаргон аналитика — semantic_query и search_queries ОБЯЗАНЫ содержать полную договорную формулировку.
- ЗАПРЕЩЕНО копировать примеры формата ответа из промпта (Yes/No, All Cash, Each Covenant и т.п.) в semantic_query / search_queries.
- Ориентируйся на название колонки и смысл deal point, а не на instruction-обёртку промпта.

Формат:
{"semantic_query":"...","search_queries":["...","..."],"lexical_terms":["..."],"exact_query":"","exact_literals":[],"rationale":"..."}

Примеры RU:
{"semantic_query":"неустойка штраф просрочка","search_queries":["неустойка за просрочку","штраф пеня ответственность","размер неустойки"],"lexical_terms":["неустойка","штраф","пеня","просрочка","ответственность"],"exact_query":"","exact_literals":[],"rationale":"yes_no_liability"}
{"semantic_query":"предмет договора","search_queries":["предмет договора","существенные условия поставки"],"lexical_terms":["предмет","договора","поставка"],"exact_query":"","exact_literals":[],"rationale":"section_title"}
{"semantic_query":"пункт 1.4","search_queries":["пункт 1.4"],"lexical_terms":["пункт","1.4"],"exact_query":"1.4","exact_literals":[],"rationale":"clause_number"}

Примеры EN (тот же принцип — язык документа, не ярлык колонки):
{"semantic_query":"Material Adverse Effect definition","search_queries":["Material Adverse Effect","would reasonably be expected to","Company Material Adverse Effect taken as a whole"],"lexical_terms":["Material Adverse Effect","reasonably be expected","taken as a whole","adverse effect"],"exact_query":"","exact_literals":[],"rationale":"defined_term_expansion"}
{"semantic_query":"type of merger consideration cash stock","search_queries":["merger consideration","per share in cash","exchange ratio"],"lexical_terms":["consideration","cash","stock","per share","exchange ratio"],"exact_query":"","exact_literals":[],"rationale":"consideration"}
{"semantic_query":"general political social conditions MAE carveout","search_queries":["changes in general political conditions","changes in social conditions","Material Adverse Effect carveout"],"lexical_terms":["political","social","conditions","carveout","Material Adverse Effect"],"exact_query":"","exact_literals":[],"rationale":"carveout_expansion"}

Плохо (так НЕ делай для EN-ярлыков):
{"semantic_query":"FLS MAE standard","search_queries":["FLS MAE standard"],"lexical_terms":["FLS","MAE"],...}
Хорошо:
{"semantic_query":"Material Adverse Effect would reasonably be expected","search_queries":["Material Adverse Effect","would reasonably be expected to","forward looking Material Adverse Effect"],"lexical_terms":["Material Adverse Effect","reasonably be expected","forward looking"],...}

semantic_query (ОБЯЗАТЕЛЬНО):
- 2–12 слов; тема / раздел / определённый термин / «пункт N.M»;
- БЕЗ вопросительной формы и императивов;
- ЗАПРЕЩЕНО: null, пустая строка, «deal point», «question field».

search_queries (ОБЯЗАТЕЛЬНО, 2–4 штуки):
- короткие альтернативные запросы для отдельного hybrid recall;
- включай полные развёртки аббревиатур и близкие договорные синонимы;
- первая может совпадать с semantic_query;
- без канцелярии бенчмарка/UI.

lexical_terms (ОБЯЗАТЕЛЬНО если есть смысловые слова):
- 3–10 понятий и синонимов для буквального поиска на языке документа;
- для ответственности: неустойка/штраф/пеня; для defined terms — полная фраза + ключевые куски;
- не включай служебные слова (ли, есть, the, deal, point).

exact_query: номер пункта («1.4») или "" .
exact_literals: суммы / кавычки, иначе [].
"""
    human = (
        f"Тип колонки: {column_type or 'text'}\n"
        f"Название колонки: {column_label or '—'}\n"
        f"Вопрос / промпт юриста:\n{source_query}"
    )
    messages = [SystemMessage(content=system), HumanMessage(content=human)]

    if hasattr(llm, "with_structured_output"):
        try:
            structured = llm.with_structured_output(TabularSearchQueryLLMOutput)
            parsed = structured.invoke(messages)
            if isinstance(parsed, TabularSearchQueryLLMOutput):
                return parsed
            if isinstance(parsed, dict):
                return TabularSearchQueryLLMOutput.model_validate(parsed)
        except Exception:
            logger.debug("Tabular search-query structured LLM failed", exc_info=True)

    resp = llm.invoke(messages)
    text = resp.content if hasattr(resp, "content") else str(resp)
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    return TabularSearchQueryLLMOutput.model_validate_json(match.group())


def _prefer_expanded_semantic(
    cleaned: str,
    *,
    column_label: str,
    search_queries: Sequence[str],
) -> str:
    """If model kept the raw analyst label, prefer a longer document-language alternate."""
    primary = (cleaned or "").strip()
    label = sanitize_search_query(column_label)
    if not primary:
        return primary
    primary_key = primary.lower().replace("ё", "е")
    label_key = label.lower().replace("ё", "е") if label else ""
    if label_key and primary_key != label_key:
        return primary
    # Only rewrite when primary is the label (or empty label with very short primary).
    if label_key and primary_key == label_key:
        candidates = [
            q
            for q in search_queries
            if str(q).strip() and str(q).strip().lower().replace("ё", "е") != primary_key
        ]
        if not candidates:
            return primary
        best = max(candidates, key=lambda q: (len(q), q))
        if len(best) >= len(primary) + 4:
            return best
    return primary


def _result(
    *,
    search_query: str,
    source_query: str,
    method: RewriteMethod,
    rationale: str = "",
    exact_query: Optional[str] = None,
    lexical_terms: Sequence[str] = (),
    exact_literals: Sequence[str] = (),
    search_queries: Sequence[str] = (),
    column_label: str = "",
) -> TabularSearchQueryRewriteResult:
    queries = _merge_search_queries(search_query, search_queries)
    # Lexical from document-language queries/label — not from the raw lawyer prompt
    # (EN wrappers like "You are reviewing…" pollute the keyword channel).
    terms = _merge_term_lists(
        lexical_terms,
        heuristic_lexical_terms(
            search_query,
            column_label=column_label,
            semantic_query=" ".join(queries),
        ),
        limit=_MAX_LEXICAL_TERMS,
    )
    literals = _merge_term_lists(
        exact_literals,
        extract_exact_literals(source_query),
        limit=6,
    )
    return TabularSearchQueryRewriteResult(
        search_query=search_query,
        source_query=source_query,
        method=method,
        rationale=rationale,
        exact_query=exact_query,
        lexical_terms=terms,
        exact_literals=literals,
        search_queries=queries,
    )


def rewrite_tabular_search_query(
    column: Any,
    *,
    allow_llm: bool = True,
) -> TabularSearchQueryRewriteResult:
    """
    Produce semantic_query + search_queries + lexical_terms + optional exact anchors.

    allow_llm=False → heuristic only (safe for per-cell paths without column prewarm).
    """
    source = column_source_query(column)
    if not source:
        return _result(
            search_query="",
            source_query="",
            method="passthrough",
            rationale="empty_source",
        )

    column_type = str(getattr(column, "column_type", None) or "text").strip() or "text"
    column_label = str(getattr(column, "column_label", None) or "").strip()
    heuristic_exact = heuristic_exact_query(source, column_label=column_label)

    if not tabular_search_query_rewrite_enabled():
        from app.services.tabular_cell_pipeline import build_retrieval_query

        legacy = build_retrieval_query(column).strip()
        return _result(
            search_query=legacy or source,
            source_query=source,
            method="disabled",
            rationale="rewrite_disabled",
            exact_query=heuristic_exact,
            lexical_terms=heuristic_lexical_terms(
                source, column_label=column_label, semantic_query=legacy or source
            ),
            column_label=column_label,
        )

    heuristic = heuristic_search_query(
        source,
        column_type=column_type,
        column_label=column_label,
    )
    heuristic_terms = heuristic_lexical_terms(
        heuristic,
        column_label=column_label,
        semantic_query=heuristic,
    )

    if not allow_llm or _should_skip_llm(source, heuristic, column_type=column_type):
        return _result(
            search_query=heuristic or source,
            source_query=source,
            method="heuristic" if heuristic != source else "passthrough",
            rationale="compact_or_llm_disallowed",
            exact_query=heuristic_exact,
            lexical_terms=heuristic_terms,
            search_queries=(heuristic or source,),
            column_label=column_label,
        )

    try:
        llm_out = _llm_rewrite_search_query(
            source_query=source,
            column_label=column_label,
            column_type=column_type,
        )
        if llm_out is None:
            raise ValueError("empty_llm_rewrite")
        cleaned = sanitize_search_query(llm_out.semantic_query)
        if _is_nullish_query(cleaned):
            cleaned = (
                sanitize_search_query(column_label)
                or heuristic
                or sanitize_search_query(source)
                or source
            )
            rationale = f"semantic_nullish_filled:{(llm_out.rationale or '')}"[:200]
            method: RewriteMethod = "llm"
        else:
            rationale = (llm_out.rationale or "")[:200]
            method = "llm"
        if not cleaned or _is_nullish_query(cleaned):
            raise ValueError("blank_after_sanitize")
        # Prefer column label over format-example leakage that somehow survived.
        if sanitize_search_query(column_label) and cleaned.lower() in {
            "yes/no",
            "all cash",
            "each covenant",
        }:
            cleaned = sanitize_search_query(column_label) or cleaned
        exact = llm_out.exact_query or heuristic_exact
        merged_queries = _merge_search_queries(
            cleaned,
            llm_out.search_queries,
            [heuristic] if heuristic else [],
        )
        cleaned = _prefer_expanded_semantic(
            cleaned,
            column_label=column_label,
            search_queries=merged_queries,
        )
        merged_queries = _merge_search_queries(cleaned, merged_queries)
        return _result(
            search_query=cleaned,
            source_query=source,
            method=method,
            rationale=rationale,
            exact_query=exact,
            lexical_terms=_merge_term_lists(
                llm_out.lexical_terms,
                heuristic_lexical_terms(
                    cleaned,
                    column_label=column_label,
                    semantic_query=" ".join(merged_queries),
                ),
            ),
            exact_literals=_merge_term_lists(
                llm_out.exact_literals, extract_exact_literals(source)
            ),
            search_queries=merged_queries,
            column_label=column_label,
        )
    except Exception as exc:
        logger.warning(
            "Tabular search-query rewrite failed; using heuristic fallback: %s",
            exc,
        )
        return _result(
            search_query=heuristic or sanitize_search_query(source) or source,
            source_query=source,
            method="fallback",
            rationale=f"llm_error:{type(exc).__name__}",
            exact_query=heuristic_exact,
            lexical_terms=heuristic_terms,
            search_queries=(heuristic or sanitize_search_query(source) or source,),
            column_label=column_label,
        )
