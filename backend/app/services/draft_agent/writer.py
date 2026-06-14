"""High-quality document writer (assistant-parity prose → HTML for editor)."""
from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.response_shape import case_assistant_readability_base
from app.services.draft_pipeline.markers import gap_marker, normalize_legacy_fillers
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


def _strip_html_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:html|markdown)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _max_output_tokens() -> int:
    explicit = int(getattr(config, "DRAFT_AGENT_MAX_TOKENS", 0) or 0)
    if explicit > 0:
        return explicit
    return int(getattr(config, "YANDEX_GPT_MAX_TOKENS", 8192) or 8192)


def _build_system_prompt(
    *,
    has_template: bool,
    structure_guide: bool = False,
    financial_claim: bool = False,
) -> str:
    gap = gap_marker("название поля")
    readability = case_assistant_readability_base()
    if has_template and structure_guide:
        body = f"""Ты — опытный юрист. Адаптируешь готовый HTML-шаблон под конкретное дело.

ПРАВИЛА:
1. Сохрани структуру шаблона: разделы, заголовки, порядок, таблицы.
2. Замени примерный, пустой или обобщённый текст фактами из инструкции агента.
3. Готовые нормативные формулировки шаблона — оставь, если они уместны для дела.
4. Не добавляй новые разделы и не удаляй существующие блоки шаблона.
5. Нет данных — маркер {gap}.
6. Суммы и даты — только из инструкции агента.
7. Официально-деловой стиль, русский язык.
8. Верни один цельный HTML без markdown-обёрток."""
        if financial_claim:
            body += (
                "\n9. ОБЯЗАТЕЛЬНО заполни просительную часть: взыскать долг и неустойку "
                "с конкретными суммами из верифицированного расчёта.\n"
                "10. Подставь истца и ответчика из инструкции; не оставляй [ФИО или наименование]."
            )
    elif has_template:
        body = f"""Ты — опытный юрист. Заполняешь HTML-шаблон процессуального документа.

ПРАВИЛА:
1. Сохрани структуру и порядок разделов шаблона.
2. Замени плейсхолдеры фактами из инструкции; не выдумывай.
3. Нет данных — маркер {gap}.
4. Суммы и даты — только из инструкции агента.
5. Официально-деловой стиль, русский язык.
6. Верни один цельный HTML без markdown-обёрток."""
    else:
        body = f"""Ты — опытный юрист. Составляешь полный процессуальный документ с нуля в HTML.

ПРАВИЛА:
1. Документ готов к подаче: шапка, факты, правовое обоснование (если уместно), просительная часть.
2. Только факты из инструкции; не галлюцинируй реквизиты и суммы.
3. Нет данных — маркер {gap}.
4. Официально-деловой стиль, связный текст (как сильный юридический ассистент).
5. Верни один цельный HTML (<section>, <p>, <h2>…) без markdown-обёрток."""

    return body + "\n\n" + readability


def _build_user_prompt(
    *,
    document_instruction: str,
    template_html: Optional[str],
    template_label: Optional[str],
) -> str:
    parts = [
        "ИНСТРУКЦИЯ АГЕНТА (все факты и нормы для документа):\n",
        (document_instruction or "").strip(),
    ]
    if (template_html or "").strip():
        label = (template_label or "шаблон").strip()
        parts.append(f"\n\nHTML-ШАБЛОН «{label}» (сохрани каркас, заполни содержимое):\n{template_html.strip()}")
    parts.append("\n\nВерни только HTML документа.")
    return "\n".join(parts)


def write_draft_document_html(
    *,
    document_instruction: str,
    template_html: Optional[str] = None,
    template_label: Optional[str] = None,
    structure_guide: bool = False,
    financial_claim: bool = False,
) -> str:
    """Single-pass document generation with assistant-quality instructions."""
    has_template = bool((template_html or "").strip())
    system = _build_system_prompt(
        has_template=has_template,
        structure_guide=structure_guide,
        financial_claim=financial_claim,
    )
    user = _build_user_prompt(
        document_instruction=document_instruction,
        template_html=template_html,
        template_label=template_label,
    )

    llm = create_legal_llm(max_tokens=_max_output_tokens())
    logger.info(
        "[draft_agent.writer] generating has_template=%s structure_guide=%s instruction_chars=%s",
        has_template,
        structure_guide,
        len(document_instruction or ""),
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)

    html = normalize_legacy_fillers(_strip_html_fences(str(raw)))
    if not html.strip():
        raise RuntimeError("draft writer returned empty HTML")
    return html


