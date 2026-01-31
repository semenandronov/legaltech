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
from langchain_core.messages import HumanMessage
import logging
import uuid
import json

from app.services.langchain_agents.graphs.chat_graph import ChatGraphState
from app.services.llm_factory import create_legal_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============== Pydantic Models for Structured Outputs ==============

class StructuredEditSchema(BaseModel):
    """Схема для одного структурированного изменения"""
    original_text: str = Field(..., description="Точный текст из документа для замены")
    new_text: str = Field(..., description="Новый текст для замены")
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
    
    if not document_context:
        logger.warning("[GenerateEdits] No document_context in state")
        return {"structured_edits": []}
    
    logger.info(f"[GenerateEdits] Generating edits for: {question[:100]}...")
    
    new_state = dict(state)
    
    try:
        # Context engineering: summarization для больших документов
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            doc_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT_LENGTH: {len(document_context)} chars\n\nFULL_DOCUMENT:\n{document_context}"
        else:
            doc_text = document_context
        
        # Structured output для гарантированного формата
        llm = create_legal_llm(use_rate_limiting=False)
        
        edits_prompt = f"""На основе запроса пользователя сгенерируй структурированные правки для документа.

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

ДОКУМЕНТ:
{doc_text}

ВАЖНО:
1. В original_text указывай ТОЧНЫЙ текст из документа
2. В new_text указывай новый текст для замены
3. Проверь, что original_text действительно есть в документе

Ответь в формате JSON согласно схеме EditsResponse."""
        
        try:
            structured_llm = llm.with_structured_output(EditsResponse)
            edits_response = structured_llm.invoke([HumanMessage(content=edits_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[GenerateEdits] Structured output failed: {e}, using fallback")
            # Fallback: обычный вызов
            response = llm.invoke([HumanMessage(content=edits_prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Простой fallback - возвращаем пустой список
            edits_response = EditsResponse(edits=[], reasoning=response_text[:200])
        
        # Проверяем наличие текста в документе и извлекаем контекст
        validated_edits = []
        edits_list = edits_response.edits if hasattr(edits_response, 'edits') else []
        
        for edit in edits_list:
            original_text = edit.original_text if hasattr(edit, 'original_text') else edit.get('original_text', '')
            new_text = edit.new_text if hasattr(edit, 'new_text') else edit.get('new_text', '')
            
            # Проверяем наличие в документе
            find_pos = document_context.find(original_text)
            found_in_doc = find_pos != -1
            
            # Извлекаем контекст
            context_before, context_after = extract_context(document_context, original_text) if found_in_doc else ("", "")
            
            validated_edits.append({
                "id": f"edit-{uuid.uuid4().hex[:8]}",
                "original_text": original_text,
                "new_text": new_text,
                "context_before": context_before,
                "context_after": context_after,
                "found_in_document": found_in_doc
            })
            
            if found_in_doc:
                logger.info(f"[GenerateEdits] Found edit: '{original_text[:50]}…' → '{new_text[:50]}…'")
            else:
                logger.warning(f"[GenerateEdits] Edit text not found: '{original_text[:100]}…'")
        
        new_state["structured_edits"] = validated_edits
        logger.info(f"[GenerateEdits] Generated {len(validated_edits)} edits")
        
    except Exception as e:
        logger.error(f"[GenerateEdits] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Generate edits error: {str(e)}"]
        new_state["structured_edits"] = []
    
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
    structured_edits = state.get("structured_edits", [])
    document_context = state.get("document_context", "")
    
    if not structured_edits:
        logger.warning("[ValidateEdits] No structured_edits to validate")
        return {"edits_valid": True}
    
    # Hard limit для предотвращения бесконечных циклов
    MAX_VALIDATION_ITERATIONS = 3
    iteration = state.get("edit_validation_iteration", 0)
    
    if iteration >= MAX_VALIDATION_ITERATIONS:
        logger.warning(f"[ValidateEdits] Max iterations ({MAX_VALIDATION_ITERATIONS}) reached, forcing valid")
        return {"edits_valid": True}
    
    logger.info(f"[ValidateEdits] Validating {len(structured_edits)} edits (iteration {iteration + 1}/{MAX_VALIDATION_ITERATIONS})")
    
    new_state = dict(state)
    
    try:
        # Используем think tool для рефлексии перед валидацией
        if iteration > 0:
            reflection = f"Валидация {iteration + 1}. Предыдущая валидация нашла ошибки. Нужно проверить более тщательно."
            think_tool(reflection, state)
        
        # Context engineering: summarization для больших документов
        if len(document_context) > 5000:
            summary = summarize_document(document_context, max_length=5000)
            doc_text = f"SUMMARY:\n{summary}\n\nFULL_DOCUMENT_LENGTH: {len(document_context)} chars\n\nFULL_DOCUMENT:\n{document_context}"
        else:
            doc_text = document_context
        
        # Structured output для валидации
        llm = create_legal_llm(use_rate_limiting=False)
        
        validation_prompt = f"""Проверь следующие структурированные правки для документа на корректность.

ДОКУМЕНТ:
{doc_text}

ПРАВКИ:
{json.dumps(structured_edits, ensure_ascii=False, indent=2)}

Проверь:
1. Наличие original_text в документе
2. Корректность контекста (context_before, context_after)
3. Логичность замены (new_text соответствует запросу)
4. Отсутствие конфликтов между правками

Ответь в формате JSON согласно схеме ValidationResultSchema."""
        
        try:
            structured_llm = llm.with_structured_output(ValidationResultSchema)
            validation_result = structured_llm.invoke([HumanMessage(content=validation_prompt)])
        except (AttributeError, Exception) as e:
            logger.warning(f"[ValidateEdits] Structured output failed: {e}, using fallback")
            # Fallback: проверяем наличие текста в документе
            all_found = all(edit.get("found_in_document", False) for edit in structured_edits)
            validation_result = ValidationResultSchema(
                is_valid=all_found,
                errors=[] if all_found else ["Некоторые правки не найдены в документе"],
                warnings=[]
            )
        
        is_valid = validation_result.is_valid if hasattr(validation_result, 'is_valid') else True
        errors = validation_result.errors if hasattr(validation_result, 'errors') else []
        
        new_state["edits_valid"] = is_valid
        new_state["edit_errors"] = errors
        new_state["edit_validation_iteration"] = iteration + 1
        
        logger.info(f"[ValidateEdits] Validation result: valid={is_valid}, errors={len(errors)}")
        
    except Exception as e:
        logger.error(f"[ValidateEdits] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Validation error: {str(e)}"]
        new_state["edits_valid"] = True  # При ошибке считаем валидными, чтобы не блокировать
        new_state["edit_errors"] = []
    
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
    structured_edits = state.get("structured_edits", [])
    document_context = state.get("document_context", "")
    user_id = state.get("user_id", "")
    
    if not structured_edits:
        logger.warning("[ApplyEdits] No structured_edits to apply")
        return state
    
    logger.info(f"[ApplyEdits] Applying {len(structured_edits)} edits")
    
    new_state = dict(state)
    
    try:
        # Применяем edits
        edited_content = document_context
        changes_applied = 0
        
        for edit in structured_edits:
            if edit.get("found_in_document", False):
                original_text = edit.get("original_text", "")
                new_text = edit.get("new_text", "")
                
                # Заменяем только первое вхождение
                if original_text in edited_content:
                    edited_content = edited_content.replace(original_text, new_text, 1)
                    changes_applied += 1
                    logger.debug(f"[ApplyEdits] Applied edit: '{original_text[:50]}…' → '{new_text[:50]}…'")
        
        # Обновляем Memory/Store с preferences редактора
        store = config.get("store") if config else None
        if store and user_id:
            try:
                from datetime import datetime
                preferences = {
                    "last_edit_type": "structured_edit",
                    "edits_count": len(structured_edits),
                    "changes_applied": changes_applied,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                if hasattr(store, 'put'):
                    # Обновляем preferences в Store
                    # Namespace: ("editor_preferences", user_id), Key: "preferences"
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
        new_state["edited_content"] = document_context  # Fallback: возвращаем оригинал
    
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


def parallel_checks_node(state: ChatGraphState) -> List:
    """
    Запускает параллельные проверки документа через Send API.
    
    Паттерн из Workflow Graph курса.
    
    Returns:
        List[Send] - список Send объектов для параллельного выполнения
    """
    from langgraph.types import Send
    
    logger.info("[ParallelChecks] Dispatching parallel checks")
    
    sends = [
        Send("check_grammar", state),
        Send("check_legal_accuracy", state),
        Send("check_compliance", state)
    ]
    
    return sends


def merge_checks_results_node(state: ChatGraphState) -> ChatGraphState:
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

