"""Per-document extraction schemas (Layer 2 — anti-contamination)."""
from __future__ import annotations

from typing import Any, Dict

EXTRACTION_SCHEMA_BY_ROLE: Dict[str, str] = {
    "contract": "ContractExtraction",
    "primary_execution_act": "ActExtraction",
    "payment_order": "PaymentExtraction",
    "pretension": "PretensionExtraction",
    "requisites": "RequisitesExtraction",
    "egrul_extract": "RequisitesExtraction",
    "charter": "RequisitesExtraction",
    "unspecified": "GenericExtraction",
}

_EXTRACTION_PROMPTS: Dict[str, str] = {
    "ContractExtraction": """Извлеки из текста ДОГОВОРА только JSON:
{{
  "contract_number": "",
  "contract_date": "YYYY-MM-DD или пусто",
  "parties": {{"поставщик/исполнитель": "", "покупатель/заказчик": ""}},
  "total_price": "",
  "payment_term_days": 0,
  "payment_term_unit": "business_days|calendar_days",
  "payment_term_from": "act_signed|contract_signed|delivery|other",
  "penalty_rate_percent_per_day": "",
  "penalty_clause_reference": ""
}}""",
    "ActExtraction": """Извлеки из текста АКТА/УПД только JSON:
{{
  "act_number": "",
  "act_date": "YYYY-MM-DD или пусто",
  "amount": "",
  "goods_description": "",
  "parties": {{"отправитель": "", "получатель": ""}}
}}""",
    "PaymentExtraction": """Извлеки из ПЛАТЁЖНОГО ДОКУМЕНТА только JSON:
{{
  "payment_date": "YYYY-MM-DD или пусто",
  "amount": "",
  "payer": "",
  "payee": "",
  "purpose": "",
  "document_number": ""
}}""",
    "PretensionExtraction": """Извлеки из ПРЕТЕНЗИИ только JSON:
{{
  "pretension_date": "YYYY-MM-DD или пусто",
  "pretension_number": "",
  "amount_claimed": "",
  "sent_to": ""
}}""",
    "RequisitesExtraction": """Извлеки РЕКВИЗИТЫ только JSON:
{{
  "parties": {{"наименование": "ИНН ОГРН адрес"}},
  "identifiers": {{"ИНН": "", "ОГРН": "", "адрес": ""}}
}}""",
    "GenericExtraction": """Извлеки ключевые факты JSON:
{{
  "parties": {{}},
  "amounts": {{}},
  "dates": {{}},
  "identifiers": {{}},
  "notes": ""
}}""",
}


def schema_name_for_role(role: str) -> str:
    return EXTRACTION_SCHEMA_BY_ROLE.get(role, "GenericExtraction")


def extraction_prompt_for_schema(schema_name: str) -> str:
    return _EXTRACTION_PROMPTS.get(schema_name, _EXTRACTION_PROMPTS["GenericExtraction"])
