"""Discrepancy agent node for LangGraph"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from sqlalchemy.orm import Session
from app.models.analysis import Discrepancy
import logging
import json

logger = logging.getLogger(__name__)


def discrepancy_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Discrepancy agent node for finding discrepancies in documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with discrepancy_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Discrepancy agent: Starting analysis for case {case_id}")
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools
        tools = get_all_tools()
        
        # Initialize LLM
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.3,
            max_tokens=2000
        )
        
        # Get prompt
        prompt = get_agent_prompt("discrepancy")
        
        # Create agent
        agent = create_react_agent(llm, tools, messages_modifier=prompt)
        
        # Create initial message
        from langchain_core.messages import HumanMessage
        initial_message = HumanMessage(
            content=f"Найди все противоречия и несоответствия между документами дела {case_id}. Используй retrieve_documents_tool для поиска документов."
        )
        
        # Run agent
        result = agent.invoke({
            "messages": [initial_message],
            "case_id": case_id
        })
        
        # Extract discrepancies from response
        response_text = result.get("messages", [])[-1].content if isinstance(result, dict) else str(result)
        
        # Try to extract JSON from response
        discrepancy_data = None
        try:
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0].strip()
                discrepancy_data = json.loads(json_text)
            elif "[" in response_text and "]" in response_text:
                start = response_text.find("[")
                end = response_text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_text = response_text[start:end]
                    discrepancy_data = json.loads(json_text)
        except Exception as e:
            logger.warning(f"Could not parse JSON from discrepancy agent response: {e}")
        
        # If we have discrepancy data, parse it
        if discrepancy_data:
            parsed_discrepancies = ParserService.parse_discrepancies(
                json.dumps(discrepancy_data) if isinstance(discrepancy_data, (list, dict)) else str(discrepancy_data)
            )
        else:
            # Fallback: use RAG to find discrepancies
            if not rag_service:
                raise ValueError("RAG service required for discrepancy finding")
            
            query = "Найди все противоречия, несоответствия и расхождения между документами"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=30)
            
            # Use LLM to analyze discrepancies
            from app.services.llm_service import LLMService
            llm_service = LLMService()
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("discrepancy")
            user_prompt = f"Проанализируй следующие документы и найди все противоречия:\n\n{sources_text}"
            
            response = llm_service.generate(system_prompt, user_prompt, temperature=0.3)
            parsed_discrepancies = ParserService.parse_discrepancies(response)
        
        # Save discrepancies to database
        saved_discrepancies = []
        if db and parsed_discrepancies:
            for disc_model in parsed_discrepancies:
                try:
                    discrepancy = Discrepancy(
                        case_id=case_id,
                        type=disc_model.type,
                        severity=disc_model.severity,
                        description=disc_model.description,
                        source_documents=disc_model.source_documents,
                        details=disc_model.details
                    )
                    db.add(discrepancy)
                    saved_discrepancies.append(discrepancy)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении противоречия: {e}, discrepancy: {disc_model}")
                    continue
            
            if saved_discrepancies:
                db.commit()
        
        # Create result
        result_data = {
            "discrepancies": [
                {
                    "id": disc.id if hasattr(disc, 'id') else None,
                    "type": disc.type if hasattr(disc, 'type') else disc_model.type,
                    "severity": disc.severity if hasattr(disc, 'severity') else disc_model.severity,
                    "description": disc.description if hasattr(disc, 'description') else disc_model.description,
                    "source_documents": disc.source_documents if hasattr(disc, 'source_documents') else disc_model.source_documents,
                    "details": disc.details if hasattr(disc, 'details') else disc_model.details
                }
                for disc, disc_model in zip(saved_discrepancies, parsed_discrepancies) if saved_discrepancies
            ] or [
                {
                    "type": disc.type,
                    "severity": disc.severity,
                    "description": disc.description,
                    "source_documents": disc.source_documents,
                    "details": disc.details
                }
                for disc in parsed_discrepancies
            ],
            "total": len(parsed_discrepancies),
            "high_risk": len([d for d in parsed_discrepancies if d.severity == "HIGH"]),
            "medium_risk": len([d for d in parsed_discrepancies if d.severity == "MEDIUM"]),
            "low_risk": len([d for d in parsed_discrepancies if d.severity == "LOW"])
        }
        
        logger.info(f"Discrepancy agent: Found {len(parsed_discrepancies)} discrepancies for case {case_id}")
        
        # Update state
        new_state = state.copy()
        new_state["discrepancy_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Discrepancy agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "discrepancy",
            "error": str(e)
        })
        new_state["discrepancy_result"] = None
        return new_state
