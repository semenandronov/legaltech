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

EDIT_GENERATION_SYSTEM_PROMPT = """Ты — юридический редактор. Тебе передан HTML юридического документа.
Каждый значимый блок (абзац, заголовок, пункт списка, ячейка таблицы) имеет атрибут id="UUID" на открывающем теге.

Твоя задача — вернуть JSON со списком правок (схема EditsResponse).

Для КАЖДОЙ правки:
1. Если переписываешь блок ЦЕЛИКОМ — укажи node_id (скопируй UUID из OUTLINE БЕЗ ИЗМЕНЕНИЯ СИМВОЛОВ) и new_text.
   Поле original_text ОБЯЗАТЕЛЬНО: точная копия текущего текста блока (plain text, как в OUTLINE), для fallback на клиенте.
2. Если меняешь фразу ВНУТРИ блока — укажи original_text (точный фрагмент из HTML) и new_text; node_id не указывай.
3. Категорически запрещено выдумывать id, которых нет в OUTLINE или HTML.
4. Не меняй id, не добавляй новые теги с id — только текстовые правки.
5. Учитывай историю диалога: местоимения («его», «это») и отсылки к прошлым ответам ассистента — подставляй факты из истории (ИНН, адреса, суммы)."""

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
    """Ответ с структурированными правками"""
    edits: List[StructuredEditSchema] = Field(..., description="Список правок")
    reasoning: str = Field(..., description="Обоснование правок")


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
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "editor_enrich_context") as tr:
        case_id = state.get("case_id")
        question = (state.get("question") or "").strip()
        if not case_id or not question:
            out: Dict[str, Any] = {}
            if tr:
                tr.set_output(out)
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


def _generate_selection_edit(
    state: ChatGraphState,
    selected_text: str,
    question: str,
    document_context: str,
) -> ChatGraphState:
    """Fast path: user selected text — return one structured edit with exact original_text."""
    llm = create_legal_llm(use_rate_limiting=False)
    memory_section = _editor_memory_section(state)
    system_prompt = (
        "Ты — AI-ассистент для точечного редактирования юридических текстов.\n\n"
        "Пользователь выделил конкретный фрагмент и хочет применить к нему инструкцию.\n\n"
        "Учитывай историю диалога: «его/это» — подставляй данные из прошлых ответов ассистента.\n\n"
        "Ответь строго в формате (две строки):\n\n"
        "ОБЪЯСНЕНИЕ: <одно предложение — что именно ты изменяешь>\n"
        "ЗАМЕНА: <улучшенный вариант выделенного текста>\n\n"
        "После слова ЗАМЕНА: — только новый текст, без кавычек."
    )
    memory_block = f"\n\n{memory_section}\n" if memory_section else ""
    user_prompt = (
        f"ИНСТРУКЦИЯ: {question}{memory_block}\n\n"
        f"ВЫДЕЛЕННЫЙ ТЕКСТ (работай только с ним):\n{selected_text}\n"
    )
    response = llm.invoke([HumanMessage(content=system_prompt + "\n\n" + user_prompt)])
    answer = response.content if hasattr(response, "content") else str(response)

    import re as _re
    explanation_match = _re.search(r"ОБЪЯСНЕНИЕ:\s*(.+?)(?=\nЗАМЕНА:|$)", answer, _re.DOTALL)
    replacement_match = _re.search(r"ЗАМЕНА:\s*([\s\S]+)", answer)
    explanation = explanation_match.group(1).strip() if explanation_match else ""
    new_text = replacement_match.group(1).strip() if replacement_match else None

    if not new_text:
        clean = _re.sub(r"```[\s\S]*?```", "", answer, flags=_re.DOTALL).strip()
        return {"response": clean or "Не удалось подготовить правку.", "structured_edits": []}

    edit = {
        "id": f"edit-{uuid.uuid4().hex[:8]}",
        "original_text": selected_text,
        "new_text": new_text,
        "context_before": "",
        "context_after": "",
        "found_in_document": True,
    }
    resp_text = explanation or "Правка подготовлена."
    out: Dict[str, Any] = {
        "response": resp_text,
        "structured_edits": [edit],
    }
    msgs = _append_editor_turn_message(
        state,
        f"{resp_text} Замена: {new_text[:500]}",
    )
    if msgs:
        out["messages"] = msgs
    return out


