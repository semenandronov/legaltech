"""Case fact passport extraction (Step 2 — single source of truth)."""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.json_utils import parse_llm_json_object
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot, ExtractedFacts, PenaltyTerms
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

_PASSPORT_PROMPT = """Ты юридический аналитик. Сформируй «паспорт фактов дела» — единый JSON, который будет
единственным источником правды при генерации всех разделов документа.

ЗАДАНИЕ ЮРИСТА:
{user_prompt}

МАТЕРИАЛЫ ДЕЛА (фрагменты, могут быть из разных файлов):
{rag_block}

ПРАВИЛА:
1. Факты из ЗАДАНИЯ ЮРИСТА включай, если юрист указал их явно (стороны, суммы, даты, ставка).
   Из материалов дела — только подтверждённые фрагментами. Не домысливай.
2. document_type — тип итогового документа (например: «исковое заявление»).
3. penalty_terms — СЫРЫЕ условия для расчёта (без итоговых сумм неустойки):
   - payment_term_value: число (например 10)
   - payment_term_unit: business_days | calendar_days
   - payment_term_from: act_signed | contract_signed | delivery | other
   - term_count_starts: next_day (типично для «с момента подписания») | same_day
   - act_date, contract_date: ISO YYYY-MM-DD если известны
   - penalty_rate_percent_per_day: ставка в % за день (например "0.1" для 0,1%)
   - principal_amount: основной долг/цена договора числом (например "4500000")
   - penalty_end_date: дата «по состоянию на» / дата иска ISO, если указана в задании юриста
   - partial_payments: как в financial
4. financial — только факты из документов:
   - principal_claim: формулировка основного долга (можно с суммой из договора)
   - partial_payments: частичные оплаты из платёжек
   - penalty_claim, total_to_claim: оставь ПУСТЫМИ — их посчитает калькулятор Python
   - computation_method: оставь пустым или кратко «расчёт будет выполнен автоматически»
   - confidence: partial (пока нет verified)
5. Суммы и даты сохраняй максимально структурированно; даты предпочтительно ISO.

Верни СТРОГО JSON:
{{
  "document_type": "...",
  "parties": {{"роль": "наименование/ФИО"}},
  "amounts": {{"метка": "значение"}},
  "dates": {{"метка": "дата"}},
  "identifiers": {{"ИНН/ОГРН/номер дела": "значение"}},
  "other": {{"ключ": "значение"}},
  "penalty_terms": {{
    "payment_term_value": 10,
    "payment_term_unit": "business_days",
    "payment_term_from": "act_signed",
    "term_count_starts": "next_day",
    "act_date": "2025-06-02",
    "contract_date": "",
    "penalty_rate_percent_per_day": "0.1",
    "principal_amount": "",
    "penalty_end_date": "",
    "partial_payments": [{{"date": "", "amount": "", "source": "", "note": ""}}]
  }},
  "financial": {{
    "principal_claim": "",
    "penalty_claim": "",
    "partial_payments": [{{"date": "", "amount": "", "source": "", "note": ""}}],
    "total_to_claim": "",
    "computation_method": "",
    "confidence": "partial"
  }}
}}"""


def extract_case_fact_passport(
    *,
    user_prompt: str,
    case_retrieval: CaseRetrievalSnapshot,
) -> ExtractedFacts:
    rag_block = (case_retrieval.rag_context or "").strip()

    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        prompt = _PASSPORT_PROMPT.format(
            user_prompt=user_prompt,
            rag_block=rag_block or "(материалы не найдены)",
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        parsed = parse_llm_json_object(raw)
        if parsed:
            facts = ExtractedFacts.from_llm_dict(parsed)
            # Merge partial payments from financial into penalty_terms when missing
            if facts.penalty_terms and not facts.penalty_terms.partial_payments:
                facts.penalty_terms.partial_payments = list(facts.financial.partial_payments)
            elif facts.penalty_terms is None and facts.financial.partial_payments:
                facts = facts.model_copy(
                    update={"penalty_terms": PenaltyTerms(partial_payments=list(facts.financial.partial_payments))}
                )
            logger.info(
                "[draft_pipeline.passport] type=%s financial_conf=%s payments=%s penalty_term=%s",
                facts.document_type[:60] if facts.document_type else "-",
                facts.financial.confidence,
                len(facts.financial.partial_payments),
                facts.penalty_terms.payment_term_value if facts.penalty_terms else 0,
            )
            return facts
    except Exception as exc:
        logger.warning("[draft_pipeline.passport] extraction failed: %s", exc)

    return ExtractedFacts()
