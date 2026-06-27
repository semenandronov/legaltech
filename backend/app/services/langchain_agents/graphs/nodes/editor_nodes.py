"""
Editor Nodes - Узлы для режима редактора документа

Реализует специализированные узлы для работы с документами в редакторе:
- Анализ структуры документа
- Проверка юридических рисков
- Улучшение текста
- Генерация структурированных правок

Использует паттерны из LangGraph Academy:
- Structured outputs для гарантированного формата
- Context engineering для больших документов
- Think tool для рефлексии
- Hard limits для предотвращения бесконечных циклов
"""
from typing import Dict, Any, Optional, List, Literal
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import logging
import uuid
import json

from app.services.langchain_agents.graphs.chat_graph import ChatGraphState
from app.services.llm_factory import create_legal_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def editor_document_context_for_prompt(document_context: str) -> str:
    """Trust frontend windowing; safety cap only (default 80k chars)."""
    from app.config import config

    cap = max(1000, int(getattr(config, "EDITOR_DOCUMENT_CONTEXT_MAX_CHARS", 80_000) or 80_000))
    ctx = (document_context or "").strip()
    return ctx if len(ctx) <= cap else ctx[:cap]


def _editor_memory_section(state: ChatGraphState) -> str:
    from app.services.langchain_agents.graphs.editor_transcript import editor_memory_block_for_prompt

    return editor_memory_block_for_prompt(state)


def _append_editor_turn_message(state: ChatGraphState, content: str) -> List[Any]:
    """Запись ответа узла редактора в checkpoint (add_messages)."""
    text = (content or "").strip()
    if not text:
        return []
    return [AIMessage(content=text[:4000])]


# ============== Pydantic Models for Structured Outputs ==============

EDIT_PLAN_SYSTEM_PROMPT = """Ты — юридический редактор. Составь только ПЛАН правок (схема EditScopePlanSchema).

Каждый блок документа имеет id="UUID" в OUTLINE.

Правила плана:
- target_count = число ОТДЕЛЬНЫХ мест для изменения.
- Каждая цель в targets: location (где), change (что менять), node_id (если известен из OUTLINE).
- Одна конкретная фраза в одном месте → target_count = 1.
- Несколько разделов, «везде», «приведи в соответствие» → target_count = N.
- Если в истории диалога ассистент назвал N несоответствий или перечислил N проблем → target_count = N (не меньше).
- Если передан блок ОБЯЗАТЕЛЬНЫЕ ЦЕЛИ — включи каждую как отдельную цель, не уменьшай число.
- Выделение пользователя — подсказка, не ограничение при широком запросе или истории."""

EDIT_SINGLE_TARGET_SYSTEM_PROMPT = """Ты — юридический редактор. Сгенерируй РОВНО ОДНУ правку для указанной цели.

HTML документа и OUTLINE переданы. Верни SingleEditResponse с одним edit:
- Переписываешь блок целиком → node_id + original_text (из OUTLINE/HTML) + new_text.
- Меняешь фразу внутри блока → original_text (точная подстрока) + new_text, без node_id.
- Не выдумывай id. Только текстовые правки."""

EDIT_GENERATION_SYSTEM_PROMPT = EDIT_PLAN_SYSTEM_PROMPT


class EditTargetPlanSchema(BaseModel):
    """Одна цель правки в плане."""
    location: str = Field(..., description="Где в документе (раздел, пункт, смысл блока)")
    change: str = Field(..., description="Что именно изменить в этом месте")
    node_id: Optional[str] = Field(
        None,
        description="node_id из OUTLINE, если цель привязана к конкретному блоку",
    )


class EditScopePlanSchema(BaseModel):
    """План масштаба правки: сколько мест затронуто."""
    target_count: int = Field(..., ge=1, description="Число отдельных мест для изменения")
    targets: List[EditTargetPlanSchema] = Field(
        ...,
        min_length=1,
        description="Список целей; длина должна соответствовать target_count",
    )


class StructuredEditSchema(BaseModel):
    """Схема для одного структурированного изменения"""
    new_text: str = Field(..., description="Новый текст для замены")
    node_id: Optional[str] = Field(
        None,
        description="id блока из HTML/outline (замена целого абзаца/заголовка)",
    )
    original_text: Optional[str] = Field(
        None,
        description="Точный текст из документа (обязателен при node_id; для фразы внутри блока — без node_id)",
    )
    context_before: Optional[str] = Field(None, description="Контекст до текста (50 символов)")
    context_after: Optional[str] = Field(None, description="Контекст после текста (50 символов)")


class EditsResponse(BaseModel):
    """Legacy combined response (tests / fallbacks)."""
    scope: EditScopePlanSchema = Field(..., description="План: сколько мест и какие цели")
    edits: List[StructuredEditSchema] = Field(..., description="Список правок — по одной на каждую цель")
    reasoning: str = Field(..., description="Краткое обоснование плана и правок")


class SingleEditResponse(BaseModel):
    """Одна правка для одной цели из плана."""
    edit: StructuredEditSchema = Field(..., description="Правка для цели")
    reasoning: str = Field(default="", description="Краткое обоснование")


class DocumentAnalysisSchema(BaseModel):
    """Схема для анализа документа"""
    doc_type: str = Field(..., description="Тип документа")
    structure: Dict[str, Any] = Field(..., description="Структура документа")
    key_elements: List[str] = Field(..., description="Ключевые элементы (заголовки, клаузулы)")
    parties: Optional[List[str]] = Field(None, description="Стороны договора/документа")
    dates: Optional[List[str]] = Field(None, description="Важные даты")
    summary: Optional[str] = Field(None, description="Краткое содержание (для больших документов)")


class RiskSchema(BaseModel):
    """Схема для одного риска"""
    description: str = Field(..., description="Описание риска")
    severity: Literal["low", "medium", "high", "critical"] = Field(..., description="Критичность")
    location: Optional[str] = Field(None, description="Местоположение в документе")
    recommendation: Optional[str] = Field(None, description="Рекомендация по устранению")


class RisksResponse(BaseModel):
    """Ответ с найденными рисками"""
    risks: List[RiskSchema] = Field(..., description="Список рисков")
    overall_assessment: str = Field(..., description="Общая оценка документа")


# ============== Helper Functions ==============

