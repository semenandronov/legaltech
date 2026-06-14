"""Уникальные вопросы шаблона → ответы LLM → подстановка во все вхождения."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.services.draft_template_schemas import TemplateFieldSpec

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    "creditor": "кредитора",
    "debtor": "должника",
    "court": "суда",
}


def _bulk_context_char_limit() -> int:
    return max(4000, int(getattr(config, "DRAFT_BULK_CONTEXT_MAX_CHARS", 7000) or 7000))


def _questions_chunk_size() -> int:
    return max(8, int(getattr(config, "DRAFT_BULK_UNIFIED_MAX_FIELDS_PER_CALL", 48) or 48))


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _context_hint(context_snippet: str) -> str:
    """Краткая подсказка из окружения плейсхолдера для различения одинаковых маркеров."""
    low = (context_snippet or "").lower()
    hints: List[str] = []
    if any(x in low for x in ("регистрац", "огрн", "егрюл")):
        hints.append("регистрация")
    if any(x in low for x in ("составлен", "подписан", "подпись")):
        hints.append("дата составления")
    if any(x in low for x in ("договор", "контракт")):
        hints.append("договор")
    if any(x in low for x in ("неусто", "пени", "процент")):
        hints.append("неустойка")
    if any(x in low for x in ("госпошлин", "пошлин")):
        hints.append("госпошлина")
    if any(x in low for x in ("задолжен", "долг", "сумм", "руб")):
        hints.append("сумма требования")
    if any(x in low for x in ("просительн", "требован")):
        hints.append("просительная часть")
    return ", ".join(hints[:2])


def build_fill_question(spec: TemplateFieldSpec) -> str:
    """Человекочитаемый вопрос для LLM (один на смысл, не на вхождение)."""
    explicit = _normalize_whitespace(spec.fill_question)
    if explicit:
        return explicit

    what = _normalize_whitespace(spec.what_to_find)
    if what and not what.lower().startswith("найти в материалах дела значение для поля"):
        if what.endswith("?"):
            return what
        return f"{what}?"

    inner = spec.marker.strip("[]").strip() or "поле"
    role_label = _ROLE_LABELS.get(spec.entity_role or "", "")
    hint = _context_hint(spec.context_snippet)

    if role_label:
        base = f"Какое значение «{inner}» {role_label}"
    else:
        base = f"Какое значение «{inner}»"
    if hint:
        base += f" ({hint})"
    return base + "?"


def question_key_for_fill_question(fill_question: str) -> str:
    """Стабильный ключ: одинаковый вопрос → один ключ во всех шаблонах."""
    norm = _normalize_whitespace(fill_question).lower()
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
    return f"q_{digest}"


def resolve_question_key(spec: TemplateFieldSpec) -> str:
    key = (spec.question_key or "").strip()
    if key:
        return key
    return question_key_for_fill_question(build_fill_question(spec))


@dataclass(frozen=True)
class TemplateFillQuestion:
    """Уникальный вопрос для заполнения шаблона."""

    question_key: str
    fill_question: str
    marker: str
    field_ids: Tuple[str, ...]
    occurrence_count: int


def build_unique_fill_questions(field_specs: List[TemplateFieldSpec]) -> List[TemplateFillQuestion]:
    """Сгруппировать вхождения полей по уникальному вопросу."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for spec in field_specs:
        fq = build_fill_question(spec)
        qk = resolve_question_key(spec)
        if qk not in buckets:
            buckets[qk] = {
                "fill_question": fq,
                "marker": spec.marker,
                "field_ids": [],
            }
        buckets[qk]["field_ids"].append(spec.field_id)

    out: List[TemplateFillQuestion] = []
    for qk, data in buckets.items():
        fids = tuple(data["field_ids"])
        out.append(
            TemplateFillQuestion(
                question_key=qk,
                fill_question=str(data["fill_question"]),
                marker=str(data["marker"]),
                field_ids=fids,
                occurrence_count=len(fids),
            )
        )
    out.sort(key=lambda q: q.question_key)
    return out


def propagate_answers_to_fields(
    field_specs: List[TemplateFieldSpec],
    answers_by_key: Dict[str, Optional[str]],
    confidences_by_key: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, Optional[str]], Dict[str, float]]:
    """Размножить ответы на все field_id с тем же question_key."""
    confidences_by_key = confidences_by_key or {}
    values: Dict[str, Optional[str]] = {s.field_id: None for s in field_specs}
    confidences: Dict[str, float] = {s.field_id: 0.0 for s in field_specs}

    key_to_value: Dict[str, Optional[str]] = {}
    key_to_conf: Dict[str, float] = {}
    for spec in field_specs:
        qk = resolve_question_key(spec)
        if qk not in key_to_value:
            key_to_value[qk] = answers_by_key.get(qk)
            key_to_conf[qk] = float(confidences_by_key.get(qk) or 0.0)

    for spec in field_specs:
        qk = resolve_question_key(spec)
        values[spec.field_id] = key_to_value.get(qk)
        confidences[spec.field_id] = key_to_conf.get(qk, 0.0)
    return values, confidences