def complete_draft_document_html(
    *,
    draft_html: str,
    gap_report: str,
    verified_amounts_block: str,
    document_instruction: str,
    financial_claim: bool = False,
) -> str:
    """
    Second LLM pass: supplement missing sections without rewriting the full draft.
    Numbers must come only from verified_amounts_block (calculator).
    """
    gap = gap_marker("название поля")
    system = f"""Ты — опытный юрист. Получаешь черновик HTML и список пробелов.

ЗАДАЧА: дозаполнить ТОЛЬКО то, что указано в списке пробелов. Остальной текст сохрани без изменений.

ПРАВИЛА:
1. Не переписывай уже заполненные разделы (обстоятельства, правовое обоснование).
2. Все суммы — СТРОГО из блока КАЛЬКУЛЯТОР; не пересчитывай и не округляй иначе.
3. Просительную часть сформулируй юридически грамотно (пункты «взыскать…»), цифры — из калькулятора.
4. Госпошлину укажи в блоке «Цена иска», если она есть в калькуляторе.
5. Нет данных для поля — маркер {gap}.
6. Верни полный HTML документа без markdown-обёрток."""

    if financial_claim:
        system += (
            "\n7. Просительная часть обязательна: минимум взыскание долга, неустойки и госпошлины "
            "(если рассчитана) отдельными пунктами."
        )

    user_parts = [
        "СПИСОК ПРОБЕЛОВ ДЛЯ ИСПРАВЛЕНИЯ:\n",
        (gap_report or "").strip(),
        "",
        verified_amounts_block.strip() or "(калькулятор не вернул суммы)",
        "",
        "ИСХОДНАЯ ИНСТРУКЦИЯ (факты дела):\n",
        (document_instruction or "").strip()[:14000],
        "",
        "ЧЕРНОВИК HTML (сохрани заполненное, исправь пробелы):\n",
        (draft_html or "").strip(),
        "",
        "Верни полный исправленный HTML.",
    ]
    user = "\n".join(user_parts)

    llm = create_legal_llm(max_tokens=_max_output_tokens())
    logger.info(
        "[draft_agent.writer] completion pass financial_claim=%s draft_chars=%s gaps_chars=%s",
        financial_claim,
        len(draft_html or ""),
        len(gap_report or ""),
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)

    html = normalize_legacy_fillers(_strip_html_fences(str(raw)))
    if not html.strip():
        raise RuntimeError("draft completion returned empty HTML")
    return html


def resolve_template_for_draft(
    db: Session,
    *,
    template_file_id: Optional[str],
    template_file_content: Optional[str],
    user_question: str,
) -> tuple[str, Optional[str], Optional[str]]:
    from app.services.draft_template_context import resolve_draft_template_context

    text, label, template_key = resolve_draft_template_context(
        db,
        template_file_content=template_file_content,
        template_file_id=template_file_id,
        user_question=user_question,
    )
    return text or "", label, template_key


def persist_draft_document(
    db: Session,
    *,
    case_id: str,
    user_id: str,
    title: str,
    content: str,
) -> dict:
    from app.services.document_editor_service import DocumentEditorService
    from app.utils.database import ensure_db_session_live

    ensure_db_session_live(db)
    svc = DocumentEditorService(db)
    doc = svc.create_document(
        case_id=case_id,
        user_id=user_id,
        title=title[:255] if title else "Новый документ",
        content=content,
        metadata={"source": "draft_agent", "pipeline_version": "draft_hybrid_v1"},
    )
    return {
        "id": str(doc.id),
        "title": doc.title,
        "case_id": case_id,
        "preview": (content or "")[:500],
    }