def summarize_document(text: str, max_length: int = 5000) -> str:
    """
    Создать summary для большого документа (context engineering).
    
    Паттерн из Deep Research курса.
    """
    if len(text) <= max_length:
        return text
    
    logger.info(f"[ContextEngineering] Summarizing document: {len(text)} → {max_length} chars")
    
    try:
        llm = create_legal_llm(use_rate_limiting=False)
        
        summary_prompt = f"""Создай краткое содержание следующего юридического документа.
Сохрани ключевую информацию: стороны, даты, основные условия, важные клаузулы.

ДОКУМЕНТ:
{text[:10000]}  # Первые 10000 символов для контекста

КРАТКОЕ СОДЕРЖАНИЕ (максимум {max_length} символов):"""
        
        response = llm.invoke([HumanMessage(content=summary_prompt)])
        summary = response.content if hasattr(response, 'content') else str(response)
        
        return summary[:max_length]
    except Exception as e:
        logger.warning(f"[ContextEngineering] Summarization failed: {e}, using truncation")
        return text[:max_length] + "\n[... документ обрезан ...]"


def build_document_outline(html: str, max_blocks: int = 200, preview_len: int = 200) -> List[Dict[str, Any]]:
    """
    Build compact outline of blocks with data-id / id attributes for LLM targeting.
    """
    import re as _re
    import html as _html

    if not html:
        return []

    outline: List[Dict[str, Any]] = []
    pattern = _re.compile(
        r"<(p|h[1-6]|li|td|th)([^>]*\sid=[\"']([^\"']+)[\"'][^>]*)>([\s\S]*?)</\1>",
        _re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        tag = match.group(1).lower()
        node_id = match.group(3)
        inner = _re.sub(r"<[^>]+>", "", match.group(4) or "")
        inner = _html.unescape(_re.sub(r"\s+", " ", inner)).strip()
        outline.append(
            {
                "node_id": node_id,
                "type": tag,
                "text": inner[:preview_len] + ("…" if len(inner) > preview_len else ""),
            }
        )
        if len(outline) >= max_blocks:
            break
    return outline


def _node_id_in_document(node_id: str, document_html: str) -> bool:
    if not node_id or not document_html:
        return False
    needle = f'id="{node_id}"'
    if needle in document_html:
        return True
    return f"id='{node_id}'" in document_html


def _extract_block_text_by_node_id(document_html: str, node_id: str) -> Optional[str]:
    """Plain-text content of a block with id=node_id (for fallback / server-side enrichment)."""
    import re as _re
    import html as _html

    if not node_id or not document_html:
        return None
    pattern = _re.compile(
        rf'<(p|h[1-6]|li|td|th)([^>]*\sid=["\']{_re.escape(node_id)}["\'][^>]*)>([\s\S]*?)</\1>',
        _re.IGNORECASE,
    )
    match = pattern.search(document_html)
    if not match:
        return None
    inner = _re.sub(r"<[^>]+>", "", match.group(3) or "")
    return _html.unescape(_re.sub(r"\s+", " ", inner)).strip() or None


def _enrich_block_edit(
    *,
    node_id: str,
    original_text: Optional[str],
    new_text: str,
    document_context: str,
) -> Dict[str, Any]:
    """Ensure block-level edits carry original_text and found_in_document flags."""
    resolved_original = (original_text or "").strip()
    if not resolved_original:
        resolved_original = _extract_block_text_by_node_id(document_context, node_id) or ""
    found_id = _node_id_in_document(node_id, document_context)
    return {
        "id": f"edit-{uuid.uuid4().hex[:8]}",
        "node_id": node_id,
        "original_text": resolved_original or None,
        "new_text": new_text,
        "context_before": "",
        "context_after": "",
        "found_in_document": found_id,
    }


def _scope_plan_to_dict(scope: Any) -> Dict[str, Any]:
    """Serialize scope from Pydantic model or dict."""
    if scope is None:
        return {"target_count": 0, "targets": []}
    if hasattr(scope, "model_dump"):
        return scope.model_dump()
    if isinstance(scope, dict):
        return scope
    return {"target_count": 0, "targets": []}


def _expand_llm_edits_to_raw(
    edits_list: List[Any],
    document_context: str,
) -> List[Dict[str, Any]]:
    """Turn LLM edit proposals into client-ready structured_edits (with occurrence expansion)."""
    raw_edits: List[Dict[str, Any]] = []

    for edit in edits_list:
        original_text = edit.original_text if hasattr(edit, "original_text") else edit.get("original_text", "")
        node_id = edit.node_id if hasattr(edit, "node_id") else edit.get("node_id")
        new_text = edit.new_text if hasattr(edit, "new_text") else edit.get("new_text", "")

        if not original_text and not node_id:
            continue

        if node_id:
            enriched = _enrich_block_edit(
                node_id=node_id,
                original_text=original_text,
                new_text=new_text,
                document_context=document_context,
            )
            if not enriched["found_in_document"]:
                logger.warning("[GenerateEdits] node_id not found: %s", node_id)
            raw_edits.append(enriched)
            continue

        occurrences: List[int] = []
        search_from = 0
        while original_text:
            idx = document_context.find(original_text, search_from)
            if idx == -1:
                break
            occurrences.append(idx)
            search_from = idx + len(original_text)

        if not occurrences:
            raw_edits.append({
                "id": f"edit-{uuid.uuid4().hex[:8]}",
                "original_text": original_text,
                "node_id": node_id,
                "new_text": new_text,
                "context_before": "",
                "context_after": "",
                "found_in_document": False,
            })
            logger.warning(
                "[GenerateEdits] Edit text not found: '%s…'",
                (original_text or "")[:100],
            )
        else:
            for pos in occurrences:
                ctx_before = document_context[max(0, pos - 50):pos]
                ctx_after = document_context[
                    pos + len(original_text):pos + len(original_text) + 50
                ]
                raw_edits.append({
                    "id": f"edit-{uuid.uuid4().hex[:8]}",
                    "original_text": original_text,
                    "node_id": node_id,
                    "new_text": new_text,
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                    "found_in_document": True,
                })
            logger.info(
                "[GenerateEdits] '%s…' → '%s…' (%d вхождений)",
                original_text[:50],
                new_text[:50],
                len(occurrences),
            )

    return raw_edits


def _build_edits_user_prompt(
    *,
    question: str,
    memory_block: str,
    outline_json: str,
    doc_text: str,
    selected_text: str,
    correction_hint: str = "",
    pending_targets_block: str = "",
) -> str:
    selection_block = ""
    if selected_text:
        selection_block = (
            "\nВЫДЕЛЕНИЕ ПОЛЬЗОВАТЕЛЯ (подсказка фокуса; не ограничивай план, если запрос или история шире):\n"
            f"{selected_text}\n"
        )
    correction_block = f"\n{correction_hint}\n" if correction_hint else ""
    pending_block = f"\n{pending_targets_block}\n" if pending_targets_block else ""

    return f"""ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{question}
{memory_block}{selection_block}{pending_block}{correction_block}
OUTLINE (блоки с node_id — единственный источник допустимых id):
{outline_json}

ДОКУМЕНТ (HTML, атрибут id на блоках):
{doc_text}

Напоминание:
- Верни только scope (план целей): target_count и targets.
- Одинаковая фраза в нескольких местах — отдельная цель на каждое вхождение.
- Если в запросе «вставь его/это» — возьми значение из истории диалога."""


def _build_single_target_user_prompt(
    *,
    question: str,
    memory_block: str,
    outline_json: str,
    doc_text: str,
    target: Dict[str, Any],
    target_index: int,
    target_total: int,
) -> str:
    location = (target.get("location") or "").strip()
    change = (target.get("change") or "").strip()
    node_id = target.get("node_id")
    node_hint = f"\nnode_id из плана: {node_id}" if node_id else ""

    return f"""ЗАПРОС ПОЛЬЗОВАТЕЛЯ (общий контекст):
{question}
{memory_block}
ЦЕЛЬ {target_index} из {target_total}:
- Где: {location}
- Что изменить: {change}{node_hint}

OUTLINE:
{outline_json}

ДОКУМЕНТ (HTML):
{doc_text}

Верни ровно одну правку (edit) для этой цели."""


def extract_context(document: str, text: str, context_size: int = 50) -> tuple[str, str]:
    """
    Извлечь контекст до и после текста в документе.
    
    Args:
        document: Полный текст документа
        text: Текст для поиска
        context_size: Размер контекста в символах
        
    Returns:
        (context_before, context_after)
    """
    find_pos = document.find(text)
    if find_pos == -1:
        return "", ""
    
    # Контекст до
    start_ctx = max(0, find_pos - context_size)
    context_before = document[start_ctx:find_pos]
    if start_ctx > 0:
        # Начинаем с начала слова
        space_pos = context_before.find(' ')
        if space_pos != -1:
            context_before = context_before[space_pos + 1:]
    
    # Контекст после
    end_pos = find_pos + len(text)
    end_ctx = min(len(document), end_pos + context_size)
    context_after = document[end_pos:end_ctx]
    if end_ctx < len(document):
        # Заканчиваем на конце слова
        space_pos = context_after.rfind(' ')
        if space_pos != -1:
            context_after = context_after[:space_pos]
    
    return context_before, context_after


# ============== Node Functions ==============

def analyze_document_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Анализирует структуру и содержимое документа.
    
    Использует:
    - Context engineering: summarization для больших документов (>5000 символов)
    - Structured outputs: гарантированный формат анализа
    
    Паттерны из курсов:
    - Context engineering (Deep Research): summarization для больших документов
    - Structured outputs (Ambient Agents): для структурированного анализа
    
    Сохраняет результаты в state.document_analysis.
    """
    document_context = state.get("document_context", "")
    
    if not document_context:
        logger.warning("[AnalyzeDocument] No document_context in state")
        return {"document_analysis": None}
    
    logger.info(f"[AnalyzeDocument] Analyzing document: {len(document_context)} chars")
    
    new_state = dict(state)
    
    try:
        # Context engineering: summarization для больших документов
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            analysis_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT_LENGTH: {len(document_context)} chars"
        else:
            analysis_text = document_context
        
        # Structured output для анализа
        llm = create_legal_llm(use_rate_limiting=False)
        
        analysis_prompt = f"""Проанализируй структуру и содержимое следующего юридического документа.

ДОКУМЕНТ:
{analysis_text}

Определи:
1. Тип документа (договор, заявление, иск, и т.д.)
2. Структуру (разделы, подразделы, пункты)
3. Ключевые элементы (заголовки, клаузулы, условия)
4. Стороны (если есть)
5. Важные даты (если есть)

Ответь в формате JSON согласно схеме DocumentAnalysisSchema."""
        
        # Используем structured output
        try:
            structured_llm = llm.with_structured_output(DocumentAnalysisSchema)
            analysis = structured_llm.invoke([HumanMessage(content=analysis_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[AnalyzeDocument] Structured output failed: {e}, using fallback")
            # Fallback: обычный вызов и парсинг
            response = llm.invoke([HumanMessage(content=analysis_prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Простой fallback
            analysis = DocumentAnalysisSchema(
                doc_type="Неизвестный",
                structure={},
                key_elements=[],
                parties=None,
                dates=None,
                summary=response_text[:500] if len(response_text) > 500 else response_text
            )
        
        new_state["document_analysis"] = analysis.model_dump() if hasattr(analysis, 'model_dump') else analysis
        logger.info(f"[AnalyzeDocument] Analysis completed: type={analysis.doc_type if hasattr(analysis, 'doc_type') else 'unknown'}")
        
    except Exception as e:
        logger.error(f"[AnalyzeDocument] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Analysis error: {str(e)}"]
        new_state["document_analysis"] = None
    
    return new_state


def think_tool(
    reflection: str,
    state: ChatGraphState = None
) -> str:
    """
    Think tool для рефлексии между шагами.
    
    Паттерн из Deep Research курса: interleaved thinking между шагами.
    
    Args:
        reflection: Текст рефлексии
        state: Состояние графа (опционально, для записи в state)
        
    Returns:
        Подтверждение записи рефлексии
    """
    logger.debug(f"[ThinkTool] Reflection: {reflection[:100]}...")
    
    # Записываем reflection в state.thinking_steps если доступен
    if state is not None:
        thinking_steps = state.get("thinking_steps", [])
        if not isinstance(thinking_steps, list):
            thinking_steps = []
        
        thinking_steps.append({
            "type": "reflection",
            "content": reflection,
            "step_number": len(thinking_steps) + 1
        })
        
        # Обновляем state (но это no-op tool, поэтому не возвращаем state)
        # State будет обновлён через другой механизм если нужно
    
    return f"Reflection recorded: {reflection[:50]}..."


def check_risks_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Проверяет документ на юридические риски.
    
    Использует:
    - Think tool для рефлексии между проверками
    - Hard limits: максимум 3 итерации проверки
    
    Паттерны из курсов:
    - Think tool (Deep Research): для рефлексии
    - Hard limits (Deep Research): ограничение количества проверок
    
    Сохраняет результаты в state.risks.
    """
    document_context = state.get("document_context", "")
    
    if not document_context:
        logger.warning("[CheckRisks] No document_context in state")
        return {"risks": []}
    
    # Hard limit для предотвращения spin-out
    MAX_RISK_CHECKS = 3
    iteration = state.get("risk_check_iteration", 0)
    
    if iteration >= MAX_RISK_CHECKS:
        logger.warning(f"[CheckRisks] Max iterations ({MAX_RISK_CHECKS}) reached")
        return {"risks": state.get("risks", [])}
    
    logger.info(f"[CheckRisks] Checking risks (iteration {iteration + 1}/{MAX_RISK_CHECKS})")
    
    new_state = dict(state)
    
    try:
        # Context engineering: summarization для больших документов
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            analysis_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT_LENGTH: {len(document_context)} chars"
        else:
            analysis_text = document_context
        
        # Используем think tool для рефлексии перед проверкой
        if iteration > 0:
            previous_risks = state.get("risks", [])
            reflection = f"Проверка {iteration + 1}. Предыдущие проверки нашли {len(previous_risks)} рисков. Нужно проверить документ более глубоко."
            think_tool(reflection, state)
        
        # Structured output для рисков
        llm = create_legal_llm(use_rate_limiting=False)
        
        risks_prompt = f"""Проверь следующий юридический документ на наличие юридических рисков.

ДОКУМЕНТ:
{analysis_text}

Ищи:
1. Неоднозначные формулировки
2. Отсутствующие обязательные элементы
3. Потенциальные проблемы с исполнением
4. Риски для сторон

Ответь в формате JSON согласно схеме RisksResponse."""
        
        try:
            structured_llm = llm.with_structured_output(RisksResponse)
            risks_response = structured_llm.invoke([HumanMessage(content=risks_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[CheckRisks] Structured output failed: {e}, using fallback")
            # Fallback
            response = llm.invoke([HumanMessage(content=risks_prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Простой fallback
            risks_response = RisksResponse(
                risks=[],
                overall_assessment=response_text[:200] if len(response_text) > 200 else response_text
            )
        
        risks_list = risks_response.risks if hasattr(risks_response, 'risks') else []
        risks_data = [r.model_dump() if hasattr(r, 'model_dump') else r for r in risks_list]
        
        new_state["risks"] = risks_data
        new_state["risk_check_iteration"] = iteration + 1
        
        logger.info(f"[CheckRisks] Found {len(risks_data)} risks")
        
    except Exception as e:
        logger.error(f"[CheckRisks] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Risks check error: {str(e)}"]
        new_state["risks"] = []
    
    return new_state


def improve_text_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Улучшает текст документа.
    
    Использует:
    - Context engineering: работа с selected_text vs document_context
    - Приоритет selected_text над document_context
    
    Паттерны из курсов:
    - Context engineering (Deep Research): работа с selected_text vs document_context
    
    Сохраняет улучшенный текст в state.improved_text.
    """
    # Приоритет selected_text над document_context
    selected_text = state.get("selected_text")
    document_context = state.get("document_context", "")
    
    text_to_improve = selected_text or document_context
    
    if not text_to_improve:
        logger.warning("[ImproveText] No text to improve")
        return {"improved_text": None}
    
    logger.info(f"[ImproveText] Improving text: {len(text_to_improve)} chars (selected: {bool(selected_text)})")
    
    new_state = dict(state)
    
    try:
        # Context engineering: если текст большой, используем summarization
        if len(text_to_improve) > 2000:
            context_summary = summarize_document(text_to_improve, max_length=2000)
            improvement_text = f"TEXT_TO_IMPROVE:\n{text_to_improve}\n\nCONTEXT_SUMMARY:\n{context_summary}"
        else:
            improvement_text = text_to_improve
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        improve_prompt = f"""Улучши следующий текст юридического документа:
- Сделай формулировки более точными и профессиональными
- Упрости сложные предложения
- Сохрани смысл и юридическую точность

ТЕКСТ:
{improvement_text}

УЛУЧШЕННЫЙ ТЕКСТ:"""
        
        response = llm.invoke([HumanMessage(content=improve_prompt)])
        improved_text = response.content if hasattr(response, 'content') else str(response)
        
        new_state["improved_text"] = improved_text
        logger.info(f"[ImproveText] Text improved: {len(improved_text)} chars")
        
    except Exception as e:
        logger.error(f"[ImproveText] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Improve text error: {str(e)}"]
        new_state["improved_text"] = None
    
    return new_state


def editor_enrich_case_context_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None,
    rag_service=None,
) -> ChatGraphState:
    """
    Prefetch case RAG for editor subgraph (ask / edit / draft in document editor).
    Использует тот же pipeline, что и внутренний ассистент: router → hybrid → rerank.
    """
    from app.services.langchain_agents.graphs.editor_edit_pipeline import editor_needs_case_context
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "editor_enrich_context") as tr:
        case_id = state.get("case_id")
        question = (state.get("question") or "").strip()
        if not case_id or not question:
            out: Dict[str, Any] = {}
            if tr:
                tr.set_output(out)
            return out

        attached = state.get("attached_file_ids") or []
        if not editor_needs_case_context(
            question,
            editor_mode_hint=state.get("editor_mode_hint"),
            attached_file_ids=attached,
            selected_text=state.get("selected_text"),
        ):
            logger.info(
                "[EditorEnrich] case_id=%s skip RAG — local edit without case-material signals",
                case_id,
            )
            out = {"context_pipeline_meta": {"pipeline": "editor_skip", "scope_mode": "local_edit"}}
            if tr:
                tr.set_output({"skipped_rag": True, "reason": "local_edit"})
            return out

        rag = rag_service
        if rag is None and config:
            rag = (config or {}).get("rag_service")
        if rag is None:
            from app.services.rag_service import RAGService
            rag = RAGService()

        try:
            from app.config import config as app_config

            attached = state.get("attached_file_ids") or []
            attached_ctx = (state.get("attached_case_files_context") or "").strip()
            if (
                attached
                and attached_ctx
                and getattr(app_config, "EDITOR_ATTACH_FULL_TEXT_ENABLED", True)
            ):
                logger.info(
                    "[EditorEnrich] case_id=%s skip RAG — %s attached file(s) use full structured_text",
                    case_id,
                    len(attached),
                )
                out = {"attached_case_files_context": attached_ctx}
                if tr:
                    tr.set_output({"skipped_rag": True, "attached_count": len(attached)})
                return out

            from app.services.chat.case_context_pipeline import run_case_context_pipeline

            budget_profile = state.get("budget_profile")
            pipeline_out = run_case_context_pipeline(
                rag_service=rag,
                case_id=str(case_id),
                question=question,
                db=db,
                attached_file_ids=attached,
                document_id=state.get("document_id"),
                corpus_size=int(state.get("corpus_size") or 0),
                budget_profile=budget_profile if isinstance(budget_profile, dict) else None,
                retrieval_task=state.get("retrieval_task")
                if isinstance(state.get("retrieval_task"), dict)
                else None,
                editor_case_files_only=True,
            )
            if not pipeline_out:
                logger.info("[EditorEnrich] case_id=%s no case context", case_id)
                out = {}
                if tr:
                    tr.set_output(out)
                return out

            meta = pipeline_out.get("context_pipeline_meta") or {}
            logger.info(
                "[EditorEnrich] case_id=%s pipeline=%s recall=%s rerank=%s scope=%s files=%s",
                case_id,
                meta.get("pipeline"),
                meta.get("recall_docs"),
                meta.get("rerank_docs"),
                meta.get("scope_mode"),
                meta.get("scoped_files_count"),
            )
            out = {
                k: pipeline_out[k]
                for k in (
                    "rag_context",
                    "rag_documents",
                    "citations",
                    "context_pipeline_meta",
                    "retrieval_task",
                    "scoped_file_ids",
                    "scoped_doc_type",
                )
                if k in pipeline_out
            }
            if tr:
                tr.set_output(out)
            return out
        except Exception as e:
            logger.warning("[EditorEnrich] RAG failed: %s", e, exc_info=True)
            out = {}
            if tr:
                tr.set_output(out)
            return out


def generate_editor_snippet_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None,
) -> ChatGraphState:
    """
    Draft mode for in-editor cursor insert: return plain-text snippet only (not full document).
    Distinct from global draft_mode / generate_draft_plan HITL flow.
    """
    question = state.get("question", "")
    document_context = state.get("document_context", "") or ""
    rag_context = state.get("rag_context", "") or ""

    logger.info("[GenerateEditorSnippet] question=%r", (question or "")[:80])

    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "generate_editor_snippet") as tr:
        try:
            llm = create_legal_llm(use_rate_limiting=False)
            memory_section = _editor_memory_section(state)
            system_prompt = (
                "Ты — AI-ассистент для юридических документов. Сейчас ты работаешь в режиме Draft.\n"
                "Пользователь поставил курсор в нужное место документа и просит создать текст для вставки.\n\n"
                "ПРАВИЛА:\n"
                "- Верни ТОЛЬКО текст нового фрагмента — без вступлений, без пояснений, без markdown.\n"
                "- Пиши профессионально, в стиле юридического документа на русском языке.\n"
                "- Не добавляй HTML-теги, если только пользователь явно не просит форматирование.\n"
                "- Не начинай ответ со слов «Конечно», «Вот», «Я напишу» и т.п.\n"
                "- Первое слово ответа — уже текст для вставки.\n"
                "- Учитывай историю диалога: «его/это/как выше» — факты из прошлых ответов ассистента."
            )
            doc_section = (
                f"\n\n=== КОНТЕКСТ ДОКУМЕНТА ===\n"
                f"{editor_document_context_for_prompt(document_context)}\n=== КОНЕЦ ==="
                if document_context
                else ""
            )
            case_section = (
                f"\n\n=== КОНТЕКСТ ИЗ ДРУГИХ ДОКУМЕНТОВ ДЕЛА ===\n{rag_context}\n=== КОНЕЦ ==="
                if rag_context
                else ""
            )
            memory_block = f"\n\n{memory_section}\n" if memory_section else ""
            user_prompt = f"ЗАПРОС: {question}{memory_block}{doc_section}{case_section}\n\nСгенерируй текст для вставки."

            response = llm.invoke([HumanMessage(content=system_prompt + "\n\n" + user_prompt)])
            snippet = response.content if hasattr(response, "content") else str(response)
            import re as _re
            snippet = _re.sub(r"```[\s\S]*?```", "", snippet, flags=_re.DOTALL).strip()

            out: Dict[str, Any] = {"response": snippet, "structured_edits": []}
            msgs = _append_editor_turn_message(state, snippet)
            if msgs:
                out["messages"] = msgs
            if tr:
                tr.set_output(out)
            return out
        except Exception as e:
            logger.error("[GenerateEditorSnippet] Error: %s", e, exc_info=True)
            out = {
                "response": "Не удалось сгенерировать текст. Попробуйте переформулировать запрос.",
                "structured_edits": [],
                "errors": (state.get("errors") or []) + [f"Editor snippet error: {str(e)}"],
            }
            if tr:
                tr.set_output(out)
            return out


def _plan_edit_scope(
    *,
    llm,
    question: str,
    memory_block: str,
    outline_json: str,
    doc_text: str,
    selected_text: str,
    pending_targets_block: str,
    correction_hint: str,
) -> Dict[str, Any]:
    """LLM plan step — scope only."""
    structured_llm = llm.with_structured_output(EditScopePlanSchema)
    user_prompt = _build_edits_user_prompt(
        question=question,
        memory_block=memory_block,
        outline_json=outline_json,
        doc_text=doc_text,
        selected_text=selected_text,
        correction_hint=correction_hint,
        pending_targets_block=pending_targets_block,
    )
    try:
        plan = structured_llm.invoke([
            SystemMessage(content=EDIT_PLAN_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        if hasattr(plan, "model_dump"):
            data = plan.model_dump()
            return {"target_count": data.get("target_count", 0), "targets": data.get("targets") or []}
        return _scope_plan_to_dict(plan)
    except (AttributeError, Exception) as e:
        logger.warning("[GenerateEdits] Plan structured output failed: %s", e)
        return {"target_count": 0, "targets": []}


def _execute_edit_for_target(
    *,
    llm,
    question: str,
    memory_block: str,
    outline_json: str,
    doc_text: str,
    target: Dict[str, Any],
    target_index: int,
    target_total: int,
) -> Optional[Any]:
    """LLM execute step — one edit per plan target."""
    structured_llm = llm.with_structured_output(SingleEditResponse)
    user_prompt = _build_single_target_user_prompt(
        question=question,
        memory_block=memory_block,
        outline_json=outline_json,
        doc_text=doc_text,
        target=target,
        target_index=target_index,
        target_total=target_total,
    )
    try:
        return structured_llm.invoke([
            SystemMessage(content=EDIT_SINGLE_TARGET_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
    except (AttributeError, Exception) as e:
        logger.warning(
            "[GenerateEdits] Single edit failed target %d/%d: %s",
            target_index,
            target_total,
            e,
        )
        return None


def generate_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Генерирует structured_edits: план → по одной правке на цель → fail-closed.
    """
    question = state.get("question", "")
    document_context = state.get("document_context", "")
    selected_text = (state.get("selected_text") or "").strip()

    if not document_context:
        logger.warning("[GenerateEdits] No document_context in state")
        return {"structured_edits": []}

    logger.info("[GenerateEdits] Generating edits for: %s...", question[:100])

    from app.services.langchain_agents.graphs.editor_edit_handoff import (
        format_minimum_targets_hint,
        format_pending_targets_block,
        merge_pending_into_scope,
        resolve_minimum_target_count,
        scope_meets_minimum,
    )
    from app.services.langchain_agents.graphs.editor_edit_pipeline import (
        MAX_EDIT_PLAN_ATTEMPTS,
        MAX_EDIT_TARGETS_PER_TURN,
        build_generate_edits_document_section,
        check_edit_plan_completeness,
        format_incomplete_edit_failure_message,
        format_edit_turn_response,
        requires_broad_document_context,
    )
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    new_state = dict(state)

    with editor_node_trace(state, "generate_edits") as tr:
        try:
            outline = build_document_outline(document_context)
            memory_section = _editor_memory_section(state)
            memory_block = f"\n{memory_section}\n" if memory_section else ""
            has_history = "ИСТОРИЯ ДИАЛОГА" in memory_section
            broad_context = requires_broad_document_context(
                question,
                has_dialogue_history=has_history,
            )

            doc_text = build_generate_edits_document_section(
                document_context,
                question,
                outline=outline,
                broad_context=broad_context,
                extra_search_text=memory_section if broad_context else "",
            )

            llm = create_legal_llm(use_rate_limiting=False)
            outline_json = json.dumps(outline, ensure_ascii=False, indent=2) if outline else "[]"

            pending_targets = list(state.get("pending_edit_targets") or [])
            minimum_targets = resolve_minimum_target_count(state, question)
            pending_block = format_pending_targets_block(pending_targets)

            edit_scope: Dict[str, Any] = {"target_count": 0, "targets": []}
            correction_hint = ""
            if minimum_targets:
                correction_hint = format_minimum_targets_hint(minimum_targets)

            for attempt in range(1, MAX_EDIT_PLAN_ATTEMPTS + 1):
                planned = _plan_edit_scope(
                    llm=llm,
                    question=question,
                    memory_block=memory_block,
                    outline_json=outline_json,
                    doc_text=doc_text,
                    selected_text=selected_text,
                    pending_targets_block=pending_block,
                    correction_hint=correction_hint,
                )
                edit_scope = planned

                if pending_targets and not scope_meets_minimum(planned, len(pending_targets)):
                    edit_scope = merge_pending_into_scope(planned, pending_targets)
                    logger.info(
                        "[GenerateEdits] Adopted pending_edit_targets as scope (%d targets)",
                        len(edit_scope.get("targets") or []),
                    )

                targets = edit_scope.get("targets") or []
                if targets and scope_meets_minimum(edit_scope, minimum_targets):
                    break

                if attempt >= MAX_EDIT_PLAN_ATTEMPTS:
                    if pending_targets:
                        edit_scope = merge_pending_into_scope(edit_scope, pending_targets)
                    break

                hint_parts = []
                if minimum_targets:
                    hint_parts.append(format_minimum_targets_hint(minimum_targets))
                if not targets:
                    hint_parts.append("План пуст — добавь scope.targets.")
                else:
                    hint_parts.append(
                        f"В плане {len(targets)} целей, требуется минимум {minimum_targets or 1}."
                    )
                correction_hint = "\n".join(hint_parts)

            scope_targets = [
                t for t in (edit_scope.get("targets") or []) if isinstance(t, dict)
            ][:MAX_EDIT_TARGETS_PER_TURN]
            if not scope_targets:
                failure = format_incomplete_edit_failure_message(
                    check_edit_plan_completeness(edit_scope, []),
                    minimum_targets=minimum_targets,
                )
                new_state["structured_edits"] = []
                new_state["edit_scope"] = edit_scope
                new_state["response"] = failure
                turn_msgs = _append_editor_turn_message(state, failure)
                if turn_msgs:
                    new_state["messages"] = turn_msgs
                if tr:
                    tr.set_output(new_state)
                return new_state

            edit_scope["targets"] = scope_targets
            edit_scope["target_count"] = len(scope_targets)

            raw_edits: List[Dict[str, Any]] = []
            for idx, target in enumerate(scope_targets, start=1):
                single = _execute_edit_for_target(
                    llm=llm,
                    question=question,
                    memory_block=memory_block,
                    outline_json=outline_json,
                    doc_text=doc_text,
                    target=target,
                    target_index=idx,
                    target_total=len(scope_targets),
                )
                if single is None:
                    continue
                edit_obj = single.edit if hasattr(single, "edit") else None
                if edit_obj is None:
                    continue
                raw_edits.extend(
                    _expand_llm_edits_to_raw([edit_obj], document_context)
                )

            completeness = check_edit_plan_completeness(edit_scope, raw_edits)
            logger.info(
                "[GenerateEdits] scope_targets=%d edits=%d complete=%s min=%s",
                completeness.expected_targets,
                completeness.actual_edits,
                completeness.is_complete,
                minimum_targets,
            )

            if not completeness.is_complete:
                failure = format_incomplete_edit_failure_message(
                    completeness,
                    minimum_targets=minimum_targets,
                )
                new_state["structured_edits"] = []
                new_state["edit_scope"] = edit_scope
                new_state["response"] = failure
                turn_msgs = _append_editor_turn_message(state, failure)
                if turn_msgs:
                    new_state["messages"] = turn_msgs
                if tr:
                    tr.set_output(new_state)
                return new_state

            new_state["structured_edits"] = raw_edits
            new_state["edit_scope"] = edit_scope
            new_state["pending_edit_targets"] = None
            logger.info(
                "[GenerateEdits] Generated %d edits (scope targets=%d)",
                len(raw_edits),
                len(scope_targets),
            )

            summary = format_edit_turn_response(raw_edits)
            turn_msgs = _append_editor_turn_message(state, summary)
            if turn_msgs:
                new_state["messages"] = turn_msgs
            new_state["response"] = summary
            if tr:
                tr.set_output(new_state)
            return new_state
        except Exception as e:
            logger.error("[GenerateEdits] Error: %s", e, exc_info=True)
            new_state["errors"] = (new_state.get("errors") or []) + [
                f"Generate edits error: {str(e)}"
            ]
            new_state["structured_edits"] = []
            if tr:
                tr.set_output(new_state)
            return new_state



def validate_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Детерминированная валидация structured_edits перед показом в UI.

    Без LLM: проверяем node_id / original_text в HTML, обогащаем found_in_document.
    Граф не возвращается к generate_edits. Неполный план → fail-closed (пустой список правок).
    """
    from app.services.langchain_agents.graphs.editor_edit_pipeline import (
        validate_structured_edits_deterministic,
    )
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "validate_edits") as tr:
        structured_edits = state.get("structured_edits", [])
        document_context = state.get("document_context", "")

        if not structured_edits:
            logger.info("[ValidateEdits] No structured_edits to validate")
            out = {"edits_valid": True, "structured_edits": []}
            if tr:
                tr.set_output(out)
            return out

        result = validate_structured_edits_deterministic(
            structured_edits,
            document_context,
            node_id_in_document=_node_id_in_document,
            extract_block_text_by_node_id=_extract_block_text_by_node_id,
            edit_scope=state.get("edit_scope"),
        )

        logger.info(
            "[ValidateEdits] Deterministic validation: valid=%s edits=%s warnings=%s",
            result.is_valid,
            len(result.enriched_edits),
            len(result.warnings),
        )

        out = {
            "structured_edits": result.enriched_edits if result.is_valid else [],
            "edits_valid": result.is_valid,
            "edit_errors": result.errors,
            "edit_warnings": result.warnings,
        }
        if tr:
            tr.set_output(out)
        return out


def apply_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Финализация edit-turn: короткий ответ в чат, без мутации HTML на сервере.

    Правки применяет клиент (TipTap) по structured_edits / node_id.
    """
    from app.config import config as app_config
    from app.services.langchain_agents.graphs.editor_edit_pipeline import format_edit_turn_response
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "apply_edits") as tr:
        import re as _re_apply

        work_state = dict(state)
        question = (work_state.get("question") or "").lower()

        if work_state.get("waiting_for_edits_approval") and _re_apply.search(
            r"\b(одобр|подтвержда|согласен)\b",
            question,
        ):
            work_state["edits_approved"] = True
            work_state["waiting_for_edits_approval"] = False

        structured_edits = work_state.get("structured_edits", [])
        user_id = work_state.get("user_id", "")

        if not structured_edits:
            logger.info("[ApplyEdits] No structured_edits — nothing to finalize")
            prior = (work_state.get("response") or "").strip()
            response = prior if prior else format_edit_turn_response([])
            out = {
                "response": response,
                "messages": [AIMessage(content=response)],
            }
            if tr:
                tr.set_output(out)
            return out

        max_auto_apply = max(
            1,
            int(getattr(app_config, "EDITOR_MASS_EDIT_APPROVAL_THRESHOLD", 10) or 10),
        )
        edits_approved = bool(work_state.get("edits_approved", False))
        if len(structured_edits) > max_auto_apply and not edits_approved:
            response = format_edit_turn_response(
                structured_edits,
                waiting_for_approval=True,
                approval_count=len(structured_edits),
            )
            new_state = dict(work_state)
            new_state["waiting_for_edits_approval"] = True
            new_state["response"] = response
            new_state["messages"] = [AIMessage(content=response)]
            if tr:
                tr.set_output(new_state)
            return new_state

        response = format_edit_turn_response(structured_edits)
        prior = (work_state.get("response") or "").strip()
        if prior and len(structured_edits) == 1 and "Предлагаю" not in prior:
            response = prior

        new_state = dict(work_state)
        new_state["waiting_for_edits_approval"] = False
        new_state["response"] = response
        new_state["messages"] = [AIMessage(content=response)]

        store = config.get("store") if config else None
        if store and user_id:
            try:
                from datetime import datetime

                preferences = {
                    "last_edit_type": "structured_edit_proposal",
                    "edits_count": len(structured_edits),
                    "found_in_document_count": sum(
                        1 for e in structured_edits if e.get("found_in_document")
                    ),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                if hasattr(store, "put"):
                    store.put(("editor_preferences", user_id), "preferences", preferences)
            except Exception as store_e:
                logger.debug("[ApplyEdits] Store preferences skipped: %s", store_e)

        logger.info(
            "[ApplyEdits] Finalized %s edit proposal(s) for client apply",
            len(structured_edits),
        )
        if tr:
            tr.set_output(new_state)
        return new_state


# ============== Parallel Checks Nodes ==============

class GrammarCheckResult(BaseModel):
    """Результат проверки грамматики"""
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Найденные ошибки")
    suggestions: List[str] = Field(default_factory=list, description="Предложения по улучшению")


class LegalCheckResult(BaseModel):
    """Результат проверки юридической точности"""
    issues: List[Dict[str, Any]] = Field(default_factory=list, description="Найденные проблемы")
    recommendations: List[str] = Field(default_factory=list, description="Рекомендации")


class ComplianceCheckResult(BaseModel):
    """Результат проверки соответствия стандартам"""
    violations: List[Dict[str, Any]] = Field(default_factory=list, description="Нарушения")
    fixes: List[str] = Field(default_factory=list, description="Исправления")


def check_grammar_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Проверка грамматики и орфографии.
    
    Использует context engineering для больших документов.
    """
    document_context = state.get("document_context", "")
    selected_text = state.get("selected_text")
    
    text_to_check = selected_text or document_context
    
    if not text_to_check:
        return {"grammar_check": None}
    
    logger.info(f"[CheckGrammar] Checking grammar: {len(text_to_check)} chars")
    
    new_state = dict(state)
    
    try:
        # Context engineering
        if len(text_to_check) > 2000:
            summary = summarize_document(text_to_check, max_length=2000)
            check_text = f"SUMMARY:\n{summary}\n\nFULL_TEXT:\n{text_to_check}"
        else:
            check_text = text_to_check
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        grammar_prompt = f"""Проверь следующий текст на грамматические и орфографические ошибки.

ТЕКСТ:
{check_text}

Найди и исправь:
1. Орфографические ошибки
2. Грамматические ошибки
3. Пунктуационные ошибки

Ответь в формате JSON согласно схеме GrammarCheckResult."""
        
        try:
            structured_llm = llm.with_structured_output(GrammarCheckResult)
            result = structured_llm.invoke([HumanMessage(content=grammar_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[CheckGrammar] Structured output failed: {e}")
            result = GrammarCheckResult(errors=[], suggestions=[])
        
        new_state["grammar_check"] = result.model_dump() if hasattr(result, 'model_dump') else result
        logger.info(f"[CheckGrammar] Found {len(result.errors) if hasattr(result, 'errors') else 0} errors")
        
    except Exception as e:
        logger.error(f"[CheckGrammar] Error: {e}", exc_info=True)
        new_state["grammar_check"] = None
    
    return new_state


def check_legal_accuracy_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Проверка юридической точности.
    
    Использует context engineering для больших документов.
    """
    document_context = state.get("document_context", "")
    
    if not document_context:
        return {"legal_check": None}
    
    logger.info(f"[CheckLegal] Checking legal accuracy: {len(document_context)} chars")
    
    new_state = dict(state)
    
    try:
        # Context engineering
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            check_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT:\n{document_context}"
        else:
            check_text = document_context
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        legal_prompt = f"""Проверь следующий юридический документ на юридическую точность.

ДОКУМЕНТ:
{check_text}

Проверь:
1. Корректность юридических терминов
2. Соответствие законодательству
3. Логическую последовательность клаузул
4. Отсутствие противоречий

Ответь в формате JSON согласно схеме LegalCheckResult."""
        
        try:
            structured_llm = llm.with_structured_output(LegalCheckResult)
            result = structured_llm.invoke([HumanMessage(content=legal_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[CheckLegal] Structured output failed: {e}")
            result = LegalCheckResult(issues=[], recommendations=[])
        
        new_state["legal_check"] = result.model_dump() if hasattr(result, 'model_dump') else result
        logger.info(f"[CheckLegal] Found {len(result.issues) if hasattr(result, 'issues') else 0} issues")
        
    except Exception as e:
        logger.error(f"[CheckLegal] Error: {e}", exc_info=True)
        new_state["legal_check"] = None
    
    return new_state


def check_compliance_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Проверка соответствия стандартам.
    
    Использует context engineering для больших документов.
    """
    document_context = state.get("document_context", "")
    
    if not document_context:
        return {"compliance_check": None}
    
    logger.info(f"[CheckCompliance] Checking compliance: {len(document_context)} chars")
    
    new_state = dict(state)
    
    try:
        # Context engineering
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            check_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT:\n{document_context}"
        else:
            check_text = document_context
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        compliance_prompt = f"""Проверь следующий юридический документ на соответствие стандартам.

ДОКУМЕНТ:
{check_text}

Проверь:
1. Соответствие стандартам оформления
2. Наличие обязательных элементов
3. Правильность структуры
4. Соответствие требованиям

Ответь в формате JSON согласно схеме ComplianceCheckResult."""
        
        try:
            structured_llm = llm.with_structured_output(ComplianceCheckResult)
            result = structured_llm.invoke([HumanMessage(content=compliance_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[CheckCompliance] Structured output failed: {e}")
            result = ComplianceCheckResult(violations=[], fixes=[])
        
        new_state["compliance_check"] = result.model_dump() if hasattr(result, 'model_dump') else result
        logger.info(f"[CheckCompliance] Found {len(result.violations) if hasattr(result, 'violations') else 0} violations")
        
    except Exception as e:
        logger.error(f"[CheckCompliance] Error: {e}", exc_info=True)
        new_state["compliance_check"] = None
    
    return new_state


def parallel_checks_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Выполняет все проверки документа последовательно и объединяет результаты.
    
    Проверяет:
    - Грамматику и орфографию
    - Юридическую точность
    - Соответствие стандартам
    
    Затем объединяет результаты.
    """
    logger.info("[ParallelChecks] Running all checks")
    
    # Выполняем все проверки последовательно
    # (для настоящей параллельности нужно использовать Send API через conditional edges)
    
    # 1. Грамматика
    grammar_state = check_grammar_node(state, config=config, db=db)
    
    # 2. Юридическая точность  
    legal_state = check_legal_accuracy_node(state, config=config, db=db)
    
    # 3. Соответствие стандартам
    compliance_state = check_compliance_node(state, config=config, db=db)
    
    # Объединяем результаты в новое состояние
    new_state = dict(state)
    new_state["grammar_check"] = grammar_state.get("grammar_check")
    new_state["legal_check"] = legal_state.get("legal_check")
    new_state["compliance_check"] = compliance_state.get("compliance_check")
    
    # Объединяем через merge
    merged_state = merge_checks_results_node(new_state, config=config, db=db)
    
    logger.info("[ParallelChecks] All checks completed and merged")
    
    return merged_state


def merge_checks_results_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Объединяет результаты параллельных проверок.
    
    Паттерн из Deep Research: compression для сжатия результатов.
    """
    grammar_check = state.get("grammar_check")
    legal_check = state.get("legal_check")
    compliance_check = state.get("compliance_check")
    
    logger.info("[MergeChecks] Merging parallel check results")
    
    new_state = dict(state)
    
    # Объединяем результаты
    all_issues = []
    
    if grammar_check:
        errors = grammar_check.get("errors", [])
        all_issues.extend([{"type": "grammar", **e} for e in errors])
    
    if legal_check:
        issues = legal_check.get("issues", [])
        all_issues.extend([{"type": "legal", **i} for i in issues])
    
    if compliance_check:
        violations = compliance_check.get("violations", [])
        all_issues.extend([{"type": "compliance", **v} for v in violations])
    
    # Compression: приоритизируем и группируем
    prioritized_issues = sorted(all_issues, key=lambda x: x.get("severity", "low") == "high", reverse=True)
    
    new_state["merged_checks"] = {
        "total_issues": len(all_issues),
        "issues": prioritized_issues[:10],  # Ограничиваем до 10 самых важных
        "grammar_count": len(grammar_check.get("errors", [])) if grammar_check else 0,
        "legal_count": len(legal_check.get("issues", [])) if legal_check else 0,
        "compliance_count": len(compliance_check.get("violations", [])) if compliance_check else 0
    }
    
    logger.info(f"[MergeChecks] Merged {len(all_issues)} issues into {len(prioritized_issues[:10])} prioritized")
    
    return new_state


# ============== Precedents Search Node ==============

def search_precedents_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Поиск похожих дел и прецедентов.
    
    Использует:
    - RAG retrieval для поиска в базе данных
    - Context engineering для summarization результатов
    
    Паттерны из курсов:
    - RAG retrieval (Chat Graph): поиск в базе данных
    - Context engineering (Deep Research): summarization результатов
    """
    question = state.get("question", "")
    document_context = state.get("document_context", "")
    case_id = state.get("case_id", "")
    
    if not case_id:
        logger.warning("[SearchPrecedents] No case_id in state")
        return {"precedents": []}
    
    logger.info(f"[SearchPrecedents] Searching precedents for case {case_id}")
    
    new_state = dict(state)
    
    try:
        # Используем RAG service для поиска похожих дел
        from app.services.rag_service import RAGService
        
        rag_service = RAGService()
        
        # Формируем запрос для поиска прецедентов
        search_query = f"{question} {document_context[:500]}" if document_context else question
        
        # Ищем в других делах (не в текущем)
        # В реальной реализации нужно добавить фильтрацию по case_id
        docs = rag_service.retrieve_context(
            case_id=case_id,
            query=search_query,
            k=5,
            retrieval_strategy="multi_query",
            db=db
        )
        
        if docs:
            # Context engineering: summarization результатов
            precedents = []
            for i, doc in enumerate(docs[:5], 1):
                content = doc.page_content[:500]  # Ограничиваем длину
                precedents.append({
                    "index": i,
                    "source": doc.metadata.get("source", "Неизвестный источник"),
                    "content": content,
                    "relevance": doc.metadata.get("score", 0.0)
                })
            
            new_state["precedents"] = precedents
            logger.info(f"[SearchPrecedents] Found {len(precedents)} precedents")
        else:
            new_state["precedents"] = []
            logger.info("[SearchPrecedents] No precedents found")
        
    except Exception as e:
        logger.error(f"[SearchPrecedents] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Precedents search error: {str(e)}"]
        new_state["precedents"] = []
    
    return new_state

