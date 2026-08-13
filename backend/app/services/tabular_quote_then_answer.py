"""
Quote-then-answer extraction for tabular cells.

Architecture (not a special-case hack):
1) Locate a supporting verbatim quote in the retrieved fragments.
2) Snap/accept the quote only if it is grounded in those fragments.
3) Derive cell_value from the quote alone — the model cannot invent from the rest of the bag.

If no grounded quote exists → «—» (caller may fall back to single-pass + evidence gate).

Quote contract (production):
- The model may emit a near-quote; we never persist that string as-is when an OCR span exists.
- ``resolve_quote_span_in_original`` / ``snap_quote_to_corpus`` always return text from the
  corpus (original_text / retrieval bag), never the model paraphrase.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.tabular_extraction_policy import (
    TABULAR_NA_VALUE,
    ensure_na_reasoning,
)
from app.services.tabular_extraction_schemas import (
    extraction_schema_for_column,
    typed_extraction_to_cell_model,
)
from app.services.tabular_review_models import TabularCellExtractionModel

logger = logging.getLogger(__name__)

_MIN_QUOTE_LEN = 20
# Contiguous OCR match must cover at least this fraction of the normalized model quote.
_MIN_SNAP_COVERAGE = 0.75


def normalize_for_grounding(text: str) -> str:
    t = (text or "").replace("\u00a0", " ")
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", " ", t.strip()).lower()
    return t


def _grounding_norm_and_map(original: str) -> Tuple[str, List[int]]:
    """
    Build normalize_for_grounding(original) plus norm-index → raw-index map.

    Each normalized character maps to the raw offset of the source character in ``original``.
    """
    mapping: List[int] = []
    chars: List[str] = []
    prev_space = True
    for i, ch in enumerate(original or ""):
        if ch == "\u00a0":
            ch = " "
        elif ch in "“”":
            ch = '"'
        elif ch in "‘’":
            ch = "'"
        elif ch in "–—":
            ch = "-"
        ch_l = ch.lower()
        if ch_l.isspace():
            if prev_space:
                continue
            chars.append(" ")
            mapping.append(i)
            prev_space = True
            continue
        chars.append(ch_l)
        mapping.append(i)
        prev_space = False
    while chars and chars[0] == " ":
        chars.pop(0)
        mapping.pop(0)
    while chars and chars[-1] == " ":
        chars.pop()
        mapping.pop()
    return "".join(chars), mapping


def _map_grounding_norm_range_to_raw(
    mapping: List[int],
    original_len: int,
    norm_start: int,
    norm_end: int,
) -> Optional[Tuple[int, int]]:
    if norm_end <= norm_start or norm_start < 0 or not mapping:
        return None
    if norm_start >= len(mapping):
        return None
    raw_start = mapping[norm_start]
    if norm_end >= len(mapping):
        raw_end = original_len
    else:
        raw_end = mapping[norm_end]
    if raw_end <= raw_start:
        return None
    return raw_start, raw_end


def _alnum_norm_and_map(original: str) -> Tuple[str, List[int]]:
    """
    Letter/digit normalization for punctuation drift (commas, periods).

    Punctuation is skipped in the normalized form but still covered by the raw
    span when mapping back (raw_end advances to the next kept character).
    """
    mapping: List[int] = []
    chars: List[str] = []
    prev_space = True
    for i, ch in enumerate(original or ""):
        if ch == "\u00a0":
            ch = " "
        ch_l = ch.lower()
        if ch_l.isspace():
            if prev_space:
                continue
            chars.append(" ")
            mapping.append(i)
            prev_space = True
            continue
        if not ch_l.isalnum():
            continue
        chars.append(ch_l)
        mapping.append(i)
        prev_space = False
    while chars and chars[0] == " ":
        chars.pop(0)
        mapping.pop(0)
    while chars and chars[-1] == " ":
        chars.pop()
        mapping.pop()
    return "".join(chars), mapping


def _expand_span_to_token_bounds(
    original: str,
    start: int,
    end: int,
    *,
    max_expand: int = 48,
) -> Tuple[int, int]:
    """
    If a fuzzy match starts/ends mid-token, expand to the nearest whitespace bounds.

    Keeps highlights and displayed quotes on whole OCR words (e.g. полный
    «недвижимое», а не хвост «ое»).
    """
    n = len(original or "")
    if not original or end <= start or start < 0 or end > n:
        return start, end

    s, e = start, end
    if s > 0 and not original[s].isspace() and not original[s - 1].isspace():
        left = s
        budget = max_expand
        while left > 0 and not original[left - 1].isspace() and budget > 0:
            left -= 1
            budget -= 1
        s = left

    if e < n and e > 0 and not original[e - 1].isspace() and not original[e].isspace():
        right = e
        budget = max_expand
        while right < n and not original[right].isspace() and budget > 0:
            right += 1
            budget -= 1
        e = right

    return s, e


def resolve_quote_span_in_original(
    quote: str,
    original: str,
    *,
    min_len: int = _MIN_QUOTE_LEN,
    min_coverage: float = _MIN_SNAP_COVERAGE,
) -> Optional[Tuple[int, int]]:
    """
    Locate a contiguous OCR/original span for ``quote``.

    Returns half-open [start, end) into ``original``, or None when no contiguous
    match covers enough of the quote. Never invents offsets outside ``original``.
    """
    raw_quote = (quote or "").strip()
    # Below 12 chars: too ambiguous for production snap (use exact locate elsewhere).
    if len(raw_quote) < 12 or not original:
        return None

    q = normalize_for_grounding(raw_quote)
    need = max(12, int(min_coverage * len(q))) if len(q) < min_len else max(
        min_len, int(min_coverage * len(q))
    )

    def _finish(span: Optional[Tuple[int, int]], *, fuzzy: bool) -> Optional[Tuple[int, int]]:
        if span is None:
            return None
        start, end = span
        if fuzzy:
            start, end = _expand_span_to_token_bounds(original, start, end)
        return start, end

    # 1) Exact whitespace/dash-normalized containment.
    body, mapping = _grounding_norm_and_map(original)
    if body and len(q) >= 12:
        idx = body.find(q)
        if idx != -1:
            return _finish(
                _map_grounding_norm_range_to_raw(
                    mapping, len(original), idx, idx + len(q)
                ),
                fuzzy=False,
            )

    # 2) Punctuation-insensitive containment (commas / periods dropped by model).
    body_a, map_a = _alnum_norm_and_map(original)
    q_a, _ = _alnum_norm_and_map(raw_quote)
    if body_a and len(q_a) >= 12:
        idx = body_a.find(q_a)
        if idx != -1:
            mapped = _map_grounding_norm_range_to_raw(
                map_a, len(original), idx, idx + len(q_a)
            )
            if mapped is not None:
                start, end = mapped
                while (
                    end < len(original)
                    and not original[end].isalnum()
                    and not original[end].isspace()
                ):
                    end += 1
                return _finish((start, end), fuzzy=False)

    # Fuzzy paths require the full production minimum length.
    if len(q) < min_len and len(q_a) < min_len:
        return None

    # 3) Longest contiguous near-match (one-word paraphrase / OCR drift).
    if body and len(q) >= min_len:
        matcher = SequenceMatcher(None, q, body, autojunk=False)
        match = matcher.find_longest_match(0, len(q), 0, len(body))
        if match.size >= need:
            return _finish(
                _map_grounding_norm_range_to_raw(
                    mapping, len(original), match.b, match.b + match.size
                ),
                fuzzy=True,
            )

    # 4) Same on alnum-folded strings.
    if body_a and len(q_a) >= min_len:
        need_a = max(min_len, int(min_coverage * len(q_a)))
        matcher = SequenceMatcher(None, q_a, body_a, autojunk=False)
        match = matcher.find_longest_match(0, len(q_a), 0, len(body_a))
        if match.size >= need_a:
            mapped = _map_grounding_norm_range_to_raw(
                map_a, len(original), match.b, match.b + match.size
            )
            if mapped is not None:
                start, end = mapped
                while (
                    end < len(original)
                    and not original[end].isalnum()
                    and not original[end].isspace()
                ):
                    end += 1
                return _finish((start, end), fuzzy=True)

    return None


def _head_tail_soft_grounded(quote_norm: str, body: str) -> bool:
    """Soft evidence only: head and tail appear (may be non-contiguous). Not used for snap."""
    if len(quote_norm) < 48:
        return False
    head, tail = quote_norm[:36], quote_norm[-36:]
    return head in body and tail in body


def quote_grounded_in_corpus(quote: str, corpus: str, *, min_len: int = _MIN_QUOTE_LEN) -> bool:
    """True when the quote maps to a contiguous corpus span, or soft head+tail evidence."""
    if resolve_quote_span_in_original(quote, corpus, min_len=min_len) is not None:
        return True
    raw = (quote or "").strip()
    if len(raw) < min_len:
        return False
    q = normalize_for_grounding(raw)
    body = normalize_for_grounding(corpus)
    return bool(body) and _head_tail_soft_grounded(q, body)


def snap_quote_to_corpus(
    quote: str,
    corpus: str,
    *,
    min_len: int = _MIN_QUOTE_LEN,
) -> Optional[str]:
    """
    Return the contiguous corpus substring that grounds ``quote``.

    Always returns text copied from ``corpus`` (OCR / retrieval bag), never the
    model paraphrase. None when no contiguous span covers enough of the quote.
    """
    span = resolve_quote_span_in_original(quote, corpus, min_len=min_len)
    if span is None:
        return None
    start, end = span
    snapped = (corpus or "")[start:end]
    return snapped.strip() or None


def canonicalize_extraction_quotes(
    result: TabularCellExtractionModel,
    original_text: str,
) -> TabularCellExtractionModel:
    """
    Replace model-emitted quotes with OCR-exact spans from ``original_text``.

    Updates ``verbatim_extract`` and each ``source_references[].text``. When a span
    resolves, also stamps ``char_start`` / ``char_end`` on that reference.
    """
    ot = original_text or ""
    if not ot or result is None:
        return result

    updates: Dict[str, Any] = {}
    snapped_primary: Optional[str] = None
    primary_span: Optional[Tuple[int, int]] = None

    ve = (result.verbatim_extract or "").strip()
    if ve:
        span = resolve_quote_span_in_original(ve, ot)
        if span is not None:
            snapped_primary = ot[span[0] : span[1]].strip()
            primary_span = span
            if snapped_primary:
                updates["verbatim_extract"] = snapped_primary[:500]

    refs_in = result.source_references if isinstance(result.source_references, list) else []
    new_refs: List[Dict[str, Any]] = []
    refs_changed = False
    for raw_ref in refs_in:
        if not isinstance(raw_ref, dict):
            continue
        ref = dict(raw_ref)
        text = str(ref.get("text") or "").strip()
        if not text:
            new_refs.append(ref)
            continue
        span = resolve_quote_span_in_original(text, ot)
        if span is None:
            # Keep the model text; do not steal another quote's OCR span.
            new_refs.append(ref)
            continue
        snapped = ot[span[0] : span[1]].strip()
        if not snapped:
            new_refs.append(ref)
            continue
        if ref.get("text") != snapped[:500]:
            refs_changed = True
        ref["text"] = snapped[:500]
        ref["char_start"] = int(span[0])
        ref["char_end"] = int(span[1])
        ref["verified"] = True
        new_refs.append(ref)
        if snapped_primary is None:
            snapped_primary = snapped
            primary_span = span

    if refs_changed or (new_refs and new_refs != refs_in):
        updates["source_references"] = new_refs

    if snapped_primary and not (result.verbatim_extract or "").strip():
        updates["verbatim_extract"] = snapped_primary[:500]

    if not updates:
        return result
    return result.model_copy(update=updates)


def _question_is_english(question: str) -> bool:
    letters = [c for c in (question or "") if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ("a" <= c.lower() <= "z"))
    return (latin / len(letters)) >= 0.7


class SupportingQuoteModel(BaseModel):
    found: bool = Field(
        description="true only if fragments contain a verbatim quote sufficient to answer",
    )
    supporting_quote: Optional[str] = Field(
        None,
        description="Verbatim quote copied from fragments (no paraphrase). null/empty if found=false",
    )
    reasoning: str = Field(description="Why this quote answers the question, or why none exists")

    class Config:
        extra = "ignore"


def _quote_locate_prompt(*, english: bool) -> ChatPromptTemplate:
    if english:
        system = (
            "You are a legal analyst. Find a verbatim quote in the document fragments "
            "that is sufficient to answer the deal-point question.\n"
            "Rules:\n"
            "- supporting_quote must be copied verbatim from the fragments — no paraphrase, "
            "no stitching distant spans\n"
            "- If fragments do not support an answer — found=false and supporting_quote empty\n"
            "- Do not output the cell value — only the quote or its absence\n"
            "- Quote must be self-contained for the next step (usually 1–3 sentences)\n"
            "- For Yes/No deal points, quote the clause that decides Yes vs No "
            "(including carveouts/exceptions when that is what the question asks)"
        )
        human = """Question: {question}

