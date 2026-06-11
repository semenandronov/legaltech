"""
User-facing activity for the in-case assistant (SSE).

Natural, context-dependent progress lines — like a colleague thinking aloud.
Built from case facts (document names, scope), not pipeline jargon.
Variations are deterministic per request (stable within one turn).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

ActivityStatus = Literal["pending", "running", "completed", "error"]

_DEFAULT_TOTAL = 4

# Nodes that must never surface in lawyer-facing UI (observability only).
_HIDDEN_GRAPH_NODES = frozenset(
    {
        "mode_router",
        "sync_execution_tier",
        "parallel_retrieval",
        "merge_retrieval_results",
        "grade_retrieval",
        "rewrite_search_query",
        "rag_quality_gate",
    }
)


@dataclass(frozen=True)
class AssistantActivityStep:
    step_id: str
    phase: str
    step: int
    total_steps: int
    label: str
    detail: Optional[str] = None
    status: ActivityStatus = "running"
    content: str = ""

    def to_payload(self) -> Dict[str, Any]:
        body = (self.content or "").strip() or self._compose_content()
        return {
            "type": "assistant_activity",
            "step_id": self.step_id,
            "phase": self.phase,
            "step": self.step,
            "totalSteps": self.total_steps,
            "label": self.label or body,
            "detail": self.detail,
            "content": body,
            "status": self.status,
        }

    def _compose_content(self) -> str:
        if self.detail:
            return f"{self.label}: {self.detail}" if self.label else self.detail
        return self.label


def _short(text: str, limit: int = 72) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _pick_variant(variants: Sequence[str], seed: str) -> str:
    items = [v for v in variants if v and v.strip()]
    if not items:
        return ""
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return items[int(digest, 16) % len(items)]


def _question_profile(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"\b(о чем|о чём|обзор|кратко|суть|содержан|в целом|какие документ)\b", q):
        return "overview"
    if re.search(r"\b(когда|дата|срок|до какого|со скольки)\b", q):
        return "dates"
    if re.search(r"\b(сколько|сумм|размер|стоимост|цена)\b", q):
        return "amount"
    if re.search(r"\b(кто|сторон|истец|ответчик|заказчик|исполнител|арендодател)\b", q):
        return "parties"
    if re.search(r"\b(наруш|риск|спор|противореч|несоответ)\b", q):
        return "risk"
    return "general"


def _file_names_from_docs(docs: Any, *, limit: int = 6) -> List[str]:
    if not isinstance(docs, list):
        return []
    names: List[str] = []
    seen: set[str] = set()
    for item in docs:
        meta: Dict[str, Any] = {}
        if isinstance(item, dict):
            raw_meta = item.get("metadata")
            if isinstance(raw_meta, dict):
                meta = raw_meta
        elif hasattr(item, "metadata"):
            raw_meta = getattr(item, "metadata", None)
            if isinstance(raw_meta, dict):
                meta = raw_meta
        fn = str(
            meta.get("source_file")
            or meta.get("filename")
            or meta.get("file_name")
            or ""
        ).strip()
        if not fn or fn in seen:
            continue
        seen.add(fn)
        names.append(_short(fn, 56))
        if len(names) >= limit:
            break
    return names


def _names_phrase(names: List[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return f"«{names[0]}»"
    if len(names) == 2:
        return f"«{names[0]}» и «{names[1]}»"
    return f"«{names[0]}», «{names[1]}» и ещё {len(names) - 2}"


def _docs_count_phrase(n: int) -> str:
    n = max(0, int(n))
    if n == 0:
        return ""
    if n == 1:
        return "один документ"
    if 2 <= n <= 4:
        return f"{n} документа"
    return f"{n} документов"


def _narrative_step(
    *,
    step_id: str,
    phase: str,
    step: int,
    content: str,
    status: ActivityStatus = "running",
    total_steps: int = _DEFAULT_TOTAL,
) -> AssistantActivityStep:
    text = (content or "").strip()
    return AssistantActivityStep(
        step_id=step_id,
        phase=phase,
        step=step,
        total_steps=total_steps,
        label=text,
        content=text,
        status=status,
    )


def publish_activity_step(step: AssistantActivityStep) -> None:
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(step.to_payload())
    except Exception:
        return


def mark_step_completed(step: AssistantActivityStep) -> AssistantActivityStep:
    return AssistantActivityStep(
        step_id=step.step_id,
        phase=step.phase,
        step=step.step,
        total_steps=step.total_steps,
        label=step.label,
        detail=step.detail,
        status="completed",
        content=step.content,
    )


# ── Early HTTP / orchestrator ───────────────────────────────────────────────


def build_request_accepted_activity(*, question: str) -> AssistantActivityStep:
    seed = f"accepted|{question}"
    variants = [
        "Принял вопрос, начинаю разбираться",
        "Хорошо, сейчас посмотрю по материалам дела",
        "Понял, перехожу к материалам дела",
    ]
    return _narrative_step(
        step_id="accepted",
        phase="accepted",
        step=1,
        content=_pick_variant(variants, seed),
        status="running",
    )


def build_analyzing_request_activity(*, question: str = "") -> AssistantActivityStep:
    profile = _question_profile(question)
    seed = f"analyze|{profile}|{question}"
    by_profile = {
        "overview": [
            "Нужен общий обзор — сначала пойму, какие документы в деле",
            "Смотрю, из чего состоит досье и что в нём главное",
            "Хочу сложить картину по всем материалам сразу",
        ],
        "dates": [
            "Ищу даты и сроки в документах",
            "Проверю, где в деле зафиксированы нужные даты",
            "Сфокусируюсь на хронологии и сроках",
        ],
        "amount": [
            "Нужны цифры и суммы — посмотрю соответствующие места в документах",
            "Ищу финансовые условия и расчёты в материалах",
            "Проверю, где в деле указаны суммы и порядок оплаты",
        ],
        "parties": [
            "Выясню, кто фигурирует в документах и как обозначены стороны",
            "Посмотрю реквизиты и роли участников в материалах",
            "Найду в деле сведения о сторонах и их обязанностях",
        ],
        "risk": [
            "Проверю материалы на спорные и рискованные места",
            "Сопоставлю формулировки — ищу возможные противоречия",
            "Внимательно пройду документы с точки зрения рисков",
        ],
        "general": [
            "Уточняю, что именно искать в материалах дела",
            "Сначала пойму, к каким документам обратиться",
            "Разбираюсь, где в деле может лежать ответ",
        ],
    }
    content = _pick_variant(by_profile.get(profile, by_profile["general"]), seed)
    return _narrative_step(
        step_id="analyze",
        phase="preparing",
        step=1,
        content=content,
        status="running",
    )


def build_preparing_session_activity(*, question: str = "") -> AssistantActivityStep:
    seed = f"prepare|{question}"
    variants = [
        "Подключаюсь к материалам этого дела",
        "Открываю контекст дела и историю переписки",
        "Сверяюсь с тем, что уже обсуждали в этом чате",
    ]
    return _narrative_step(
        step_id="prepare",
        phase="preparing",
        step=1,
        content=_pick_variant(variants, seed),
        status="running",
    )


def build_stream_started_activity(*, question: str) -> AssistantActivityStep:
    return build_analyzing_request_activity(question=question)


def build_scope_running_activity(*, question: str) -> AssistantActivityStep:
    return _narrative_review_running(question=question, file_count=0, file_names=[])


def build_search_case_running_activity(
    *,
    question: str,
    scope_mode: Optional[str] = None,
    file_count: int = 0,
) -> AssistantActivityStep:
    _ = scope_mode
    return _narrative_review_running(
        question=question,
        file_count=file_count,
        file_names=[],
    )


def build_refine_running_activity(*, recall_docs: int = 0) -> AssistantActivityStep:
    _ = recall_docs
    seed = "refine|running"
    variants = [
        "Сверяю найденное — оставляю только то, что относится к вопросу",
        "Просматриваю выдержки и отбираю главное для ответа",
        "Уточняю, какие фрагменты действительно важны",
    ]
    return _narrative_step(
        step_id="review",
        phase="retrieval",
        step=2,
        content=_pick_variant(variants, seed),
        status="running",
    )


# ── Fast path ───────────────────────────────────────────────────────────────


def build_fast_path_scope_activity(
    *,
    question: str,
    attached_count: int = 0,
    route: str = "fast_path",
) -> AssistantActivityStep:
    _ = route
    return _narrative_review_running(
        question=question,
        file_count=attached_count,
        file_names=[],
    )


def build_fast_path_recall_completed(
    *,
    question: str,
    retrieved_chunks: int,
    docs_used: int,
) -> AssistantActivityStep:
    _ = retrieved_chunks
    return _narrative_review_completed(
        question=question,
        file_names=[],
        docs_used=docs_used,
    )


def build_fast_path_synthesis_activity(*, overview: bool = False) -> AssistantActivityStep:
    return _narrative_answer_running(overview=overview, question="")


# ── Graph node mapping ──────────────────────────────────────────────────────


def build_graph_node_activity(
    node_name: str,
    node_data: Dict[str, Any],
    *,
    question: str = "",
) -> Optional[AssistantActivityStep]:
    name = str(node_name or "").strip()
    if not name or not isinstance(node_data, dict):
        return None
    if name in _HIDDEN_GRAPH_NODES:
        return None

    builders = {
        "extract_retrieval_task": _activity_scope_done,
        "rag_retrieval": _activity_review_done,
        "rerank_context": _activity_refine_done,
        "garant_retrieval": _activity_legal_done,
        "court_practice_retrieval": _activity_court_done,
        "clarify_response": _activity_clarify,
        "generate_response": _activity_answer_done,
        "generate_draft_plan": _activity_draft_plan,
    }
    builder = builders.get(name)
    if builder is None:
        return None
    return builder(node_data, question=question)


def _retrieval_task(node_data: Dict[str, Any]) -> Dict[str, Any]:
    raw = node_data.get("retrieval_task")
    return raw if isinstance(raw, dict) else {}


def _narrative_review_running(
    *,
    question: str,
    file_count: int,
    file_names: List[str],
) -> AssistantActivityStep:
    profile = _question_profile(question)
    seed = f"review_run|{profile}|{file_count}|{'|'.join(file_names)}|{question}"
    names = _names_phrase(file_names)
    count_phrase = _docs_count_phrase(file_count)

    if names:
        templates = [
            f"Читаю {names}",
            f"Просматриваю {names} — ищу ответ на ваш вопрос",
            f"Смотрю {names} в контексте дела",
        ]
    elif count_phrase:
        templates = [
            f"Просматриваю {count_phrase} в материалах дела",
            f"Открываю {count_phrase} — нужно найти релевантные места",
            f"Иду по {count_phrase} в деле",
        ]
    elif profile == "overview":
        templates = [
            "Просматриваю документы дела — хочу понять общую картину",
            "Смотрю, из каких документов состоит дело и о чём каждый",
            "Читаю материалы, чтобы сложить целостное представление",
        ]
    else:
        templates = [
            "Ищу в материалах дела то, что относится к вашему вопросу",
            "Просматриваю документы — ищу нужные формулировки и факты",
            "Смотрю дело и отмечаю места, которые могут ответить на вопрос",
        ]

    return _narrative_step(
        step_id="review",
        phase="retrieval",
        step=2,
        content=_pick_variant(templates, seed),
        status="running",
    )


def _narrative_review_completed(
    *,
    question: str,
    file_names: List[str],
    docs_used: int = 0,
) -> AssistantActivityStep:
    profile = _question_profile(question)
    seed = f"review_done|{profile}|{'|'.join(file_names)}|{docs_used}|{question}"
    names = _names_phrase(file_names)
    n = len(file_names) or docs_used

    if names and profile == "overview":
        templates = [
            f"Просмотрел {names} — на их основе соберу обзор",
            f"По {names} уже видно основные темы, сейчас сведу это в ответ",
            f"В {names} нашёл достаточно, чтобы описать содержание",
        ]
    elif names:
        templates = [
            f"Нашёл нужные места в {names}",
            f"В {names} есть материал для ответа — сверяю формулировки",
            f"Опираюсь на {names} при подготовке ответа",
        ]
    elif n > 0:
        cp = _docs_count_phrase(n)
        templates = [
            f"Просмотрел {cp} — можно переходить к ответу",
            f"По {cp} собрал нужные выдержки",
            f"Материалы из {cp} просмотрены",
        ]
    else:
        templates = [
            "Просмотрел доступные материалы дела",
            "Прошёлся по документам — можно формулировать ответ",
        ]

    return _narrative_step(
        step_id="review",
        phase="retrieval",
        step=2,
        content=_pick_variant(templates, seed),
        status="completed",
    )


def _narrative_answer_running(*, overview: bool, question: str) -> AssistantActivityStep:
    profile = _question_profile(question) if question else ("overview" if overview else "general")
    seed = f"answer_run|{profile}|{overview}"
    if overview or profile == "overview":
        variants = [
            "Собираю краткий обзор по найденному",
            "Формулирую общее описание документов простым языком",
            "Свожу в ответ главное из просмотренных материалов",
        ]
    else:
        variants = [
            "Формулирую ответ по найденным фактам",
            "Собираю ответ, опираясь только на материалы дела",
            "Готовлю ответ с опорой на просмотренные документы",
        ]
    return _narrative_step(
        step_id="answer",
        phase="synthesizing",
        step=3,
        content=_pick_variant(variants, seed),
        status="running",
    )


def _activity_scope_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    task = _retrieval_task(node_data)
    file_ids = task.get("file_ids")
    file_count = len(file_ids) if isinstance(file_ids, list) else 0
    return _narrative_review_running(
        question=question,
        file_count=file_count,
        file_names=[],
    )


def _activity_review_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    names = _file_names_from_docs(node_data.get("rag_documents"))
    meta = node_data.get("context_pipeline_meta")
    scoped = 0
    if isinstance(meta, dict):
        raw = meta.get("scoped_files_count") or meta.get("unique_files")
        if isinstance(raw, int):
            scoped = raw
    return _narrative_review_completed(
        question=question,
        file_names=names,
        docs_used=scoped or len(names),
    )


def _activity_refine_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    names = _file_names_from_docs(node_data.get("rag_documents"))
    if names:
        return _narrative_review_completed(
            question=question,
            file_names=names,
            docs_used=len(names),
        )
    seed = f"refine_done|{question}"
    variants = [
        "Отобрал главное из найденного — можно переходить к ответу",
        "Оставил только релевантные выдержки",
        "Сверил найденное и убрал лишнее",
    ]
    return _narrative_step(
        step_id="review",
        phase="retrieval",
        step=2,
        content=_pick_variant(variants, seed),
        status="completed",
    )


def _activity_legal_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    has_context = bool(node_data.get("garant_context"))
    seed = f"legal|{has_context}|{question}"
    if has_context:
        variants = [
            "Сверил формулировки со справочником норм",
            "Подобрал релевантные нормы для контекста ответа",
            "Проверил правовые ориентиры по справочнику",
        ]
    else:
        variants = [
            "Смотрю справочник норм — пока без явных совпадений",
            "Проверяю нормативный контекст",
        ]
    return _narrative_step(
        step_id="legal",
        phase="legal",
        step=3,
        content=_pick_variant(variants, seed),
        status="completed",
        total_steps=5,
    )


def _activity_court_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    has_context = bool(node_data.get("court_practice_context"))
    seed = f"court|{has_context}|{question}"
    if has_context:
        variants = [
            "Нашёл подходящие примеры из судебной практики",
            "Сверил позицию с решениями судов по похожим вопросам",
        ]
    else:
        variants = [
            "Проверяю судебную практику по теме",
            "Ищу релевантные судебные решения",
        ]
    return _narrative_step(
        step_id="legal",
        phase="legal",
        step=3,
        content=_pick_variant(variants, seed),
        status="completed",
        total_steps=5,
    )


def _activity_clarify(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    _ = node_data
    seed = f"clarify|{question}"
    variants = [
        "Пока не хватает данных — задам уточняющий вопрос",
        "Нужно чуть больше контекста, сформулирую уточнение",
    ]
    return _narrative_step(
        step_id="clarify",
        phase="clarify",
        step=3,
        content=_pick_variant(variants, seed),
        status="completed",
    )


def _activity_answer_done(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    response = node_data.get("response")
    has_response = isinstance(response, str) and bool(response.strip())
    step = _narrative_answer_running(
        overview=_question_profile(question) == "overview",
        question=question,
    )
    return AssistantActivityStep(
        step_id=step.step_id,
        phase=step.phase,
        step=step.step,
        total_steps=step.total_steps,
        label=step.content,
        content=step.content,
        status="completed" if has_response else "running",
    )


def _activity_draft_plan(node_data: Dict[str, Any], *, question: str = "") -> AssistantActivityStep:
    _ = node_data
    seed = f"draft|{question}"
    variants = [
        "Продумываю структуру будущего документа",
        "Намечаю разделы и логику документа",
    ]
    return _narrative_step(
        step_id="draft",
        phase="draft",
        step=2,
        content=_pick_variant(variants, seed),
        status="completed",
        total_steps=5,
    )


def activity_sse(step: AssistantActivityStep) -> str:
    import json

    return f"data: {json.dumps(step.to_payload(), ensure_ascii=False)}\n\n"
