"""Layer 1: decompose lawyer task into retrieval sub-queries."""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.config import config
from app.services.draft_pipeline.document_roles import CORE_DATA_ROLES, SIDEBAR_ROLES
from app.services.draft_pipeline.json_utils import parse_llm_json_object
from app.services.draft_pipeline.schemas import DraftTaskPlan, RetrievalSubQuery
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

_DECOMPOSE_PROMPT = """Ты — планировщик юридического draft-пайплайна. Разбей задачу юриста на конкретные поисковые подзапросы
к материалам дела. НЕ пиши текст документа — только план поиска.

ЗАДАЧА ЮРИСТА:
{user_prompt}

Верни СТРОГО JSON:
{{
  "target_document_type": "исковое заявление | претензия | заявление о включении | …",
  "case_category": "supply_debt | services_debt | bankruptcy | other",
  "required_doc_roles": [
    "contract",
    "primary_execution_act",
    "payment_order",
    "pretension",
    "egrul_extract"
  ],
  "sub_queries": [
    {{
      "query_id": "q1",
      "role": "contract",
      "search_query": "договор поставки номер дата условия оплаты неустойка стороны",
      "purpose": "найти договор и условия оплаты"
    }}
  ]
}}

Допустимые role: contract, primary_execution_act, payment_order, pretension, invoice,
delivery_note, egrul_extract, charter, power_of_attorney, requisites.
Минимум 3 sub_queries для долговых споров (договор, акт/УПД, платёжки). Добавь requisites/egrul если нужны реквизиты."""


def _heuristic_plan(user_prompt: str) -> DraftTaskPlan:
    q = (user_prompt or "").strip()
    low = q.lower()
    category = "supply_debt" if any(x in low for x in ("поставк", "договор", "отгруз")) else "other"
    if "банкрот" in low or "реестр" in low:
        category = "bankruptcy"
        doc_type = "заявление о включении в реестр"
    elif "претенз" in low:
        doc_type = "претензия"
    else:
        doc_type = "исковое заявление"

    roles = ["contract", "primary_execution_act", "payment_order", "requisites"]
    if "претенз" in low or "досудеб" in low:
        roles.append("pretension")

    sub_queries: list[RetrievalSubQuery] = []
    templates = [
        ("contract", f"{q[:120]} договор номер дата условия оплаты срок неустойка процент"),
        ("primary_execution_act", f"{q[:120]} акт приёмки передачи УПД отгрузка дата сумма"),
        ("payment_order", f"{q[:120]} платёжное поручение оплата частичная погашение"),
        ("pretension", f"{q[:120]} претензия досудебная претензионный порядок"),
        ("requisites", f"{q[:120]} ИНН ОГРН адрес наименование стороны реквизиты выписка"),
    ]
    for role, sq in templates:
        if role not in roles and role not in SIDEBAR_ROLES:
            continue
        if role == "pretension" and "pretension" not in roles:
            continue
        sub_queries.append(
            RetrievalSubQuery(
                query_id=f"q_{role}",
                role=role,
                search_query=sq.strip(),
                purpose=f"find_{role}",
            )
        )

    return DraftTaskPlan(
        target_document_type=doc_type,
        case_category=category,
        required_doc_roles=[r for r in roles if r in CORE_DATA_ROLES or r in SIDEBAR_ROLES],
        sub_queries=sub_queries[:8],
        source="heuristic",
    )


def _normalize_plan(raw: dict, user_prompt: str) -> DraftTaskPlan:
    sub_raw = raw.get("sub_queries") or []
    sub_queries: list[RetrievalSubQuery] = []
    for i, item in enumerate(sub_raw):
        if not isinstance(item, dict):
            continue
        sq = str(item.get("search_query") or "").strip()
        if not sq:
            continue
        role = str(item.get("role") or "").strip()
        sub_queries.append(
            RetrievalSubQuery(
                query_id=str(item.get("query_id") or f"q{i+1}"),
                role=role,
                search_query=sq[:500],
                purpose=str(item.get("purpose") or "")[:200],
            )
        )
    if len(sub_queries) < 2:
        return _heuristic_plan(user_prompt)

    roles_raw = raw.get("required_doc_roles") or []
    roles = [str(r).strip() for r in roles_raw if str(r).strip()] if isinstance(roles_raw, list) else []

    return DraftTaskPlan(
        target_document_type=str(raw.get("target_document_type") or "").strip()[:200],
        case_category=str(raw.get("case_category") or "other").strip()[:64],
        required_doc_roles=roles,
        sub_queries=sub_queries[:10],
        source="llm",
    )


def decompose_draft_task(user_prompt: str) -> DraftTaskPlan:
    """Produce structured retrieval plan from lawyer brief."""
    prompt_text = (user_prompt or "").strip()
    if not prompt_text:
        return DraftTaskPlan(source="empty")

    try:
        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        resp = llm.invoke([HumanMessage(content=_DECOMPOSE_PROMPT.format(user_prompt=prompt_text[:2000]))])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        parsed = parse_llm_json_object(raw)
        if parsed:
            plan = _normalize_plan(parsed, prompt_text)
            logger.info(
                "[draft_pipeline.decompose] source=%s sub_queries=%s category=%s",
                plan.source,
                len(plan.sub_queries),
                plan.case_category,
            )
            return plan
    except Exception as exc:
        logger.warning("[draft_pipeline.decompose] LLM failed: %s", exc)

    plan = _heuristic_plan(prompt_text)
    logger.info("[draft_pipeline.decompose] fallback heuristic sub_queries=%s", len(plan.sub_queries))
    return plan
