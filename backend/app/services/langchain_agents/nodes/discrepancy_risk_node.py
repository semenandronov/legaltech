"""
Объединённый узел для поиска противоречий и оценки рисков.

Согласно рекомендациям LangGraph:
- risk_node зависит от discrepancy_result
- Нет смысла разделять их на отдельные узлы
- Объединение упрощает граф и уменьшает latency
"""
from typing import Dict, Any, Optional, List, TypedDict
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
from app.services.llm_factory import create_llm, create_legal_llm
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.models.case import Case
import logging
import json
import re

logger = logging.getLogger(__name__)


# Определяем AnalysisState локально чтобы не зависеть от удалённых модулей
class AnalysisState(TypedDict, total=False):
    """Состояние анализа."""
    case_id: str
    user_id: str
    discrepancy_result: Optional[Dict[str, Any]]
    risk_result: Optional[Dict[str, Any]]


def extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Извлечь JSON из ответа LLM.
    
    Args:
        response_text: Текст ответа LLM
    
    Returns:
        Распарсенный JSON или None
    """
    if not response_text:
        return None
    
    # Пробуем найти JSON в markdown блоке
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Пробуем найти JSON напрямую
    try:
        # Ищем первый { и последний }
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = response_text[start:end + 1]
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    return None


def discrepancy_risk_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Объединённый узел для поиска противоречий и оценки рисков.
    
    Выполняет:
    1. Поиск противоречий между документами
    2. Оценка рисков на основе найденных противоречий
    
    Args:
        state: Текущее состояние графа
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Обновлённое состояние с discrepancy_result и risk_result
    """
    case_id = state.get("case_id", "")
    
    try:
        logger.info(f"[DiscrepancyRisk] Starting combined analysis for case {case_id}")
        
        # Initialize LLM
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Get case info
        case_type = "general"
        case_context = ""
        if db:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                case_type = case.case_type.lower().replace(" ", "_").replace("-", "_") if case.case_type else "general"
                case_context = f"Тип дела: {case.case_type or 'Не указан'}\nОписание: {case.description or 'Нет описания'}"
        
        # Get documents context
        documents_context = ""
        if rag_service:
            try:
                docs = rag_service.retrieve_context(
                    case_id=case_id,
                    query="все документы дела для анализа противоречий",
                    k=10,
                    db=db
                )
                if docs:
                    documents_context = rag_service.format_sources_for_prompt(docs, max_context_chars=8000)
            except Exception as e:
                logger.warning(f"[DiscrepancyRisk] Failed to get documents context: {e}")
        
        # ========== PHASE 1: Find Discrepancies ==========
        discrepancy_request = f"""Ты - юридический аналитик. Проанализируй документы и найди противоречия.

{case_context}

ДОКУМЕНТЫ ДЕЛА:
{documents_context}

ЗАДАЧА:
Проанализируй документы и найди ВСЕ противоречия между ними.

Для каждого противоречия укажи:
1. Тип противоречия (даты, суммы, факты, показания)
2. Документ 1: название, страница, цитата
3. Документ 2: название, страница, цитата
4. Описание противоречия
5. Серьёзность: HIGH / MEDIUM / LOW

Ответь в формате JSON:
{{
    "discrepancies": [
        {{
            "id": "1",
            "type": "dates",
            "severity": "HIGH",
            "description": "...",
            "document_1": {{"name": "...", "page": 1, "quote": "..."}},
            "document_2": {{"name": "...", "page": 2, "quote": "..."}}
        }}
    ],
    "summary": "Краткое резюме найденных противоречий"
}}
"""
        
        discrepancy_response = llm.invoke([HumanMessage(content=discrepancy_request)])
        discrepancy_text = discrepancy_response.content if hasattr(discrepancy_response, 'content') else str(discrepancy_response)
        
        # Parse discrepancy result
        discrepancy_result = extract_json_from_response(discrepancy_text)
        if not discrepancy_result:
            discrepancy_result = {
                "discrepancies": [],
                "summary": "Не удалось проанализировать противоречия",
                "raw_response": discrepancy_text[:500]
            }
        
        discrepancies = discrepancy_result.get("discrepancies", [])
        logger.info(f"[DiscrepancyRisk] Found {len(discrepancies)} discrepancies")
        
        # ========== PHASE 2: Assess Risks ==========
        if not discrepancies:
            # No discrepancies = no risks from discrepancies
            risk_result = {
                "risks": [],
                "overall_risk_level": "LOW",
                "summary": "Противоречий не обнаружено, риски минимальны"
            }
        else:
            discrepancies_text = json.dumps(discrepancies, ensure_ascii=False, indent=2)
            
            risk_request = f"""Ты - юридический аналитик. Оцени риски на основе найденных противоречий.

{case_context}

НАЙДЕННЫЕ ПРОТИВОРЕЧИЯ:
{discrepancies_text}

ЗАДАЧА:
На основе найденных противоречий оцени юридические риски для дела.

Для каждого риска укажи:
1. Название риска
2. Описание
3. Уровень: CRITICAL / HIGH / MEDIUM / LOW
4. Связанные противоречия (ID)
5. Рекомендации по митигации

Ответь в формате JSON:
{{
    "risks": [
        {{
            "id": "1",
            "name": "...",
            "description": "...",
            "level": "HIGH",
            "related_discrepancies": ["1", "2"],
            "mitigation": "..."
        }}
    ],
    "overall_risk_level": "HIGH",
    "summary": "Общая оценка рисков"
}}
"""
            
            risk_response = llm.invoke([HumanMessage(content=risk_request)])
            risk_text = risk_response.content if hasattr(risk_response, 'content') else str(risk_response)
            
            risk_result = extract_json_from_response(risk_text)
            if not risk_result:
                risk_result = {
                    "risks": [],
                    "overall_risk_level": "UNKNOWN",
                    "summary": "Не удалось оценить риски",
                    "raw_response": risk_text[:500]
                }
        
        risks = risk_result.get("risks", [])
        logger.info(f"[DiscrepancyRisk] Assessed {len(risks)} risks, overall level: {risk_result.get('overall_risk_level', 'UNKNOWN')}")
        
        # ========== Update State ==========
        new_state = dict(state)
        new_state["discrepancy_result"] = discrepancy_result
        new_state["risk_result"] = risk_result
        
        logger.info(f"[DiscrepancyRisk] Completed analysis for case {case_id}")
        return new_state
        
    except Exception as e:
        logger.error(f"[DiscrepancyRisk] Error in analysis for case {case_id}: {e}", exc_info=True)
        new_state = dict(state)
        new_state["discrepancy_result"] = {
            "discrepancies": [],
            "summary": f"Ошибка анализа: {str(e)}",
            "error": str(e)
        }
        new_state["risk_result"] = {
            "risks": [],
            "overall_risk_level": "UNKNOWN",
            "summary": f"Ошибка оценки рисков: {str(e)}",
            "error": str(e)
        }
        return new_state
