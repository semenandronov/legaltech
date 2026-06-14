"""Post-compile coherence linter — stylistic polish without changing facts."""
from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.markers import find_gap_markers, html_tag_balance_ok
from app.services.draft_pipeline.schemas import ExtractedFacts
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def _strip_html_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:html)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_amount_tokens(facts: ExtractedFacts) -> set[str]:
    """Money digit sequences from verified financial fields — must survive linter."""
    tokens: set[str] = set()
    fin = facts.financial
    texts = [
        fin.principal_claim,
        fin.penalty_claim,
        fin.total_to_claim,
    ]
    if fin.verified:
        texts.extend(
            [
                fin.verified.principal_outstanding,
                fin.verified.penalty_amount,
                fin.verified.total_claim,
            ]
        )
    for p in fin.partial_payments:
        texts.append(p.amount)

    for text in texts:
        digits = re.sub(r"\D", "", text or "")
        if len(digits) < 5:
            continue
        # Skip ISO-like dates accidentally parsed as amounts (YYYYMMDD)
        if len(digits) == 8 and digits.startswith("20"):
            continue
        tokens.add(digits)
    return tokens


def _validate_linter_output(
    *,
    original: str,
    candidate: str,
    facts: ExtractedFacts,
) -> bool:
    if not candidate or len(candidate) < len(original) * 0.5:
        return False
    if not html_tag_balance_ok(candidate):
        return False

    orig_gaps = {label for label, _, _ in find_gap_markers(original)}
    new_gaps = {label for label, _, _ in find_gap_markers(candidate)}
    if not orig_gaps.issubset(new_gaps):
        logger.warning("[draft_pipeline.linter] gap markers removed: %s", orig_gaps - new_gaps)
        return False

    for token in _extract_amount_tokens(facts):
        if token not in re.sub(r"\D", "", candidate):
            logger.warning("[draft_pipeline.linter] amount token missing: %s", token)
            return False

    return True


def run_document_linter(
    *,
    html: str,
    facts: ExtractedFacts,
    user_prompt: str,
) -> str:
    """
    Final LLM pass: smooth transitions and remove obvious duplication.
    Reverts to original HTML if output fails validation.
    """
    if not bool(getattr(config, "DRAFT_LINTER_ENABLED", True)):
        return html
    source = (html or "").strip()
    if not source or len(source) < 80:
        return html

    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        prompt = f"""Ты юридический редактор. Полируешь СКЛЕЕННЫЙ HTML документа.

ЗАДАНИЕ ЮРИСТА (контекст):
{user_prompt[:800]}

ПАСПОРТ ФАКТОВ (НЕ МЕНЯТЬ цифры, ИНН, даты, стороны):
{facts.to_prompt_json()}

HTML ДОКУМЕНТА:
{source[:48000]}

ЗАДАЧА:
- Убрать дословные повторы между соседними абзацами.
- Сгладить стыки между разделами (1–2 связки), без добавления новых фактов.
- Исправить явные грамматические огрехи.

ЗАПРЕЩЕНО:
- Менять суммы, даты, ИНН, наименования сторон.
- Удалять или изменять маркеры пропусков в квадратных скобках [поле].
- Менять структуру HTML (теги, порядок section/table).
- Добавлять новые факты.

Верни ТОЛЬКО итоговый HTML без markdown-обёртки."""

        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        polished = _strip_html_fences(raw)

        if _validate_linter_output(original=source, candidate=polished, facts=facts):
            logger.info("[draft_pipeline.linter] applied polish chars=%s→%s", len(source), len(polished))
            return polished

        logger.warning("[draft_pipeline.linter] validation failed, keeping original")
    except Exception as exc:
        logger.warning("[draft_pipeline.linter] failed: %s", exc)

    return html
