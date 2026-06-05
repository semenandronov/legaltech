"""
Optional LLM classifier for case-assistant execution tier (adaptive RAG).
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.config import config

logger = logging.getLogger(__name__)

ExecutionTierChoice = Literal[
    "no_retrieval",
    "clarify",
    "instant",
    "standard",
    "deep",
    "mixed",
]


class ExecutionTierClassification(BaseModel):
    execution_tier: ExecutionTierChoice = Field(
        description="How deeply to search the case corpus before answering.",
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
    reason: str = Field(default="", max_length=200)


def tier_llm_classifier_enabled() -> bool:
    return bool(
        getattr(config, "CASE_ASSISTANT_TIER_LLM_ENABLED", False)
        and getattr(config, "CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", True)
    )


def classify_execution_tier_llm(
    *,
    question: str,
    task_type: str = "",
    depth_tier: str = "",
    clarification_needed: bool = False,
    legal_research: bool = False,
    deep_think: bool = False,
    draft_mode: bool = False,
    corpus_size: int = 0,
    attached_files_count: int = 0,
) -> Optional[ExecutionTierChoice]:
    """Structured tier from lite model; None on disable or failure."""
    if not tier_llm_classifier_enabled():
        return None
    if draft_mode or legal_research or deep_think:
        return None

    q = (question or "").strip()
    if not q:
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.llm_factory import create_llm

        model = (
            getattr(config, "CASE_ASSISTANT_TIER_CLASSIFIER_MODEL", None)
            or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "")
            or "yandexgpt-lite/latest"
        )
        llm = create_llm(model=model, temperature=0.0, max_tokens=128)
        structured = llm.with_structured_output(ExecutionTierClassification)
        result: ExecutionTierClassification = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "Классифицируй глубину поиска по материалам дела для юриста.\n"
                        "no_retrieval — приветствие/благодарность без вопроса по делу.\n"
                        "clarify — вопрос слишком расплывчатый, нет scope.\n"
                        "instant — один факт, узкий вопрос.\n"
                        "standard — один документ или краткий разбор.\n"
                        "deep — обзор, сравнение, синтез по многим документам.\n"
                        "mixed — только если нужен справочник норм (legal_research).\n"
                        "Не выбирай mixed без legal_research."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Вопрос: {q[:800]}\n"
                        f"task_type={task_type} depth_tier={depth_tier} "
                        f"clarification_needed={clarification_needed} "
                        f"corpus_size={corpus_size} attached_files={attached_files_count}"
                    )
                ),
            ]
        )
        tier = result.execution_tier
        if result.confidence < 0.55:
            logger.info(
                "[TierClassifier] low confidence %.2f tier=%s — heuristic fallback",
                result.confidence,
                tier,
            )
            return None
        logger.info(
            "[TierClassifier] tier=%s confidence=%.2f reason=%s",
            tier,
            result.confidence,
            (result.reason or "")[:80],
        )
        return tier
    except Exception as exc:
        logger.warning("[TierClassifier] failed: %s", exc)
        return None