def generate_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Генерирует structured_edits на основе запроса пользователя.
    
    Использует:
    - Structured outputs вместо regex парсинга
    - Проверку наличия текста в документе
    
    Паттерны из курсов:
    - Structured outputs (Ambient Agents): вместо regex парсинга
    
    Сохраняет в state.structured_edits.
    """
    question = state.get("question", "")
    document_context = state.get("document_context", "")
    selected_text = (state.get("selected_text") or "").strip()
    editor_mode_hint = state.get("editor_mode_hint")

    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    if selected_text and editor_mode_hint == "edit":
        with editor_node_trace(state, "generate_selection_edit") as tr:
            out = _generate_selection_edit(state, selected_text, question, document_context)
            if tr:
                tr.set_output(out)
            return out

    if not document_context:
        logger.warning("[GenerateEdits] No document_context in state")
        return {"structured_edits": []}

    logger.info(f"[GenerateEdits] Generating edits for: {question[:100]}...")

    new_state = dict(state)

    with editor_node_trace(state, "generate_edits") as tr:
        try:
            # Контекст приходит с фронта (context windowing); не суммаризируем — иначе теряются id.
            doc_text = document_context

            llm = create_legal_llm(use_rate_limiting=False)

            outline = build_document_outline(document_context)
            outline_json = json.dumps(outline, ensure_ascii=False, indent=2) if outline else "[]"
            memory_section = _editor_memory_section(state)
            memory_block = f"\n{memory_section}\n" if memory_section else ""

            edits_user_prompt = f"""ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{question}
{memory_block}
OUTLINE (блоки с node_id — единственный источник допустимых id):
{outline_json}

ДОКУМЕНТ (HTML, атрибут id на блоках):
{doc_text}

