"""Risk analysis agent node for LangGraph"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
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
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.1,  # Немного выше для аналитической задачи, но все еще детерминистично
            max_tokens=2000
        )
        
        # Get prompt
        prompt = get_agent_prompt("risk")
        
        # Create agent
        agent = create_legal_agent(llm, tools, system_prompt=prompt)
        
        # Get case info
        case_info = ""
        if db:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                case_info = f"Тип дела: {case.case_type or 'Не указан'}\nОписание: {case.description or 'Нет описания'}\n"
        
        # Create initial message with discrepancy data
        from langchain_core.messages import HumanMessage
        discrepancies_text = json.dumps(discrepancy_result.get("discrepancies", []), ensure_ascii=False, indent=2)
        initial_message = HumanMessage(
            content=f"""Проанализируй риски следующего дела:

{case_info}

Найденные противоречия:
{discrepancies_text}

Оцени риски по категориям: юридические, финансовые, репутационные, процессуальные."""
        )
        
        # Run agent with safe invoke (handles tool use errors)
        from app.services.langchain_agents.agent_factory import safe_agent_invoke
        result = safe_agent_invoke(
            agent,
            llm,
            {
                "messages": [initial_message],
                "case_id": case_id
            },
            config={"recursion_limit": 25}
        )
        
        # Extract risk analysis from response
        response_text = result.get("messages", [])[-1].content if isinstance(result, dict) else str(result)
        
        # Save to database
        result_id = None
        if db:
            risk_analysis_result = AnalysisResult(
                case_id=case_id,
                analysis_type="risk_analysis",
                result_data={
                    "analysis": response_text,
                    "discrepancies": discrepancy_result
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