def _parse_extract_json(raw: str) -> Dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    t = str(raw).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t, flags=re.IGNORECASE)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}\s*$", t)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def _normalize_answer(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "н/д", "n/a"):
        return None
    return s


def _parse_question_answers_payload(
    raw: str,
    questions: List[TemplateFillQuestion],
) -> Dict[str, Tuple[Optional[str], float]]:
    obj = _parse_extract_json(raw)
    allowed = {q.question_key for q in questions}
    by_key: Dict[str, Tuple[Optional[str], float]] = {}

    nested = obj.get("answers")
    if isinstance(nested, dict):
        for qk, entry in nested.items():
            if qk not in allowed:
                continue
            if isinstance(entry, dict):
                val = _normalize_answer(entry.get("value"))
                conf = float(entry.get("confidence") or 0.0)
            else:
                val = _normalize_answer(entry)
                conf = 0.5 if val else 0.0
            by_key[qk] = (val, conf)

    for qk in allowed:
        if qk in by_key:
            continue
        if qk in obj and not isinstance(obj[qk], dict):
            val = _normalize_answer(obj[qk])
            by_key[qk] = (val, 0.5 if val else 0.0)

    for q in questions:
        by_key.setdefault(q.question_key, (None, 0.0))
    return by_key


def extract_fill_question_answers(
    questions: List[TemplateFillQuestion],
    shared_rag_context: str,
    *,
    user_context: str = "",
    llm=None,
) -> Tuple[Dict[str, Optional[str]], Dict[str, float]]:
    """
    LLM отвечает на уникальные вопросы (не на каждое вхождение плейсхолдера).

    Returns:
        (answers_by_question_key, confidence_by_question_key)
    """
    answers: Dict[str, Optional[str]] = {q.question_key: None for q in questions}
    confidences: Dict[str, float] = {q.question_key: 0.0 for q in questions}
    if not questions:
        return answers, confidences

    ctx = (shared_rag_context or "").strip()
    user = (user_context or "").strip()
    if not ctx and not user:
        return answers, confidences

    if llm is None:
        try:
            from app.services.llm_factory import create_legal_llm

            llm = create_legal_llm(provider="yandex", use_rate_limiting=False)
        except Exception as e:
            logger.warning("[draft_template_questions] LLM unavailable: %s", e)
            return answers, confidences

    from langchain_core.messages import HumanMessage

    chunk_n = _questions_chunk_size()
    for i in range(0, len(questions), chunk_n):
        chunk = questions[i : i + chunk_n]
        lines = [
            f'- key="{q.question_key}" | вопрос: {q.fill_question}'
            for q in chunk
        ]
        prompt = (
            "Ответь на вопросы для заполнения юридического шаблона.\n"
            "Источники (в порядке приоритета): сначала ЗАПРОС ЮРИСТА, затем ФРАГМЕНТЫ ИЗ ДЕЛА.\n"
            "Ответь ТОЛЬКО JSON:\n"
            '{"answers": {"<question_key>": {"value": "строка" или null, "confidence": 0.0-1.0}, ...}}\n'
            "null — если нет однозначного ответа ни в запросе, ни в материалах. Не выдумывай.\n\n"
        )
        if user:
            prompt += f"ЗАПРОС ЮРИСТА:\n{user[:3000]}\n\n"
        prompt += "ВОПРОСЫ:\n" + "\n".join(lines) + "\n\n"
        if ctx:
            prompt += f"ФРАГМЕНТЫ ИЗ ДЕЛА:\n{ctx[:_bulk_context_char_limit()]}\n"
        else:
            prompt += "ФРАГМЕНТЫ ИЗ ДЕЛА: (нет — опирайся только на запрос юриста, где это допустимо)\n"

        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(raw, list):
                raw = "".join(str(x) for x in raw)
            parsed = _parse_question_answers_payload(str(raw), chunk)
            for qk, (val, conf) in parsed.items():
                answers[qk] = val
                confidences[qk] = conf
        except Exception as e:
            logger.warning("[draft_template_questions] extract chunk failed: %s", e)

    return answers, confidences


