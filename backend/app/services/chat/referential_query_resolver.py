"""
Phase 2 — referential query resolution for scoped follow-ups.

Rewrites deictic / underspecified questions into standalone retrieval queries
using PriorTurnEvidence (prior assistant excerpt + citation anchors), not raw
chat history. LLM-lite with deterministic fallback.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from app.services.chat.referential_classifier import ReferentialKind
from app.services.chat.standalone_query_resolver import (
    StandaloneQueryResult,
    resolve_standalone_query,
)
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence

logger = logging.getLogger(__name__)

ReferentialQueryKind = Literal["scoped_deep_read", "citation_expand"]


@dataclass(frozen=True)
class ReferentialQueryResult:
    original_question: str
    standalone_query: str
    reason: str
    changed: bool
    resolver: str  # llm | prior_excerpt_fallback | unchanged


class ReferentialQueryResolution(BaseModel):
    standalone_query: str = Field(
        description=(
            "Self-contained Russian search query for case document retrieval. "
            "Replace deictic words (эта сумма, пункт 2, там) with concrete entities "
            "from the prior assistant answer."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.75)
    reason: str = Field(default="", max_length=200)


def referential_query_llm_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "TURN_CONTEXT_LLM_QUERY_RESOLVE_ENABLED", True))


def _prior_context_block(prior: PriorTurnEvidence) -> str:
    parts: list[str] = []
    excerpt = (prior.assistant_excerpt or "").strip()
    if excerpt:
        parts.append(f"Предыдущий ответ ассистента:\n{excerpt[:2200]}")

    quotes = _format_citation_quotes(prior.citations)
    if quotes:
        parts.append(f"Цитаты из документов:\n{quotes}")

    scoped_files = prior.retrieval_metadata.get("scoped_file_ids") or prior.retrieval_metadata.get(
        "file_ids"
    )
    if isinstance(scoped_files, list) and scoped_files:
        parts.append("Файлы прошлого ответа: " + ", ".join(str(x) for x in scoped_files[:5]))

    return "\n\n".join(parts)


def _format_citation_quotes(citations: Sequence[CitationAnchor]) -> str:
    lines: list[str] = []
    for anchor in citations[:6]:
        quote = (anchor.quote_excerpt or "").strip()
        if not quote:
            continue
        label = anchor.source_id or "unknown"
        lines.append(f"- [{label}]: {quote[:400]}")
    return "\n".join(lines)


def _anchor_filenames_from_prior(prior: PriorTurnEvidence) -> list[str]:
    names: list[str] = []
    meta_names = prior.retrieval_metadata.get("filenames") or prior.retrieval_metadata.get(
        "anchor_filenames"
    )
    if isinstance(meta_names, list):
        names.extend(str(x).strip() for x in meta_names if str(x).strip())
    return names


def _resolve_with_llm(
    *,
    question: str,
    prior: PriorTurnEvidence,
    referential_kind: ReferentialQueryKind,
) -> ReferentialQueryResult | None:
    from app.config import config

    if not referential_query_llm_enabled():
        return None

    q = (question or "").strip()
    if not q:
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.llm_factory import create_llm
        from app.services.observability.langfuse_service import get_langchain_callbacks

        model = (
            getattr(config, "TURN_CONTEXT_LLM_QUERY_MODEL", None)
            or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "")
            or "yandexgpt-lite/latest"
        )
        max_tokens = int(getattr(config, "TURN_CONTEXT_LLM_QUERY_MAX_TOKENS", 256) or 256)
        llm = create_llm(model=model, temperature=0.0, max_tokens=max_tokens)
        structured = llm.with_structured_output(ReferentialQueryResolution)

        kind_hint = (
            "Пользователь просит показать источник/цитату из документа."
            if referential_kind == "citation_expand"
            else "Пользователь уточняет деталь из прошлого ответа — нужен поиск в документе."
        )
        context_block = _prior_context_block(prior)
        prompt = (
            f"{kind_hint}\n\n"
            f"{context_block}\n\n"
            f"Новый вопрос пользователя (может содержать «эта сумма», «п. 2», «там»):\n{q}\n\n"
            "Сформулируй один самодостаточный поисковый запрос на русском для hybrid RAG "
            "по материалам дела. Не добавляй пояснений — только текст запроса."
        )
        callbacks = get_langchain_callbacks(tags=["assistant", "turn_context", "referential_query"])

        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span

        with assistant_step_span(
            "case",
            "turn_context.referential_query_llm",
            input_payload={"question_chars": len(q), "referential_kind": referential_kind},
        ) as span_out:
            decision: ReferentialQueryResolution = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "Ты переформулируешь уточняющие юридические вопросы в самодостаточные "
                            "поисковые запросы. Используй только факты из предыдущего ответа ассистента."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            resolved = re.sub(r"\s+", " ", (decision.standalone_query or "").strip())
            span_out["changed"] = bool(resolved and resolved.lower() != q.lower())
            span_out["confidence"] = float(decision.confidence or 0.0)
        if not resolved or len(resolved) < 4:
            return None
        changed = resolved.lower() != q.lower()
        return ReferentialQueryResult(
            original_question=q,
            standalone_query=resolved if changed else q,
            reason=(decision.reason or "llm_referential_query")[:200],
            changed=changed,
            resolver="llm",
        )
    except Exception as exc:
        logger.debug("referential query LLM failed: %s", exc)
        return None


def _enrich_query_from_prior_excerpt(question: str, prior: PriorTurnEvidence) -> str:
    """Deterministic fallback: anchor deictic question to overlapping entity in prior excerpt."""
    q = (question or "").strip()
    excerpt = (prior.assistant_excerpt or "").strip()
    if not q or not excerpt:
        return q

    q_tokens = [t for t in re.findall(r"[а-яё]{4,}", q.lower()) if t not in {"откуда", "этого", "этом"}]
    excerpt_lower = excerpt.lower()
    for token in q_tokens:
        if token not in excerpt_lower:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", excerpt):
            sent = sentence.strip()
            if token in sent.lower() and len(sent) >= 12:
                return f"{q.rstrip('?.! ')} ({sent[:200]})"
    if len(excerpt) >= 40:
        return f"{q.rstrip('?.! ')} ({excerpt[:180]})"
    return q


def _resolve_with_prior_excerpt(
    *,
    question: str,
    prior: PriorTurnEvidence,
) -> ReferentialQueryResult:
    q = (question or "").strip()
    fallback = resolve_standalone_query(
        q,
        dialog_history=prior.assistant_excerpt,
        anchor_filenames=_anchor_filenames_from_prior(prior),
    )
    resolved = fallback.resolved_question
    reason = fallback.reason
    if not fallback.changed:
        enriched = _enrich_query_from_prior_excerpt(q, prior)
        if enriched.lower() != q.lower():
            resolved = enriched
            reason = "prior_excerpt_entity_overlap"
    return ReferentialQueryResult(
        original_question=q,
        standalone_query=resolved,
        reason=reason,
        changed=resolved.lower() != q.lower(),
        resolver="prior_excerpt_fallback",
    )


def resolve_referential_query(
    *,
    question: str,
    prior_evidence: PriorTurnEvidence | None,
    referential_kind: ReferentialKind,
) -> ReferentialQueryResult:
    """
    Phase 2 query expansion for referential follow-ups.

    Uses PriorTurnEvidence as the sole context source (not full dialog history).
    """
    q = (question or "").strip()
    if referential_kind not in {"scoped_deep_read", "citation_expand"}:
        return ReferentialQueryResult(
            original_question=q,
            standalone_query=q,
            reason="not_referential_query",
            changed=False,
            resolver="unchanged",
        )

    if prior_evidence is None or not (prior_evidence.assistant_excerpt or "").strip():
        return ReferentialQueryResult(
            original_question=q,
            standalone_query=q,
            reason="no_prior_evidence",
            changed=False,
            resolver="unchanged",
        )

    llm_result = _resolve_with_llm(
        question=q,
        prior=prior_evidence,
        referential_kind=referential_kind,  # type: ignore[arg-type]
    )
    if llm_result is not None and llm_result.changed:
        return llm_result

    excerpt_result = _resolve_with_prior_excerpt(question=q, prior=prior_evidence)
    if excerpt_result.changed:
        if llm_result is not None:
            excerpt_result = ReferentialQueryResult(
                original_question=excerpt_result.original_question,
                standalone_query=excerpt_result.standalone_query,
                reason=f"{excerpt_result.reason};llm_unchanged",
                changed=True,
                resolver=excerpt_result.resolver,
            )
        return excerpt_result

    if llm_result is not None:
        return llm_result

    return ReferentialQueryResult(
        original_question=q,
        standalone_query=q,
        reason="unresolved_referential",
        changed=False,
        resolver="unchanged",
    )


def to_standalone_result(result: ReferentialQueryResult) -> StandaloneQueryResult:
    return StandaloneQueryResult(
        original_question=result.original_question,
        resolved_question=result.standalone_query,
        reason=result.reason,
        changed=result.changed,
    )
