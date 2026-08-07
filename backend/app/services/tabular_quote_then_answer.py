"""
Quote-then-answer extraction for tabular cells.

Architecture (not a special-case hack):
1) Locate a supporting verbatim quote in the retrieved fragments.
2) Snap/accept the quote only if it is grounded in those fragments.
3) Derive cell_value from the quote alone — the model cannot invent from the rest of the bag.

If no grounded quote exists → «—» (caller may fall back to single-pass + evidence gate).
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, Optional, Tuple

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


def normalize_for_grounding(text: str) -> str:
    t = (text or "").replace("\u00a0", " ")
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", " ", t.strip()).lower()
    return t


def _question_is_english(question: str) -> bool:
    letters = [c for c in (question or "") if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ("a" <= c.lower() <= "z"))
    return (latin / len(letters)) >= 0.7


def quote_grounded_in_corpus(quote: str, corpus: str, *, min_len: int = _MIN_QUOTE_LEN) -> bool:
    """True when the quote (normalized) appears in the corpus, with light truncation tolerance."""
    return snap_quote_to_corpus(quote, corpus, min_len=min_len) is not None


def snap_quote_to_corpus(
    quote: str,
    corpus: str,
    *,
    min_len: int = _MIN_QUOTE_LEN,
) -> Optional[str]:
    """
    Return a corpus-grounded span for the proposed quote.

    Exact normalized containment first; otherwise the longest near-match
    (≥75% of quote length, ≥ min_len) via SequenceMatcher.
    """
    raw = (quote or "").strip()
    if len(raw) < min_len:
        return None
    q = normalize_for_grounding(raw)
    body = normalize_for_grounding(corpus)
    if not body or len(q) < min_len:
        return None
    if q in body:
        return raw

    if len(q) >= 48:
        head, tail = q[:36], q[-36:]
        if head in body and tail in body:
            return raw

    matcher = SequenceMatcher(None, q, body, autojunk=False)
    match = matcher.find_longest_match(0, len(q), 0, len(body))
    need = max(min_len, int(0.75 * len(q)))
    if match.size < need:
        return None
    # Reconstruct a readable span from the original corpus around the match.
    # Approximate by scanning raw corpus windows with the same normalized length.
    target = body[match.b : match.b + match.size]
    # Prefer returning the model quote when head/tail already proved presence;
    # otherwise return the matched normalized span (stable for phase-2).
    return target


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