_EXTRACTION_SYSTEM_PROMPT = (
    "Ты извлекаешь данные для заполнения юридического шаблона банкротства.\n"
    "Источники (в порядке приоритета): сначала ЗАПРОС ЮРИСТА, затем ФРАГМЕНТЫ ИЗ ДЕЛА.\n"
    "Если в запросе есть блок КАЛЬКУЛЯТОР — суммы debt_*, state_duty бери ТОЛЬКО оттуда (цифры без пробелов).\n"
    "Не выдумывай. Если данных нет — оставь поле пустой строкой.\n"
    "Суммы — только цифрами без пробелов. Даты — ДД.ММ.ГГГГ.\n"
    "manager_fio: пустая строка, если в деле указано только СРО."
)


def _is_variable_keyed_questions(questions: List[TemplateFillQuestion]) -> bool:
    if not questions:
        return False
    for q in questions:
        key = (q.question_key or "").strip()
        if not key or key.startswith("q_"):
            return False
    return True


def extract_variable_answers(
    questions: List[TemplateFillQuestion],
    shared_rag_context: str,
    *,
    user_context: str = "",
    llm=None,
) -> Tuple[Dict[str, Optional[str]], Dict[str, float]]:
    """
    Structured output: ключ = имя переменной docxtpl.
    Fallback на extract_fill_question_answers при ошибке.
    """
    variable_keys = [q.question_key for q in questions if q.question_key]
    if not variable_keys:
        return {}, {}

    ctx = (shared_rag_context or "").strip()
    user = (user_context or "").strip()
    if not ctx and not user:
        return {q.question_key: None for q in questions}, {q.question_key: 0.0 for q in questions}

    if llm is None:
        try:
            from app.services.llm_factory import create_legal_llm

            llm = create_legal_llm(provider="yandex", use_rate_limiting=False)
        except Exception as e:
            logger.warning("[draft_template_questions] LLM unavailable: %s", e)
            return extract_fill_question_answers(questions, shared_rag_context, user_context=user_context, llm=llm)

    from app.services.bankruptcy_field_catalog import build_extraction_model
    from langchain_core.messages import HumanMessage, SystemMessage

    ExtractModel = build_extraction_model(variable_keys)
    answers: Dict[str, Optional[str]] = {q.question_key: None for q in questions}
    confidences: Dict[str, float] = {q.question_key: 0.0 for q in questions}

    human_parts = []
    if user:
        human_parts.append(f"ЗАПРОС ЮРИСТА:\n{user[:3000]}")
    if ctx:
        human_parts.append(f"ФРАГМЕНТЫ ИЗ ДЕЛА:\n{ctx[:_bulk_context_char_limit()]}")
    else:
        human_parts.append("ФРАГМЕНТЫ ИЗ ДЕЛА: (нет — опирайся только на запрос юриста, где допустимо)")
    human_msg = "\n\n".join(human_parts)

    try:
        if hasattr(llm, "with_structured_output"):
            structured = llm.with_structured_output(ExtractModel, method="json_schema")
            result = structured.invoke(
                [
                    SystemMessage(content=_EXTRACTION_SYSTEM_PROMPT),
                    HumanMessage(content=human_msg),
                ]
            )
            payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            for key in variable_keys:
                val = _normalize_answer(payload.get(key))
                answers[key] = val
                confidences[key] = 0.85 if val else 0.0
            return answers, confidences
    except Exception as e:
        logger.warning("[draft_template_questions] structured extract failed: %s", e)

    return extract_fill_question_answers(questions, shared_rag_context, user_context=user_context, llm=llm)


def questions_needing_retry(
    questions: List[TemplateFillQuestion],
    answers: Dict[str, Optional[str]],
    confidences: Dict[str, float],
    *,
    max_questions: Optional[int] = None,
) -> List[TemplateFillQuestion]:
    """Вопросы без ответа или с низкой уверенностью."""
    min_conf = float(getattr(config, "DRAFT_BULK_MIN_CONFIDENCE", 0.25) or 0.25)
    cap = max_questions
    if cap is None:
        cap = int(getattr(config, "DRAFT_BULK_RETRY_MAX_FIELDS", 4) or 4)
    cap = max(0, cap)
    out: List[TemplateFillQuestion] = []
    for q in questions:
        val = answers.get(q.question_key)
        conf = float(confidences.get(q.question_key) or 0.0)
        if not val or not str(val).strip():
            out.append(q)
        elif conf < min_conf:
            out.append(q)
        if len(out) >= cap:
            break
    return out


_GENERIC_QUESTION_MARKERS = (
    "найти в материалах",
    "значение для поля",
    "укажите значение",
    "заполните поле",
)


