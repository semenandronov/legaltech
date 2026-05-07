"""
Выбор системного шаблона документа для Draft через LLM (structured output).

Альтернатива keyword-матчингу: модель видит каталог id + title + description из manifest.json
и возвращает один id или null (LangChain: llm.with_structured_output).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.services.bankruptcy_templates import _load_manifest_raw

logger = logging.getLogger(__name__)


class DraftTemplateLLMChoice(BaseModel):
    """Ответ классификатора шаблона (строго из переданного каталога)."""

    template_id: Optional[str] = Field(
        default=None,
        description="Точный id шаблона из списка каталога; null если не подходит ни один",
    )


def _manifest_catalog_entries_for_llm() -> List[dict]:
    """Записи манифеста с id и файлом — кандидаты для выбора."""
    out: List[dict] = []
    for item in _load_manifest_raw():
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        fname = item.get("file")
        if not tid or not fname:
            continue
        out.append(
            {
                "id": str(tid),
                "title": str(item.get("title") or tid),
                "description": str(item.get("description") or ""),
            }
        )
    return out


def _catalog_entries_for_llm(db: Optional[Session] = None) -> List[dict]:
    out = list(_manifest_catalog_entries_for_llm())
    if db is not None:
        try:
            from app.services.draft_admin_template_service import list_admin_template_catalog_entries

            for e in list_admin_template_catalog_entries(db):
                out.append(
                    {
                        "id": e["id"],
                        "title": e["title"],
                        "description": e["description"],
                    }
                )
        except Exception as e:
            logger.warning("[draft_template_llm_select] admin catalog merge failed: %s", e)
    return out


def select_system_template_id_via_llm(
    user_question: str, db: Optional[Session] = None
) -> Optional[str]:
    """
    Один вызов LLM: какой системный шаблон из каталога подходит под запрос пользователя.

    Returns:
        id шаблона или None (не подошло / ошибка / пустой каталог).
    """
    q = (user_question or "").strip()
    if len(q) < 2:
        return None

    catalog = _catalog_entries_for_llm(db)
    if not catalog:
        logger.warning("[draft_template_llm_select] empty template catalog")
        return None
    if len(catalog) == 1:
        return catalog[0]["id"]

    allowed = {c["id"] for c in catalog}
    lines = []
    for c in catalog:
        desc = (c["description"] or "")[:500]
        lines.append(f"- id: `{c['id']}` | {c['title']}\n  Описание: {desc}")

    catalog_block = "\n".join(lines)

    prompt = f"""Ты маршрутизатор шаблонов юридических документов для ассистента в режиме Draft.

ДОСТУПНЫЕ ШАБЛОНЫ (выбери не больше одного; template_id должен совпадать с полем id буквально):
{catalog_block}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{q}

Правила:
- Если запрос явно относится к одному из шаблонов по типу документа — верни его template_id.
- Если формулировка расплывчатая или не ясно какой тип документа — верни template_id: null.
- Не придумывай id; только из списка выше."""

    try:
        from app.config import config
        from app.services.llm_factory import create_legal_llm

        llm = create_legal_llm(
            provider="yandex",
            model=config.YANDEX_GPT_MODEL_URI,
            use_rate_limiting=False,
            temperature=0.0,
            streaming=False,
        )
        # NOTE: Avoid `with_structured_output()` for provider-compat stability.
        # Some OpenAI-compatible backends return non-obvious 404s when JSON schema / parse
        # endpoints are used. We do plain JSON and validate with Pydantic.
        json_prompt = (
            prompt
            + "\n\nОтвет верни СТРОГО в JSON без текста вокруг.\n"
            + 'Формат: {"template_id": "<id или null>"}\n'
        )
        response = llm.invoke([HumanMessage(content=json_prompt)])
        raw = response.content if hasattr(response, "content") else str(response)
        try:
            result = DraftTemplateLLMChoice.model_validate_json(raw)
        except Exception:
            # Try to extract first JSON object.
            import re as _re
            m = _re.search(r"\{[\s\S]*\}", raw)
            if not m:
                raise
            result = DraftTemplateLLMChoice.model_validate_json(m.group(0))
        tid = (result.template_id or "").strip() if result else None
        if not tid:
            logger.info("[draft_template_llm_select] LLM returned no template for query snippet: %s", q[:80])
            return None
        if tid not in allowed:
            logger.warning(
                "[draft_template_llm_select] LLM returned invalid template_id=%s; allowed=%s",
                tid,
                allowed,
            )
            return None
        logger.info("[draft_template_llm_select] LLM selected template_id=%s", tid)
        return tid
    except Exception as e:
        logger.error("[draft_template_llm_select] LLM selection failed: %s", e, exc_info=True)
        return None
