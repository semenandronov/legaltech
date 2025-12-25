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
        
        # Используем helper для прямого вызова LLM с RAG и структурированного парсинга
        from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response, parse_with_fixing
        from app.services.langchain_parsers import ParserService, RiskModel
        from typing import List
        
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

Извлеки конкретные риски с обоснованием. Верни результат в формате JSON массива объектов с полями: risk_name, risk_category, probability, impact, description, evidence, recommendation, reasoning, confidence."""
        
        from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
        
        # Create callback for logging
        callback = AnalysisCallbackHandler(agent_name="risk")
        
        prompt = get_agent_prompt("risk")
        response_text = direct_llm_call_with_rag(
            case_id=case_id,
            system_prompt=prompt,
            user_query=user_query,
            rag_service=rag_service,
            db=db,
            k=20,
            temperature=0.1,
            callbacks=[callback]
        )
        
        # Parse risks with fixing parser
        parsed_risks = None
        try:
            # Try to use structured parsing with fixing
            llm = ChatYandexGPT(
                model=config.YANDEX_GPT_MODEL or "yandexgpt-lite",
                temperature=0.1,
            )
            parsed_risks = parse_with_fixing(response_text, RiskModel, llm=llm, max_retries=3, is_list=True)
        except Exception as e:
            logger.warning(f"Could not parse risks with fixing parser: {e}, trying manual parsing")
        
        # Fallback to manual parsing
        if not parsed_risks:
            try:
                risk_data = extract_json_from_response(response_text)
                if risk_data:
                    parsed_risks = ParserService.parse_risks(
                        json.dumps(risk_data) if isinstance(risk_data, (list, dict)) else str(risk_data)
                    )
                else:
                    parsed_risks = ParserService.parse_risks(response_text)
            except Exception as e:
                logger.error(f"Error parsing risks: {e}")
                parsed_risks = []
        
        # Save to database
        result_id = None
        if db:
            # Convert risks to dict for storage
            risks_data = []
            if parsed_risks:
                for risk in parsed_risks:
                    if hasattr(risk, 'dict'):
                        risks_data.append(risk.dict())
                    elif hasattr(risk, 'model_dump'):
                        risks_data.append(risk.model_dump())
                    elif isinstance(risk, dict):
                        risks_data.append(risk)
                    else:
                        risks_data.append({
                            "risk_name": getattr(risk, 'risk_name', ''),
                            "risk_category": getattr(risk, 'risk_category', ''),
                            "probability": getattr(risk, 'probability', 'MEDIUM'),
                            "impact": getattr(risk, 'impact', 'MEDIUM'),
                            "description": getattr(risk, 'description', ''),
                            "evidence": getattr(risk, 'evidence', []),
                            "recommendation": getattr(risk, 'recommendation', ''),
                            "reasoning": getattr(risk, 'reasoning', ''),
                            "confidence": getattr(risk, 'confidence', 0.8)
                        })
            
            risk_analysis_result = AnalysisResult(
                case_id=case_id,
                analysis_type="risk_analysis",
                result_data={
                    "risks": risks_data,
                    "total_risks": len(risks_data),
                    "discrepancies": discrepancy_result
                },
                status="completed"
            )
            db.add(risk_analysis_result)
            db.commit()
            result_id = risk_analysis_result.id
        
        logger.info(f"Risk agent: Completed analysis for case {case_id}, found {len(parsed_risks) if parsed_risks else 0} risks")
        
        # Create result
        result_data = {
            "risks": [
                {
                    "risk_name": r.risk_name if hasattr(r, 'risk_name') else r.get('risk_name', ''),
                    "risk_category": r.risk_category if hasattr(r, 'risk_category') else r.get('risk_category', ''),
                    "probability": r.probability if hasattr(r, 'probability') else r.get('probability', 'MEDIUM'),
                    "impact": r.impact if hasattr(r, 'impact') else r.get('impact', 'MEDIUM'),
                    "description": r.description if hasattr(r, 'description') else r.get('description', ''),
                    "evidence": r.evidence if hasattr(r, 'evidence') else r.get('evidence', []),
                    "recommendation": r.recommendation if hasattr(r, 'recommendation') else r.get('recommendation', ''),
                    "reasoning": r.reasoning if hasattr(r, 'reasoning') else r.get('reasoning', ''),
                    "confidence": r.confidence if hasattr(r, 'confidence') else r.get('confidence', 0.8)
                }
                for r in (parsed_risks if parsed_risks else [])
            ],
            "total_risks": len(parsed_risks) if parsed_risks else 0,
            "discrepancies": discrepancy_result,
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