def sanitize_fill_question(candidate: str, spec: TemplateFieldSpec) -> str:
    """
    Проверить вопрос от LLM; при слабом/пустом ответе — надёжная эвристика из контекста.
    """
    q = _normalize_whitespace(candidate)
    low = q.lower()
    if len(q) < 12 or not q.endswith("?"):
        return build_fill_question(spec.model_copy(update={"fill_question": ""}))
    if any(m in low for m in _GENERIC_QUESTION_MARKERS):
        return build_fill_question(spec.model_copy(update={"fill_question": ""}))
    if q.count("?") > 1:
        q = q.split("?")[0].strip() + "?"
    return q


def _semantic_group_key(spec: TemplateFieldSpec) -> str:
    """Ключ смысловой группы: marker + роль + контекст (различает две «даты»)."""
    hint = _context_hint(spec.context_snippet)
    return f"{spec.marker}|{spec.entity_role or ''}|{hint}"


def unify_semantic_duplicate_questions(specs: List[TemplateFieldSpec]) -> List[TemplateFieldSpec]:
    """
    Одинаковый marker+роль+контекст → один канонический вопрос (самый конкретный).
    """
    best_by_group: Dict[str, TemplateFieldSpec] = {}
    for spec in specs:
        gk = _semantic_group_key(spec)
        prev = best_by_group.get(gk)
        if prev is None:
            best_by_group[gk] = spec
            continue
        cur_q = sanitize_fill_question(spec.fill_question or build_fill_question(spec), spec)
        prev_q = sanitize_fill_question(prev.fill_question or build_fill_question(prev), prev)
        if len(cur_q) >= len(prev_q):
            best_by_group[gk] = spec

    canonical: Dict[str, str] = {}
    for gk, rep in best_by_group.items():
        canonical[gk] = sanitize_fill_question(rep.fill_question or build_fill_question(rep), rep)

    return [
        s.model_copy(update={"fill_question": canonical[_semantic_group_key(s)]})
        for s in specs
    ]


@dataclass(frozen=True)
class TemplateQuestionAudit:
    template_key: str
    template_title: str
    occurrences: int
    unique_questions: int
    questions: Tuple[str, ...]
    warnings: Tuple[str, ...]


def audit_template_questions(
    *,
    template_key: str,
    template_title: str,
    specs: List[TemplateFieldSpec],
) -> TemplateQuestionAudit:
    """Проверка качества вопросов после индексации."""
    unique = build_unique_fill_questions(specs)
    warnings: List[str] = []
    questions = [q.fill_question for q in unique]

    for q in unique:
        if len(q.fill_question) < 15:
            warnings.append(f"короткий вопрос: {q.fill_question}")
        if q.occurrence_count > 1:
            logger.debug(
                "[audit] %s ×%s: %s",
                q.marker,
                q.occurrence_count,
                q.fill_question,
            )

    by_marker: Dict[str, set[str]] = {}
    for spec in specs:
        by_marker.setdefault(spec.marker, set()).add(spec.fill_question)
    for marker, qs in by_marker.items():
        if len(qs) > 1:
            warnings.append(
                f"маркер {marker} имеет {len(qs)} разных вопросов — проверьте контекст"
            )

    return TemplateQuestionAudit(
        template_key=template_key,
        template_title=template_title,
        occurrences=len(specs),
        unique_questions=len(unique),
        questions=tuple(questions),
        warnings=tuple(warnings),
    )


def assign_question_metadata(
    specs: List[TemplateFieldSpec],
) -> Tuple[List[TemplateFieldSpec], List[TemplateFillQuestion]]:
    """
    Заполнить fill_question и question_key на каждом поле; вернуть specs и уникальные вопросы.
    Для docxtpl: question_key = variable (имя переменной).
    """
    staged: List[TemplateFieldSpec] = []
    for spec in specs:
        fq = (spec.fill_question or "").strip() or build_fill_question(spec)
        staged.append(spec.model_copy(update={"fill_question": fq}))

    key_by_normalized: Dict[str, str] = {}
    updated: List[TemplateFieldSpec] = []
    for spec in staged:
        var = (spec.variable or "").strip()
        if var:
            qk = var
        else:
            norm = _normalize_whitespace(spec.fill_question).lower()
            if norm not in key_by_normalized:
                key_by_normalized[norm] = question_key_for_fill_question(spec.fill_question)
            qk = key_by_normalized[norm]
        updated.append(spec.model_copy(update={"question_key": qk}))
    return updated, build_unique_fill_questions(updated)
