"""
LLM judge for Turn Context routing — memory vs scoped vs full retrieval.

Primary classifier: small structured LLM with dialog transcript + prior evidence.
Regex (referential_classifier) is fallback when LLM is disabled, fails, or low confidence.

Design goals:
- No arbitrary short-question length gate when LLM routes the turn.
- Deterministic safety net for high-risk patterns (memory_synthesis on «выводы»).
- Immutable invariants after LLM output (memory_synthesis never triggers RAG).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from app.services.chat.referential_classifier import ReferentialKind, classify_referential_kind
from app.services.chat.referential_query_resolver import _prior_context_block
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.session_replay_policy import is_repeated_user_question
from app.services.chat.session_transcript import turns_to_resolver_transcript
from app.services.chat.turn_context_evidence import PriorTurnEvidence

logger = logging.getLogger(__name__)

ReferentialJudgeResolver = Literal["llm", "regex_fallback", "regex_safety", "llm_regex_agree"]


@dataclass(frozen=True)
class ReferentialJudgeResult:
    referential_kind: ReferentialKind
    needs_document_retrieval: bool
    confidence: float
    reason: str
    resolver: ReferentialJudgeResolver
    standalone_query: str = ""


class ReferentialJudgeDecision(BaseModel):
    """Structured routing decision for one user turn."""

    referential_kind: Literal[
        "none",
        "memory_synthesis",
        "scoped_deep_read",
        "citation_expand",
    ] = Field(
        description=(
            "none: new topic or needs fresh full-case search. "
            "memory_synthesis: recap/summary of prior assistant answer — no document search. "
            "citation_expand: user wants source quote/location for prior answer — scoped search. "
            "scoped_deep_read: deictic/entity pointer into prior answer — scoped search."
        ),
    )
    needs_document_retrieval: bool = Field(
        description=(
            "False only when the chat transcript already contains enough facts "
            "(recap, rephrase, narrow prior answer). True for new facts or document quotes."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.75)
    rationale: str = Field(default="", max_length=320)
    standalone_query: str = Field(
        default="",
        description=(
            "Optional self-contained Russian search query when referential_kind is "
            "scoped_deep_read or citation_expand. Empty otherwise."
        ),
    )

    @field_validator("standalone_query", mode="before")
    @classmethod
    def _strip_standalone(cls, value: object) -> str:
        return str(value or "").strip()[:500]


def turn_context_llm_judge_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "TURN_CONTEXT_LLM_JUDGE_ENABLED", True))


def _judge_min_confidence() -> float:
    from app.config import config

    return max(0.0, min(1.0, float(getattr(config, "TURN_CONTEXT_LLM_JUDGE_MIN_CONF", 0.68) or 0.68)))


def _judge_max_turns() -> int:
    from app.config import config

    return max(2, int(getattr(config, "TURN_CONTEXT_LLM_JUDGE_MAX_TURNS", 10) or 10))


def _enforce_kind_invariants(
    kind: ReferentialKind,
    needs_document_retrieval: bool,
) -> tuple[ReferentialKind, bool]:
    """Legal-safe invariants — LLM output may only be normalized, never widened."""
    if kind == "memory_synthesis":
        return kind, False
    if kind in {"citation_expand", "scoped_deep_read"}:
        return kind, True
    if kind == "none" and not needs_document_retrieval:
        # Chat-only clarify without referential scope — treat as memory synthesis path.
        return "memory_synthesis", False
    return kind, True


def _build_judge_prompt(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    prior_evidence: PriorTurnEvidence | None,
    dialog_history: str,
    conversation_summary: str,
    anchor_filenames: Sequence[str],
) -> str:
    transcript = turns_to_resolver_transcript(list(turns), max_turns=_judge_max_turns())
    if not transcript.strip() and (dialog_history or "").strip():
        transcript = (dialog_history or "").strip()[:6000]

    prior_block = ""
    if prior_evidence is not None:
        prior_block = _prior_context_block(prior_evidence)

    summary = (conversation_summary or "").strip()
    files = ", ".join(str(x).strip() for x in anchor_filenames if str(x).strip())[:400]

    repeat_hint = ""
    if turns and is_repeated_user_question(question, turns):
        repeat_hint = (
            "\nВАЖНО: пользователь повторяет тот же вопрос, что уже задавал — "
            "referential_kind=none, needs_document_retrieval=true (нужен свежий ответ, не replay).\n"
        )

    return (
        "Ты маршрутизатор юридического case-assistant. По транскрипту чата и новому вопросу реши, "
        "как обрабатывать turn ДО поиска по документам дела.\n\n"
        "referential_kind (выбери один):\n"
        "- memory_synthesis: пересказ/выводы/итог/резюме прошлого ответа без новых фактов из документов.\n"
        "- citation_expand: «где написано», «покажи цитату/абзац», «откуда взял» — нужен источник "
        "из документов, уже связанных с прошлым ответом.\n"
        "- scoped_deep_read: «подробнее», «детальнее», «разверни» про документ/тему из прошлого ответа; "
        "deictic/указатель («эта сумма», «пункт 3», «там») — нужны дополнительные фрагменты документа, "
        "не пересказ чата.\n"
        "- none: новая тема, другой документ/период, сравнение с материалами которых не было в чате, "
        "или нужен полный поиск по делу.\n\n"
        "needs_document_retrieval:\n"
        "- false ТОЛЬКО для memory_synthesis (и chat-only clarify без новых фактов).\n"
        "- true для none, citation_expand, scoped_deep_read.\n\n"
        "standalone_query: заполни только для citation_expand/scoped_deep_read — "
        "самодостаточный русский запрос для RAG (без «эта сумма»).\n\n"
        "Правила:\n"
        "1) Если ответ уже в последнем ответе ассистента — не отправляй в полный RAG.\n"
        "2) «Ключевые выводы / итог / кратко» после substantive ответа → memory_synthesis.\n"
        "3) «Подробнее / детальнее / разверни» про документ или тему из прошлого ответа → "
        "scoped_deep_read + needs_document_retrieval=true.\n"
        "4) При сомнении и отсутствии фактов в чате → none + needs_document_retrieval=true.\n"
        "5) Не выдумывай факты — опирайся только на транскрипт и блок prior answer.\n"
        f"{repeat_hint}\n"
        f"Сводка сессии:\n{summary or '[нет]'}\n\n"
        f"Файлы из прошлых цитат:\n{files or '[нет]'}\n\n"
        f"Транскрипт (последние реплики):\n{transcript or '[пусто]'}\n\n"
        f"Prior answer / evidence:\n{prior_block or '[нет prior assistant turn]'}\n\n"
        f"Новый вопрос пользователя:\n{question.strip()}\n"
    )


def _invoke_llm_judge(prompt: str, *, question_chars: int) -> ReferentialJudgeDecision | None:
    from app.config import config

    if not turn_context_llm_judge_enabled():
        return None

    try:
        from app.services.llm_factory import create_llm
        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span
        from app.services.observability.langfuse_service import get_langchain_callbacks

        model = (
            getattr(config, "TURN_CONTEXT_LLM_JUDGE_MODEL", None)
            or getattr(config, "TURN_CONTEXT_LLM_QUERY_MODEL", None)
            or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "")
            or "yandexgpt-lite/latest"
        )
        max_tokens = int(getattr(config, "TURN_CONTEXT_LLM_JUDGE_MAX_TOKENS", 384) or 384)
        llm = create_llm(model=model, temperature=0.0, max_tokens=max_tokens)
        structured = llm.with_structured_output(ReferentialJudgeDecision)
        callbacks = get_langchain_callbacks(tags=["assistant", "turn_context", "llm_judge"])

        with assistant_step_span(
            "case",
            "turn_context.llm_judge",
            input_payload={"question_chars": question_chars},
        ) as span_out:
            decision: ReferentialJudgeDecision = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "Ты детерминированный маршрутизатор юридического ассистента. "
                            "Классифицируй turn строго по правилам. "
                            "memory_synthesis никогда не требует document retrieval."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            span_out["referential_kind"] = decision.referential_kind
            span_out["needs_document_retrieval"] = decision.needs_document_retrieval
            span_out["confidence"] = float(decision.confidence or 0.0)
        return decision
    except Exception as exc:
        logger.debug("turn context LLM judge failed: %s", exc)
        return None


def _result_from_regex(question: str, *, has_prior: bool) -> ReferentialJudgeResult:
    kind = classify_referential_kind(question, has_prior=has_prior)
    kind, needs_docs = _enforce_kind_invariants(
        kind,
        needs_document_retrieval=kind not in {"memory_synthesis"},
    )
    return ReferentialJudgeResult(
        referential_kind=kind,
        needs_document_retrieval=needs_docs,
        confidence=0.92 if kind != "none" else 0.55,
        reason=f"regex_{kind}",
        resolver="regex_fallback",
    )


def classify_referential_kind_judge(
    *,
    question: str,
    has_prior: bool,
    prior_evidence: PriorTurnEvidence | None = None,
    turns: Sequence[SessionMessageTurn] = (),
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Sequence[str] = (),
    allow_llm: bool = True,
) -> ReferentialJudgeResult:
    """
    Primary turn router: LLM judge with regex fallback and safety merge.

    When prior assistant turn exists, LLM sees full recent transcript (not only regex patterns).
    FAST latency path passes ``allow_llm=False`` to avoid a network round-trip.
    """
    q = (question or "").strip()
    if not q:
        return ReferentialJudgeResult(
            referential_kind="none",
            needs_document_retrieval=True,
            confidence=0.0,
            reason="empty_question",
            resolver="regex_fallback",
        )

    regex_result = _result_from_regex(q, has_prior=has_prior)

    if not has_prior:
        return regex_result

    # Structural classifier matched — deterministic routing wins (no LLM override).
    if regex_result.referential_kind != "none":
        return regex_result

    if not allow_llm:
        return ReferentialJudgeResult(
            referential_kind="none",
            needs_document_retrieval=True,
            confidence=max(0.55, regex_result.confidence),
            reason="latency_path_skip_llm_judge",
            resolver="regex_fallback",
        )

    prompt = _build_judge_prompt(
        question=q,
        turns=turns,
        prior_evidence=prior_evidence,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )
    decision = _invoke_llm_judge(prompt, question_chars=len(q))

    if decision is None:
        return regex_result

    llm_kind_raw = str(decision.referential_kind or "none").strip().lower()
    llm_kind: ReferentialKind = (
        llm_kind_raw if llm_kind_raw in {"none", "memory_synthesis", "scoped_deep_read", "citation_expand"}
        else "none"
    )
    llm_kind, llm_needs_docs = _enforce_kind_invariants(llm_kind, bool(decision.needs_document_retrieval))
    llm_conf = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    llm_reason = (decision.rationale or "llm_judge")[:320]
    standalone = re.sub(r"\s+", " ", (decision.standalone_query or "").strip())

    min_conf = _judge_min_confidence()

    # Drill-down: structural classifier treats deictic «подробнее» as scoped_deep_read;
    # LLM must not collapse that into memory_synthesis (chat has summary, not full doc).
    if (
        llm_kind == "memory_synthesis"
        and regex_result.referential_kind in {"scoped_deep_read", "citation_expand"}
    ):
        return ReferentialJudgeResult(
            referential_kind=regex_result.referential_kind,
            needs_document_retrieval=True,
            confidence=max(regex_result.confidence, llm_conf),
            reason=f"regex_drill_down_overrides_memory;{llm_reason[:200]}",
            resolver="regex_safety",
            standalone_query=standalone or regex_result.standalone_query,
        )

    # High-confidence LLM wins — including long-form memory_synthesis questions regex misses.
    if llm_conf >= min_conf:
        resolver: ReferentialJudgeResolver = "llm"
        if regex_result.referential_kind == llm_kind and regex_result.referential_kind != "none":
            resolver = "llm_regex_agree"
        return ReferentialJudgeResult(
            referential_kind=llm_kind,
            needs_document_retrieval=llm_needs_docs,
            confidence=llm_conf,
            reason=llm_reason,
            resolver=resolver,
            standalone_query=standalone,
        )

    # Safety: regex caught memory_synthesis but LLM was uncertain — keep chat-only path.
    if (
        regex_result.referential_kind == "memory_synthesis"
        and llm_kind != "memory_synthesis"
    ):
        return ReferentialJudgeResult(
            referential_kind="memory_synthesis",
            needs_document_retrieval=False,
            confidence=max(regex_result.confidence, llm_conf),
            reason=f"regex_safety;{llm_reason[:200]}",
            resolver="regex_safety",
        )

    # Low-confidence LLM — fall back to regex structural classifier.
    if regex_result.referential_kind != "none":
        return ReferentialJudgeResult(
            referential_kind=regex_result.referential_kind,
            needs_document_retrieval=regex_result.needs_document_retrieval,
            confidence=regex_result.confidence,
            reason=f"regex_fallback;{llm_reason[:160]}",
            resolver="regex_fallback",
            standalone_query=standalone if standalone else "",
        )

    return ReferentialJudgeResult(
        referential_kind=llm_kind,
        needs_document_retrieval=llm_needs_docs,
        confidence=llm_conf,
        reason=f"llm_low_conf;{llm_reason[:160]}",
        resolver="llm",
        standalone_query=standalone,
    )