{navigation_block}
Document fragments:
{context}

Return found + supporting_quote + reasoning."""
    else:
        system = (
            "Ты юрист-аналитик. Найди во фрагментах документа дословную цитату, "
            "достаточную чтобы ответить на вопрос deal point.\n"
            "Правила:\n"
            "- supporting_quote только дословно из фрагментов, без перефразирования и без склейки разных мест\n"
            "- Если во фрагментах нет основания для ответа — found=false и supporting_quote пустой\n"
            "- Не отвечай на вопрос значением ячейки — только цитата или её отсутствие\n"
            "- Цитата должна быть самодостаточной для следующего шага (обычно 1–3 предложения)\n"
            "- Для вопросов Да/Нет цитируй норму, которая решает Да против Нет "
            "(включая carveout/исключение, если об этом вопрос)"
        )
        human = """Вопрос: {question}

{navigation_block}
Фрагменты документа:
{context}

Верни found + supporting_quote + reasoning."""
    return ChatPromptTemplate.from_messages([("system", system), ("human", human)])


def _value_from_quote_prompt(column: TabularColumn, *, english: bool) -> ChatPromptTemplate:
    from app.services.tabular_extraction_schemas import cell_value_field_description

    # Escape braces — field descriptions may contain JSON-like {…} that LangChain
    # would otherwise treat as template variables.
    value_contract = cell_value_field_description(column).replace("{", "{{").replace("}", "}}")
    if english:
        yes_no_extra = ""
        if column.column_type == "yes_no":
            yes_no_extra = (
                "\nFor yes_no: cell_value must be exactly «Да», «Нет», or N/A. "
                "Use only the quote; if the quote is insufficient for a decisive answer — N/A."
            )
        system = (
            "Extract the table cell value ONLY from the supporting quote.\n"
            f"Answer type: {column.column_type}\n"
            f"cell_value contract: {value_contract}{yes_no_extra}\n\n"
            "Rules:\n"
            "- The quote is the only source; no other context exists\n"
            "- verbatim_extract — the same quote (or its essential part)\n"
            "- source_references — one-element array {{text: quote}}\n"
            "- If the quote is insufficient for the type contract — cell_value = N/A\n"
            "- Do not invent facts absent from the quote\n"
            "- Prefer a short phrase taken from the quote over a long essay\n"
            "- Include confidence and brief reasoning"
        )
        human = """Question: {question}

