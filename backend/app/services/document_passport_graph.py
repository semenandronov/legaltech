"""LangGraph pipeline for strict LLM-only document passport generation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


class PassportGraphState(TypedDict, total=False):
    text: str
    filename: str
    hint_doc_type: str
    context: str
    attempt: int
    max_attempts: int
    raw_response: str
    parsed: Dict[str, Any]
    summary: str
    key_points: List[str]
    doc_type: str
    errors: List[str]
    done: bool


ALLOWED_DOC_TYPES = {
    "возражение",
    "иск",
    "жалоба",
    "ходатайство",
    "договор",
    "акт",
    "претензия",
    "отзыв",
    "прочее",
    "other",
}


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        try:
            parsed = json.loads(text[first_brace : last_brace + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _extract_response_text(response: Any) -> str:
    """Best-effort text extraction from different LangChain/OpenAI message shapes."""
    if response is None:
        return ""

    # 1) Most common: AIMessage.content
    content = getattr(response, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    chunks.append(item.strip())
                continue
            if isinstance(item, dict):
                txt = item.get("text") or item.get("output_text") or item.get("content")
                if isinstance(txt, str) and txt.strip():
                    chunks.append(txt.strip())
        if chunks:
            return "\n".join(chunks).strip()

    # 2) Provider-specific payloads
    ak = getattr(response, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        for key in ("output_text", "text", "content"):
            val = ak.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, list):
                parts = [str(v).strip() for v in val if str(v).strip()]
                if parts:
                    return "\n".join(parts).strip()

    # 3) Last-resort text-like attributes
    for attr in ("text", "output_text"):
        val = getattr(response, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # 4) str(response)
    raw = str(response or "").strip()
    return raw


def _build_context(text: str, max_chars: int = 12000) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= max_chars:
        return compact
    head = compact[: max_chars // 2]
    tail = compact[-(max_chars // 2) :]
    return f"{head}\n...\n{tail}"


def _normalize_doc_type(doc_type: str, hint_doc_type: str) -> str:
    candidate = (doc_type or "").strip().lower()
    if candidate in ALLOWED_DOC_TYPES:
        return candidate
    hint = (hint_doc_type or "").strip().lower()
    return hint if hint else "прочее"


def _validate_fields(summary: str, key_points: List[str], doc_type: str) -> List[str]:
    errors: List[str] = []
    if not summary:
        errors.append("doc_summary_short is empty")
    elif len(summary) < 80:
        errors.append("doc_summary_short is too short")
    elif len(summary) > 900:
        errors.append("doc_summary_short exceeds 900 chars")

    if not key_points:
        errors.append("doc_key_points is empty")
    elif len(key_points) < 2:
        errors.append("doc_key_points has less than 2 items")

    if not doc_type:
        errors.append("doc_type is empty")

    return errors


def _prepare_context_node(state: PassportGraphState) -> PassportGraphState:
    return {
        "context": _build_context(state.get("text", "")),
        "attempt": state.get("attempt", 0),
        "errors": [],
        "done": False,
    }


def _generate_or_repair_node(state: PassportGraphState) -> PassportGraphState:
    filename = state.get("filename", "")
    hint_doc_type = state.get("hint_doc_type", "прочее")
    attempt = int(state.get("attempt", 0)) + 1
    context = state.get("context", "")
    prev_errors = state.get("errors", [])

    llm = create_legal_llm(
        temperature=0.0,
        use_rate_limiting=False,
        max_tokens=700,
        timeout=45.0,
        reasoning_mode="disabled",
    )

    system_prompt = (
        "Ты юридический ассистент по анализу документов. "
        "Верни только JSON-объект без пояснений. "
        "Строгая схема ответа:\n"
        "{\n"
        '  "doc_type": "возражение|иск|жалоба|ходатайство|договор|акт|претензия|отзыв|прочее|other",\n'
        '  "doc_summary_short": "2-4 предложения, 80-900 символов, нейтрально и по фактам",\n'
        '  "doc_key_points": ["ключевой тезис 1", "ключевой тезис 2"]\n'
        "}\n"
        "doc_type определи по содержанию документа; подсказка по имени файла может быть неточной. "
        "Запрещено: markdown, пояснения, комментарии, поля вне схемы."
    )
    if attempt == 1:
        human_prompt = (
            f"Имя файла: {filename}\n"
            f"Подсказка по имени файла (может быть неточной): {hint_doc_type}\n"
            "Текст документа:\n"
            f"{context}\n\n"
            "Сформируй JSON строго по схеме."
        )
    else:
        human_prompt = (
            f"Имя файла: {filename}\n"
            f"Подсказка по имени файла (может быть неточной): {hint_doc_type}\n"
            "Текст документа:\n"
            f"{context}\n\n"
            "Прошлый ответ не прошел валидацию. Исправь JSON.\n"
            f"Ошибки валидации: {', '.join(prev_errors) if prev_errors else 'unknown'}\n"
            "Верни только исправленный JSON."
        )

    response = llm.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )
    raw = _extract_response_text(response)
    parsed = _extract_json_object(str(raw))

    points_raw = parsed.get("doc_key_points")
    points: List[str] = []
    if isinstance(points_raw, list):
        for item in points_raw:
            point = str(item or "").strip()
            if point:
                points.append(point[:220])
            if len(points) >= 8:
                break

    summary = str(parsed.get("doc_summary_short") or "").strip()[:900]
    doc_type = _normalize_doc_type(str(parsed.get("doc_type") or ""), hint_doc_type)

    return {
        "attempt": attempt,
        "raw_response": str(raw),
        "parsed": parsed,
        "summary": summary,
        "key_points": points,
        "doc_type": doc_type,
    }


def _validate_node(state: PassportGraphState) -> PassportGraphState:
    summary = state.get("summary", "")
    key_points = state.get("key_points", [])
    doc_type = state.get("doc_type", "")
    errors = _validate_fields(summary, key_points, doc_type)

    if errors:
        logger.warning(
            "Passport validation failed for %s attempt=%s errors=%s raw_preview=%s",
            state.get("filename", ""),
            state.get("attempt", 0),
            errors,
            (state.get("raw_response", "") or "")[:500],
        )
        return {"errors": errors, "done": False}
    return {"errors": [], "done": True}


def _route_after_validate(state: PassportGraphState) -> Literal["finish", "retry", "fail"]:
    if state.get("done"):
        return "finish"
    if int(state.get("attempt", 0)) < int(state.get("max_attempts", 3)):
        return "retry"
    return "fail"


def _build_graph():
    graph = StateGraph(PassportGraphState)
    graph.add_node("prepare_context", _prepare_context_node)
    graph.add_node("generate_or_repair", _generate_or_repair_node)
    graph.add_node("validate", _validate_node)

    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "generate_or_repair")
    graph.add_edge("generate_or_repair", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "finish": END,
            "retry": "generate_or_repair",
            "fail": END,
        },
    )
    return graph.compile()


_PASSPORT_GRAPH = _build_graph()


def generate_document_passport(
    *,
    text: str,
    filename: str,
    hint_doc_type: str,
    max_attempts: int = 3,
) -> tuple[str, List[str], str, str]:
    """Generate strict LLM-only document passport using LangGraph pipeline."""
    initial: PassportGraphState = {
        "text": text,
        "filename": filename,
        "hint_doc_type": hint_doc_type,
        "attempt": 0,
        "max_attempts": max_attempts,
    }
    result = _PASSPORT_GRAPH.invoke(initial)
    summary = str(result.get("summary") or "").strip()
    key_points = result.get("key_points") or []
    doc_type = str(result.get("doc_type") or "").strip()
    if summary and key_points and doc_type:
        return summary, key_points, doc_type, "v3_langgraph_llm"

    errors = result.get("errors") or ["unknown validation error"]
    raw_preview = str(result.get("raw_response") or "")[:500]
    raise ValueError(
        f"LLM passport for {filename} failed after {result.get('attempt', 0)} attempts: "
        f"{'; '.join(errors)}; raw_preview={raw_preview}"
    )