Дополнительно:
- Замена целого блока: node_id + original_text (копия из OUTLINE) + new_text.
- Замена фразы внутри блока: original_text + new_text, без node_id.
- Несколько одинаковых мест — отдельная правка на каждое.
- Если в запросе «вставь его/это» — возьми значение из истории диалога (например ИНН из ответа ассистента)."""

            try:
                structured_llm = llm.with_structured_output(EditsResponse)
                edits_response = structured_llm.invoke([
                    SystemMessage(content=EDIT_GENERATION_SYSTEM_PROMPT),
                    HumanMessage(content=edits_user_prompt),
                ])
            except (AttributeError, Exception) as e:
                logger.warning(f"[GenerateEdits] Structured output failed: {e}, using fallback")
                response = llm.invoke([
                    SystemMessage(content=EDIT_GENERATION_SYSTEM_PROMPT),
                    HumanMessage(content=edits_user_prompt),
                ])
                response_text = response.content if hasattr(response, 'content') else str(response)
                edits_response = EditsResponse(edits=[], reasoning=response_text[:200])

            raw_edits = []
            edits_list = edits_response.edits if hasattr(edits_response, 'edits') else []

            for edit in edits_list:
                original_text = edit.original_text if hasattr(edit, 'original_text') else edit.get('original_text', '')
                node_id = edit.node_id if hasattr(edit, 'node_id') else edit.get('node_id')
                new_text = edit.new_text if hasattr(edit, 'new_text') else edit.get('new_text', '')

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

                occurrences = []
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
                    logger.warning(f"[GenerateEdits] Edit text not found: '{(original_text or '')[:100]}…'")
                else:
                    for pos in occurrences:
                        ctx_before = document_context[max(0, pos - 50):pos]
                        ctx_after = document_context[pos + len(original_text):pos + len(original_text) + 50]
                        raw_edits.append({
                            "id": f"edit-{uuid.uuid4().hex[:8]}",
                            "original_text": original_text,
                            "node_id": node_id,
                            "new_text": new_text,
                            "context_before": ctx_before,
                            "context_after": ctx_after,
                            "found_in_document": True,
                        })
                    logger.info(f"[GenerateEdits] '{original_text[:50]}…' → '{new_text[:50]}…' ({len(occurrences)} вхождений)")

            new_state["structured_edits"] = raw_edits
            logger.info(f"[GenerateEdits] Generated {len(raw_edits)} edits (from {len(edits_list)} LLM edits)")
            summary = f"Подготовлено правок: {len(raw_edits)}."
            if raw_edits:
                preview = (raw_edits[0].get("new_text") or "")[:200]
                if preview:
                    summary += f" Пример замены: {preview}"
            turn_msgs = _append_editor_turn_message(state, summary)
            if turn_msgs:
                new_state["messages"] = turn_msgs
            if tr:
                tr.set_output(new_state)
            return new_state
        except Exception as e:
            logger.error(f"[GenerateEdits] Error: {e}", exc_info=True)
            new_state["errors"] = (new_state.get("errors") or []) + [f"Generate edits error: {str(e)}"]
            new_state["structured_edits"] = []
            if tr:
                tr.set_output(new_state)
            return new_state


class ValidationResultSchema(BaseModel):
    """Схема для результата валидации"""
    is_valid: bool = Field(..., description="Валидны ли правки")
    errors: List[str] = Field(default_factory=list, description="Список ошибок")
    warnings: List[str] = Field(default_factory=list, description="Список предупреждений")


def validate_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Валидирует structured_edits перед применением.
    
    Использует:
    - Hard limits: максимум 3 итерации валидации
    - Think tool: рефлексия перед валидацией
    - Structured outputs: для гарантированного формата
    
    Паттерны из курсов:
    - Hard limits (Deep Research): ограничение итераций
    - Think tool (Deep Research): рефлексия перед валидацией
    
    Устанавливает state.edits_valid (bool).
    """
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "validate_edits") as tr:
        structured_edits = state.get("structured_edits", [])
        document_context = state.get("document_context", "")

        if not structured_edits:
            logger.warning("[ValidateEdits] No structured_edits to validate")
            out = {"edits_valid": True}
            if tr:
                tr.set_output(out)
            return out

        MAX_VALIDATION_ITERATIONS = 3
        iteration = state.get("edit_validation_iteration", 0)

        if iteration >= MAX_VALIDATION_ITERATIONS:
            logger.warning(
                "[ValidateEdits] Max iterations (%s) reached, forcing valid",
                MAX_VALIDATION_ITERATIONS,
            )
            out = {"edits_valid": True}
            if tr:
                tr.set_output(out)
            return out

        logger.info(
            "[ValidateEdits] Validating %s edits (iteration %s/%s)",
            len(structured_edits),
            iteration + 1,
            MAX_VALIDATION_ITERATIONS,
        )

        new_state = dict(state)

        for edit in structured_edits:
            if not isinstance(edit, dict):
                continue
            node_id = edit.get("node_id")
            original_text = edit.get("original_text") or ""
            if node_id:
                if not (edit.get("original_text") or "").strip():
                    edit["original_text"] = _extract_block_text_by_node_id(
                        document_context, node_id
                    )
                edit["found_in_document"] = _node_id_in_document(node_id, document_context)
            elif original_text and "found_in_document" not in edit:
                edit["found_in_document"] = original_text in document_context

        try:
            if iteration > 0:
                reflection = (
                    f"Валидация {iteration + 1}. Предыдущая валидация нашла ошибки. "
                    "Нужно проверить более тщательно."
                )
                think_tool(reflection, state)

            if len(document_context) > 5000:
                summary = summarize_document(document_context, max_length=5000)
                doc_text = (
                    f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT_LENGTH: {len(document_context)} chars\n\n"
                    f"FULL_DOCUMENT:\n{document_context}"
                )
            else:
                doc_text = document_context

            llm = create_legal_llm(use_rate_limiting=False)
            validation_prompt = f"""Проверь следующие структурированные правки для документа на корректность.

ДОКУМЕНТ:
{doc_text}

ПРАВКИ:
{json.dumps(structured_edits, ensure_ascii=False, indent=2)}

Проверь:
1. Для правок с node_id — id должен существовать в HTML документа (атрибут id=...)
2. Для правок с original_text — фрагмент должен быть в документе
3. Логичность замены (new_text соответствует запросу)
4. Отсутствие конфликтов между правками

Ответь в формате JSON согласно схеме ValidationResultSchema."""

            try:
                structured_llm = llm.with_structured_output(ValidationResultSchema)
                validation_result = structured_llm.invoke([HumanMessage(content=validation_prompt)])
            except (AttributeError, Exception) as e:
                logger.warning(f"[ValidateEdits] Structured output failed: {e}, using fallback")
                all_found = all(edit.get("found_in_document", False) for edit in structured_edits)
                validation_result = ValidationResultSchema(
                    is_valid=all_found,
                    errors=[] if all_found else ["Некоторые правки не найдены в документе"],
                    warnings=[],
                )

            is_valid = validation_result.is_valid if hasattr(validation_result, "is_valid") else True
            errors = validation_result.errors if hasattr(validation_result, "errors") else []

            new_state["edits_valid"] = is_valid
            new_state["edit_errors"] = errors
            new_state["edit_validation_iteration"] = iteration + 1

            logger.info(f"[ValidateEdits] Validation result: valid={is_valid}, errors={len(errors)}")

        except Exception as e:
            logger.error(f"[ValidateEdits] Error: {e}", exc_info=True)
            new_state["errors"] = (new_state.get("errors") or []) + [f"Validation error: {str(e)}"]
            new_state["edits_valid"] = True
            new_state["edit_errors"] = []

        if tr:
            tr.set_output(new_state)
        return new_state


