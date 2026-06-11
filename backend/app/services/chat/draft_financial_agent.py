"""Draft-only agent: decides whether to invoke the RF financial calculator tool."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from app.config import config
from app.services.draft_pipeline.schemas import DraftTaskPlan, ExtractedFacts
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

_TOOL_NAME = "compute_contract_financials"
_MAX_RAG_CHARS = 4000
_MAX_FACTS_JSON_CHARS = 12000


class _CalculatorToolInput(BaseModel):
    reason: str = Field(
        description=(
            "Краткое обоснование: какие денежные показатели нужно проверить "
            "(неустойка, срок оплаты, остаток долга, итог иска)."
        )
    )


def _compact_facts_json(facts: ExtractedFacts) -> str:
    raw = facts.to_prompt_json()
    text = json.dumps(raw, ensure_ascii=False, indent=2)
    if len(text) > _MAX_FACTS_JSON_CHARS:
        text = text[:_MAX_FACTS_JSON_CHARS] + "\n…"
    return text


def _tool_was_called(messages: List[Any], tool_name: str) -> bool:
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls or []:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name == tool_name:
                    return True
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None) or (msg.additional_kwargs or {}).get("name")
            if name == tool_name:
                return True
    return False


def _build_user_brief(
    *,
    user_prompt: str,
    facts: ExtractedFacts,
    rag_context: str,
    task_plan: Optional[DraftTaskPlan],
) -> str:
    plan_line = ""
    if task_plan:
        plan_line = (
            f"Тип документа (план): {task_plan.target_document_type or '—'}\n"
            f"Категория дела: {task_plan.case_category or '—'}\n"
        )
    rag = (rag_context or "").strip()
    if len(rag) > _MAX_RAG_CHARS:
        rag = rag[:_MAX_RAG_CHARS] + "\n…"

    return f"""Задача юриста (draft):
{user_prompt.strip()}

{plan_line}
Фрагмент контекста из материалов дела:
{rag or '(контекст не передан — опирайся на извлечённые факты)'}

Извлечённые структурированные факты (JSON):
{_compact_facts_json(facts)}

Реши, нужен ли детерминированный расчёт денежных показателей для этого документа.
Если да — вызови инструмент `{_TOOL_NAME}` с кратким reason.
Если нет — ответь одной фразой, почему расчёт не нужен (без вызова инструмента)."""


_SYSTEM_PROMPT = f"""Ты — юридический ассистент на этапе подготовки draft-документа по материалам дела.

У тебя один инструмент: `{_TOOL_NAME}` — детерминированный калькулятор по договору:
срок оплаты (рабочие дни РФ), неустойка, частичные платежи, итоговая сумма иска.

КОГДА ВЫЗЫВАТЬ `{_TOOL_NAME}`:
- Иск / претензия / заявление о взыскании задолженности, неустойки, пени, процентов.
- В задаче или фактах есть суммы, срок оплаты, ставка неустойки, акт/отгрузка, частичная оплата.
- Для текста документа нужны проверенные цифры, а не оценка «на глаз».

КОГДА НЕ ВЫЗЫВАТЬ:
- Доверенность, ходатайство без денежных требований, процессуальные документы без сумм.
- Нет данных для расчёта и задача не про деньги.
- Достаточно описать факты без арифметики.

Ты САМ принимаешь решение. Не вызывай инструмент «на всякий случай».
Сам расчёт выполняет Python — твоя задача только решить, нужен ли он сейчас."""


def run_draft_financial_calculator_agent(
    *,
    user_prompt: str,
    facts: ExtractedFacts,
    rag_context: str = "",
    task_plan: Optional[DraftTaskPlan] = None,
) -> Tuple[ExtractedFacts, Dict[str, Any]]:
    """
    Draft-only: LLM agent decides whether to call the financial calculator tool.

    Returns updated facts and audit meta (``tool_called``, ``applied``, ``agent_reason``).
    """
    from app.services.chat.financial_calculator_instrument import execute_financial_calculator

    meta: Dict[str, Any] = {
        "source": "draft_financial_agent",
        "tool_called": False,
        "applied": False,
        "computable": False,
        "agent_reason": "",
        "agent_skipped_reason": "",
        "error": "",
    }

    if not bool(getattr(config, "DRAFT_FINANCIAL_CALCULATOR_ENABLED", True)):
        meta["agent_skipped_reason"] = "calculator_disabled"
        return facts, meta

    holder: Dict[str, Any] = {"facts": facts, "tool_result": None}

    def _run_calculator(reason: str) -> str:
        updated, tool_meta = execute_financial_calculator(holder["facts"], reason=reason)
        holder["facts"] = updated
        holder["tool_result"] = tool_meta
        if tool_meta.get("applied"):
            verified = updated.financial.verified
            return json.dumps(
                {
                    "status": "applied",
                    "total_claim": updated.financial.total_to_claim,
                    "penalty_amount": updated.financial.penalty_claim,
                    "penalty_days": verified.penalty_days if verified else None,
                    "payment_deadline": verified.payment_deadline if verified else None,
                },
                ensure_ascii=False,
            )
        if tool_meta.get("computable") is False:
            return json.dumps(
                {"status": "insufficient_data", "detail": tool_meta.get("skip_reason", "")},
                ensure_ascii=False,
            )
        return json.dumps({"status": "not_applied"}, ensure_ascii=False)

    tool = StructuredTool.from_function(
        func=_run_calculator,
        name=_TOOL_NAME,
        description=(
            "Проверить и посчитать денежные показатели по договору: срок оплаты, неустойку, "
            "остаток долга, итог иска. Вызывай только если документ требует точных сумм."
        ),
        args_schema=_CalculatorToolInput,
    )

    try:
        llm = create_legal_llm(max_tokens=2048)
        agent = create_react_agent(
            model=llm,
            tools=[tool],
            prompt=_SYSTEM_PROMPT,
        )
        brief = _build_user_brief(
            user_prompt=user_prompt,
            facts=facts,
            rag_context=rag_context,
            task_plan=task_plan,
        )
        result = agent.invoke(
            {"messages": [HumanMessage(content=brief)]},
            config={"recursion_limit": 6},
        )
        messages = result.get("messages") or []
        meta["tool_called"] = _tool_was_called(messages, _TOOL_NAME)

        if holder["tool_result"]:
            meta.update(
                {
                    k: holder["tool_result"].get(k)
                    for k in ("applied", "computable", "agent_reason", "skip_reason")
                    if k in holder["tool_result"]
                }
            )
            if holder["tool_result"].get("agent_reason"):
                meta["agent_reason"] = holder["tool_result"]["agent_reason"]

        if not meta["tool_called"]:
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    meta["agent_skipped_reason"] = str(msg.content).strip()[:500]
                    break

        logger.info(
            "[draft_financial_agent] tool_called=%s applied=%s reason=%s skip=%s",
            meta["tool_called"],
            meta.get("applied"),
            (meta.get("agent_reason") or "")[:80],
            (meta.get("agent_skipped_reason") or "")[:80],
        )
        return holder["facts"], meta

    except Exception as exc:
        logger.error("[draft_financial_agent] failed: %s", exc, exc_info=True)
        meta["error"] = str(exc)[:300]
        return facts, meta
