"""Risk analysis agent node for LangGraph"""
from typing import Dict, Any
from app.services.yandex_llm import ChatYandexGPT
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
from app.models.case import Case
import logging
import json

logger = logging.getLogger(__name__)


def risk_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Risk analysis agent node for analyzing risks based on discrepancies
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with risk_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Risk agent: Starting analysis for case {case_id}")
        
        # Check if discrepancy result is available (dependency)
        discrepancy_result = state.get("discrepancy_result")
        if not discrepancy_result:
            logger.warning(f"Risk agent: No discrepancy result available for case {case_id}, skipping")
            new_state = state.copy()
            new_state["risk_result"] = None
            return new_state
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools
        tools = get_all_tools()
        
        # Initialize LLM with temperature=0.1 for risk analysis (slightly higher for analysis task)
        # Только YandexGPT, без fallback
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
            raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
        
        # YandexGPT не поддерживает инструменты, используем прямой RAG подход
        if not rag_service:
            raise ValueError("RAG service required for risk analysis")
        
        # Используем helper для прямого вызова LLM с RAG
        from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag
        
        # Get case info
        case_info = ""
        if db:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                case_info = f"Тип дела: {case.case_type or 'Не указан'}\nОписание: {case.description or 'Нет описания'}\n"
        
        # Формируем запрос с данными о противоречиях
        discrepancies_text = json.dumps(discrepancy_result.get("discrepancies", []), ensure_ascii=False, indent=2)
        user_query = f"""Проанализируй риски следующего дела:

{case_info}

Найденные противоречия:
{discrepancies_text}

Оцени риски по категориям: юридические, финансовые, репутационные, процессуальные."""
        
        prompt = get_agent_prompt("risk")
        response_text = direct_llm_call_with_rag(
            case_id=case_id,
            system_prompt=prompt,
            user_query=user_query,
            rag_service=rag_service,
            db=db,
            k=20,
            temperature=0.1
        )
        
        # Save to database
        # Преобразуем discrepancy_result в формат, ожидаемый фронтендом
        # Фронтенд ожидает объект с ключами, а не массив
        discrepancies_dict = {}
        if discrepancy_result and isinstance(discrepancy_result, dict):
            discrepancies_list = discrepancy_result.get("discrepancies", [])
            if isinstance(discrepancies_list, list):
                # Преобразуем массив в объект с ключами-индексами
                for idx, disc in enumerate(discrepancies_list):
                    disc_id = disc.get("id") if isinstance(disc, dict) else (disc.id if hasattr(disc, 'id') else str(idx))
                    key = disc_id or f"risk_{idx}"
                    discrepancies_dict[key] = {
                        "id": disc_id,
                        "type": disc.get("type") if isinstance(disc, dict) else (disc.type if hasattr(disc, 'type') else ""),
                        "severity": disc.get("severity") if isinstance(disc, dict) else (disc.severity if hasattr(disc, 'severity') else "MEDIUM"),
                        "title": disc.get("type") if isinstance(disc, dict) else (disc.type if hasattr(disc, 'type') else ""),
                        "description": disc.get("description") if isinstance(disc, dict) else (disc.description if hasattr(disc, 'description') else ""),
                        "location": disc.get("details", {}).get("location1", "") if isinstance(disc, dict) and isinstance(disc.get("details"), dict) else "",
                        "document": (disc.get("source_documents", [])[0] if isinstance(disc.get("source_documents"), list) and len(disc.get("source_documents", [])) > 0 else "") if isinstance(disc, dict) else (disc.source_documents[0] if hasattr(disc, 'source_documents') and isinstance(disc.source_documents, list) and len(disc.source_documents) > 0 else ""),
                        "page": disc.get("details", {}).get("source_page") if isinstance(disc, dict) and isinstance(disc.get("details"), dict) else None,
                        "section": "",
                        "analysis": disc.get("reasoning", "") if isinstance(disc, dict) else (disc.reasoning if hasattr(disc, 'reasoning') else ""),
                        "reasoning": disc.get("reasoning", "") if isinstance(disc, dict) else (disc.reasoning if hasattr(disc, 'reasoning') else ""),
                    }
        
        result_id = None
        if db:
            risk_analysis_result = AnalysisResult(
                case_id=case_id,
                analysis_type="risk_analysis",
                result_data={
                    "analysis": response_text,
                    "discrepancies": discrepancies_dict  # Теперь это объект, а не массив
                },
                status="completed"
            )
            db.add(risk_analysis_result)
            db.commit()
            result_id = risk_analysis_result.id
        
        logger.info(f"Risk agent: Completed analysis for case {case_id}")
        
        # Create result
        result_data = {
            "analysis": response_text,
            "discrepancies": discrepancies_dict,  # Теперь это объект
            "result_id": result_id
        }
        
        # Update state
        new_state = state.copy()
        new_state["risk_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Risk agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "risk",
            "error": str(e)
        })
        new_state["risk_result"] = None
        return new_state