def apply_edits_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Применяет валидированные structured_edits к документу.
    
    Обновляет Memory/Store с preferences редактора.
    
    Паттерны из курсов:
    - Memory/Store (Ambient Agents): сохранение preferences редактора
    
    Примечание: Command объекты используются для interrupts/resume,
    не для state updates в узлах. Здесь просто возвращаем обновлённое состояние.
    """
    from app.services.observability.editor_langfuse_tracing import editor_node_trace

    with editor_node_trace(state, "apply_edits") as tr:
        structured_edits = state.get("structured_edits", [])
        document_context = state.get("document_context", "")
        user_id = state.get("user_id", "")

        if not structured_edits:
            logger.warning("[ApplyEdits] No structured_edits to apply")
            if tr:
                tr.set_output({"skipped": True})
            return state

        max_auto_apply = 10
        edits_approved = bool(state.get("edits_approved", False))
        if len(structured_edits) > max_auto_apply and not edits_approved:
            new_state = dict(state)
            new_state["waiting_for_edits_approval"] = True
            new_state["response"] = (
                f"Я подготовил {len(structured_edits)} правок — это много, поэтому перед применением нужно подтверждение.\n\n"
                "Напишите «одобряю правки», чтобы применить, или «отмена», чтобы отменить."
            )
            if tr:
                tr.set_output(new_state)
            return new_state

        logger.info(f"[ApplyEdits] Applying {len(structured_edits)} edits")

        new_state = dict(state)

        try:
            edited_content = document_context
            changes_applied = 0

            for edit in structured_edits:
                if edit.get("found_in_document", False):
                    original_text = edit.get("original_text", "")
                    new_text = edit.get("new_text", "")

                    if original_text in edited_content:
                        edited_content = edited_content.replace(original_text, new_text, 1)
                        changes_applied += 1
                        logger.debug(
                            f"[ApplyEdits] Applied edit: '{original_text[:50]}…' → '{new_text[:50]}…'"
                        )

            store = config.get("store") if config else None
            if store and user_id:
                try:
                    from datetime import datetime
                    preferences = {
                        "last_edit_type": "structured_edit",
                        "edits_count": len(structured_edits),
                        "changes_applied": changes_applied,
                        "timestamp": datetime.utcnow().isoformat(),
                    }

                    if hasattr(store, "put"):
                        store.put(("editor_preferences", user_id), "preferences", preferences)
                        logger.debug(f"[ApplyEdits] Updated editor preferences in Store for user {user_id}")
                except Exception as store_e:
                    logger.debug(f"[ApplyEdits] Could not update preferences in Store: {store_e}")

            new_state["edited_content"] = edited_content
            new_state["changes_applied"] = changes_applied

            logger.info(f"[ApplyEdits] Applied {changes_applied} edits, new length: {len(edited_content)}")

        except Exception as e:
            logger.error(f"[ApplyEdits] Error: {e}", exc_info=True)
            new_state["errors"] = (new_state.get("errors") or []) + [f"Apply edits error: {str(e)}"]
            new_state["edited_content"] = document_context

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