Supporting quote (sole source):
{quote}

Extract cell_value for type {column_type}."""
    else:
        yes_no_extra = ""
        if column.column_type == "yes_no":
            yes_no_extra = (
                "\nДля yes_no: cell_value строго «Да», «Нет» или N/A. "
                "Опирайся только на цитату; если цитаты недостаточно — N/A."
            )
        system = (
            "Ты извлекаешь значение ячейки таблицы ТОЛЬКО из одной подтверждающей цитаты.\n"
            f"Тип ответа: {column.column_type}\n"
            f"Формат cell_value: {value_contract}{yes_no_extra}\n\n"
            "Правила:\n"
            "- Единственный источник — приведённая цитата; другого контекста нет\n"
            "- verbatim_extract — та же цитата (или её существенная часть)\n"
            "- source_references — массив с одним элементом {{text: цитата}}\n"
            "- Если цитаты недостаточно для ответа по контракту типа — cell_value = N/A\n"
            "- Не домысливай факты, которых нет в цитате\n"
            "- Предпочитай короткую фразу из цитаты длинному эссе\n"
            "- Укажи confidence и краткий reasoning"
        )
        human = """Вопрос: {question}

Подтверждающая цитата (единственный источник):
{quote}

Извлеки cell_value согласно типу {column_type}."""
    return ChatPromptTemplate.from_messages([("system", system), ("human", human)])


async def _ainvoke_structured(llm, prompt: ChatPromptTemplate, schema, payload: Dict[str, Any]) -> Any:
    try:
        structured_llm = llm.with_structured_output(schema, method="json_mode")
        chain = prompt | structured_llm
        return await chain.ainvoke(payload)
    except Exception as exc:
        logger.warning("Quote-then-answer structured call failed: %s", exc)
        chain = prompt | llm
        response = await chain.ainvoke(payload)
        response_text = response.content if hasattr(response, "content") else str(response)
        try:
            from app.services.langchain_agents.llm_helper import create_fixing_parser

            parser = create_fixing_parser(schema, llm, max_retries=2)
            return parser.parse(response_text)
        except Exception:
            raise


def _raw_to_dict(raw: Any) -> Dict[str, Any]:
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    if isinstance(raw, dict):
        return dict(raw)
    return raw.__dict__ if hasattr(raw, "__dict__") else {}


def _na_extraction(
    *,
    column: TabularColumn,
    reasoning: str,
) -> TabularCellExtractionModel:
    return typed_extraction_to_cell_model(
        {
            "cell_value": TABULAR_NA_VALUE,
            "reasoning": ensure_na_reasoning(reasoning),
            "confidence": 0.0,
            "extraction_method": "quote_then_answer",
            "verbatim_extract": None,
            "source_references": [],
        },
        column=column,
    )


async def locate_supporting_quote(
    llm,
    *,
    question: str,
    context_text: str,
    navigation_block: str = "",
) -> SupportingQuoteModel:
    english = _question_is_english(question)
    raw = await _ainvoke_structured(
        llm,
        _quote_locate_prompt(english=english),
        SupportingQuoteModel,
        {
            "question": question,
            "navigation_block": navigation_block,
            "context": context_text,
        },
    )
    data = _raw_to_dict(raw)
    found = bool(data.get("found"))
    quote = (data.get("supporting_quote") or "").strip() or None
    reasoning = str(data.get("reasoning") or "").strip() or "locate_quote"
    if not quote:
        found = False
    return SupportingQuoteModel(found=found, supporting_quote=quote, reasoning=reasoning)


async def derive_value_from_quote(
    llm,
    *,
    column: TabularColumn,
    question: str,
    quote: str,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    file: File,
) -> TabularCellExtractionModel:
    schema = extraction_schema_for_column(column)
    english = _question_is_english(question)
    prompt = _value_from_quote_prompt(column, english=english)
    raw = await _ainvoke_structured(
        llm,
        prompt,
        schema,
        {
            "question": question,
            "quote": quote,
            "column_type": column.column_type,
        },
    )
    result_dict = _raw_to_dict(raw)
    result_dict = normalize_fn(result_dict, column, file)
    result_dict["extraction_method"] = "quote_then_answer"
    result_dict["verbatim_extract"] = quote[:500]
    result_dict["source_references"] = [{"text": quote[:500]}]
    return typed_extraction_to_cell_model(result_dict, column=column)


async def invoke_quote_then_answer_extraction(
    llm,
    *,
    column: TabularColumn,
    context_text: str,
    normalize_fn: Callable[[Dict[str, Any], TabularColumn, File], Dict[str, Any]],
    file: File,
    navigation_context: str = "",
) -> Tuple[TabularCellExtractionModel, str]:
    """
    Full quote→answer path.

    Returns (extraction, status) where status is:
      - "ok" — grounded quote → value
      - "no_quote" — locate found nothing / ungrounded
      - "value_na" — quote ok but derived value is N/A
    """
    nav_block = ""
    if (navigation_context or "").strip():
        nav_block = (
            "Navigation context (where we looked; not a quote):\n"
            f"{navigation_context.strip()}\n"
            if _question_is_english(column.prompt)
            else (
                "Контекст навигации (куда смотрели; не цитата):\n"
                f"{navigation_context.strip()}\n"
            )
        )

    located = await locate_supporting_quote(
        llm,
        question=column.prompt,
        context_text=context_text,
        navigation_block=nav_block,
    )
    quote = (located.supporting_quote or "").strip()
    if not located.found or not quote:
        return (
            _na_extraction(
                column=column,
                reasoning=(
                    (located.reasoning or "").strip()
                    + " Нет подтверждающей цитаты во фрагментах — ответ «—»."
                ).strip(),
            ),
            "no_quote",
        )

    snapped = snap_quote_to_corpus(quote, context_text)
    if not snapped:
        logger.info(
            "Rejecting ungrounded supporting quote file=%s column=%s quote_len=%s",
            getattr(file, "id", None),
            getattr(column, "id", None),
            len(quote),
        )
        return (
            _na_extraction(
                column=column,
                reasoning=(
                    "Предложенная цитата не найдена дословно во фрагментах контекста — "
                    "ответ «—». "
                    + (located.reasoning or "")
                ).strip(),
            ),
            "no_quote",
        )

    # Prefer the file OCR form when available (retrieval bag may differ slightly).
    original = getattr(file, "original_text", None) or ""
    if original:
        ot_snap = snap_quote_to_corpus(snapped, original)
        if ot_snap:
            snapped = ot_snap

    extraction = await derive_value_from_quote(
        llm,
        column=column,
        question=column.prompt,
        quote=snapped[:500],
        normalize_fn=normalize_fn,
        file=file,
    )
    from app.services.tabular_extraction_policy import is_na_cell_value

    status = "value_na" if is_na_cell_value(extraction.cell_value) else "ok"
    return extraction, status


def tabular_quote_then_answer_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "TABULAR_QUOTE_THEN_ANSWER", True))
